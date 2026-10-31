from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import date
from pathlib import Path

from scripts.auto_download.run_all_platform_downloads import (
    ControllerRunLock,
    DEFAULT_CONFIG,
    DEFAULT_MCP_URL,
    DownloadController,
    DownloadStepError,
    configure_logger,
    load_config,
    redact,
    resolve_path,
)

from .checkpoint import restore_legacy_checkpoint
from .flow_runner import FlowRunner
from .registry import business_period, refine_business_period, require_job_spec
from .service import AutomationService, TERMINAL_STATUSES


class CancelledRun(RuntimeError):
    pass


class AutomationWorker:
    def __init__(self, service: AutomationService, worker_name: str = "standalone") -> None:
        self.service = service
        self.worker_id = str(uuid.uuid4())
        self.worker_name = worker_name
        self._stop = threading.Event()
        self._heartbeat("starting")

    def _heartbeat(self, status: str, run_id: str | None = None) -> None:
        with self.service.transaction() as cursor:
            cursor.execute(
                """INSERT INTO ops.automation_worker_heartbeat(
                       worker_id,worker_name,process_id,status,current_run_id,started_at,last_seen_at,stopped_at)
                   VALUES(%s,%s,%s,%s,%s,NOW(),NOW(),CASE WHEN %s IN ('stopped','failed') THEN NOW() END)
                   ON CONFLICT(worker_id) DO UPDATE SET status=EXCLUDED.status,current_run_id=EXCLUDED.current_run_id,
                       last_seen_at=NOW(),stopped_at=CASE WHEN EXCLUDED.status IN ('stopped','failed') THEN NOW() ELSE NULL END""",
                (self.worker_id, self.worker_name, os.getpid(), status, run_id, status),
            )

    def stop(self) -> None:
        self._stop.set()
        self._heartbeat("stopped")

    def recover_stale(self, minimum_age_minutes: int = 15) -> dict[str, int]:
        return self.service.recover_stale(minimum_age_minutes)

    def run_once(self) -> bool:
        now = time.monotonic()
        if now - getattr(self, "_last_journal_sync", -60) >= 30:
            self.service.sync_report_journals()
            self._last_journal_sync = now
        # 长时间运行提醒：同一 Run 的同一次尝试只会入队一次，策略未开启时不写库。
        if now - getattr(self, "_last_stalled_scan", -120) >= 60:
            scan = getattr(self.service, "enqueue_stalled_notifications", None)
            if scan:
                try:
                    scan()
                except Exception:
                    logging.getLogger(__name__).warning("扫描长时间运行通知失败", exc_info=True)
            self._last_stalled_scan = now
        # Feishu Challenge 已回复时，优先把同一 Run 从 needs_human 恢复到 queued。
        # 复用同一 run_id + 既有本地 checkpoint，可避免重复发送验证码/重复创建历史 Run。
        self.service.resume_answered_runs(limit=20, operator=f"AutomationWorker:{self.worker_name}")
        claim = self.service.claim_run(self.worker_id)
        if not claim:
            self._heartbeat("idle")
            return False
        run_id = str(claim["automation_run_id"])
        self._heartbeat("busy", run_id)
        heartbeat_stop = threading.Event()

        def pulse() -> None:
            while not heartbeat_stop.wait(5):
                try:
                    self.service.heartbeat_run(run_id, self.worker_id)
                    self._heartbeat("busy", run_id)
                except Exception as exc:  # keep the execution thread authoritative
                    print(f"AutomationWorker 心跳失败：{redact(exc)}", file=sys.stderr)

        thread = threading.Thread(target=pulse, name=f"automation-heartbeat-{run_id[:8]}", daemon=True)
        thread.start()
        try:
            self._execute_claimed(claim)
        except CancelledRun as exc:
            self.service.finish_run(run_id, "cancelled", error=str(exc))
        except DownloadStepError as exc:
            # Some platform scripts return 1 on verification timeout even when
            # the component emitted waiting_human. Preserve the pause semantics.
            status = (
                "cancelled" if exc.return_code == 130
                else "needs_human" if exc.return_code == 2 or self.service.run_has_unanswered_human(run_id)
                else "failed"
            )
            self.service.finish_run(run_id, status, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - task failure must be persisted
            self.service.finish_run(run_id, "failed", error=str(exc))
        finally:
            heartbeat_stop.set()
            thread.join(timeout=2)
            self._heartbeat("idle")
        return True

    def _execute_claimed(self, claim: dict) -> None:
        job = claim["job"]
        spec = require_job_spec(job["job_code"])
        if spec.job_type == "full_etl":
            self._run_full_etl(claim)
        elif spec.job_type == "flow":
            self._run_flow(claim)
        else:
            self._run_download(claim)

    def _run_full_etl(self, claim: dict) -> None:
        if claim.get('trigger_type') not in {'manual', 'retry'}:
            raise ValueError('全量ETL只允许人工创建，不支持定时调度')
        run_id = str(claim["automation_run_id"])
        step_id = self.service.start_step(run_id, {
            "profile_name": None, "metadata": {}, "step_name": "全量 ETL 刷新",
            "module_name": "apps.file_ingest.service", "execution_lane": "etl",
            "business_period": {"business_date_start": str(claim["business_date"]), "business_date_end": str(claim["business_date"]), "period_type": "day"},
        })
        etl = self.service.file_ingest.create_manual_etl({"scope": "all"}, claim.get("operator") or "AutomationWorker")
        etl_run_id = str(etl["etl_run_id"])
        with self.service.transaction() as cursor:
            cursor.execute("UPDATE ops.automation_run SET etl_run_id=%s,updated_at=NOW() WHERE automation_run_id=%s", (etl_run_id, run_id))
            cursor.execute("UPDATE ops.automation_step_run SET etl_run_id=%s,updated_at=NOW() WHERE step_run_id=%s", (etl_run_id, step_id))
        deadline = time.monotonic() + int(claim["job"]["timeout_seconds"])
        while True:
            if self.service.heartbeat_run(run_id, self.worker_id):
                self.service.finish_step(step_id, "cancelled", {"error_message": "用户请求取消"})
                raise CancelledRun("用户请求取消")
            with self.service.transaction() as cursor:
                cursor.execute("SELECT status,error_message FROM ops.etl_run WHERE etl_run_id=%s", (etl_run_id,))
                state = dict(cursor.fetchone())
            if state["status"] not in {"queued", "running"}:
                break
            if time.monotonic() >= deadline:
                self.service.finish_step(step_id, "failed", {"error_message": "等待 ETL 完成超时"})
                self.service.finish_run(run_id, "failed", error="等待 ETL 完成超时", etl_run_id=etl_run_id)
                return
            time.sleep(2)
        final = {
            "success": "success", "success_with_warnings": "success_with_warnings",
            "no_change": "no_data", "partial_failed": "failed", "failed": "failed",
        }.get(state["status"], "failed")
        self.service.finish_step(step_id, final, {"error_message": state.get("error_message")})
        self.service.finish_run(run_id, final, summary={"etl_status": state["status"]}, error=state.get("error_message"), etl_run_id=etl_run_id)

    def _run_flow(self, claim: dict) -> None:
        run_id = str(claim["automation_run_id"])
        config_path = resolve_path(DEFAULT_CONFIG)
        config = load_config(config_path)
        destination = resolve_path(config.get("destination") or str(self.service.archive_root))
        self.service.archive_root = destination
        log_dir = resolve_path(
            config.get("log_directory")
            or str(destination / ".automation_logs" / "all_platform_downloads")
        )
        logger = configure_logger(log_dir / f"flow_{run_id}.log")
        mcp_url = os.getenv("CLOAK_MCP_URL") or config.get("mcp_url") or DEFAULT_MCP_URL
        run_lock = ControllerRunLock(
            path=log_dir / "controller.lock",
            wait_seconds=0,
            run_id=run_id,
            execution_lane=str(claim["execution_lane"]),
            logger=logger,
        )
        runner = FlowRunner(
            service=self.service,
            claim=claim,
            worker_id=self.worker_id,
            destination=destination,
            logger=logger,
            mcp_url=str(mcp_url),
        )
        try:
            run_lock.acquire()
            result = runner.run()
        finally:
            run_lock.release()
        status = str(result.get("status") or "failed")
        self.service.finish_run(
            run_id,
            status,
            summary=result.get("summary") or {},
            error=result.get("error_message"),
            warning="；".join((result.get("warnings") or [])[:20]) or None,
        )

    def _run_download(self, claim: dict) -> None:
        run_id = str(claim["automation_run_id"])
        lane = claim["execution_lane"]
        config_path = resolve_path(DEFAULT_CONFIG)
        config = load_config(config_path)
        context = claim.get("input_context") or {}
        if claim['job']['job_code'] == 'platform_download_backfill':
            # This snapshot is built by the whitelisted report planner, not HTTP commands.
            config = {**config, **self.service.report_run_snapshot(context)}
            config.pop("profile_rules", None)
        destination = resolve_path(config.get("destination") or str(self.service.archive_root))
        self.service.archive_root = destination
        log_dir = resolve_path(config.get("log_directory") or str(destination / ".automation_logs" / "all_platform_downloads"))
        logger = configure_logger(log_dir / f"automation_{run_id}.log")
        summary_path = log_dir / f"automation_{run_id}.summary.json"
        warnings: list[str] = []
        step_state: dict[str, object] = {"step_id": None, "components": {}}
        periods: dict[str, dict] = {}

        def event_sink(event: str, payload: dict) -> None:
            cancel_requested = self.service.heartbeat_run(run_id, self.worker_id)
            if cancel_requested and event not in {"step_succeeded", "step_failed"}:
                raise CancelledRun("用户请求取消")
            if event == "step_started":
                if payload.get("checkpoint_reused"):
                    # The original successful step is already in this Run's
                    # audit. Do not append another skipped step: it would mask
                    # its Artifact / ODS links in the daily outcome.
                    with self.service.transaction() as cursor:
                        cursor.execute(
                            """SELECT EXISTS(
                                   SELECT 1 FROM ops.automation_step_run
                                   WHERE automation_run_id=%s AND profile_name=%s
                                     AND module_name=%s AND step_name=%s
                                     AND status IN ('success','no_data')
                               ) AS already_recorded""",
                            (run_id, payload.get("profile_name"), payload.get("module_name"), payload.get("step_name")),
                        )
                        previously_recorded = bool(cursor.fetchone()["already_recorded"])
                    if previously_recorded:
                        step_state["step_id"] = None
                        step_state["components"] = {}
                        return
                period = business_period(payload["module_name"], payload.get("args") or [], claim["business_date"])
                payload["business_period"] = period
                step_id = self.service.start_step(run_id, payload)
                step_state["step_id"] = step_id
                step_state["components"] = {}
                periods[step_id] = period
                return
            if event == "plan":
                with self.service.transaction() as cursor:
                    cursor.execute("UPDATE ops.automation_run SET input_context=jsonb_set(input_context,'{report_plan}',%s::jsonb) WHERE automation_run_id=%s",
                                   (json.dumps(payload.get("targets") or [], ensure_ascii=False), run_id))
                return
            if event == "component_event":
                step_id = step_state.get("step_id")
                if not isinstance(step_id, str):
                    return
                component = payload.get("component") or {}
                if not isinstance(component, dict):
                    return
                run_key = str(component.get("component_run_key") or "")
                component_ids = step_state.get("components")
                if not isinstance(component_ids, dict):
                    component_ids = {}
                    step_state["components"] = component_ids
                component_event = str(component.get("event") or "")
                if component_event == "component_started":
                    component_ids[run_key] = self.service.start_component(step_id, payload)
                    return
                component_id = component_ids.get(run_key)
                if not component_id:
                    return
                if component_event == "component_event":
                    self.service.add_component_event(str(component_id), payload)
                    return
                if component_event in {"component_succeeded", "component_failed"}:
                    self.service.finish_component(
                        str(component_id),
                        "success" if component_event == "component_succeeded" else "failed",
                        payload,
                    )
                    return
                return
            if event == 'step_downloaded':
                step_id = step_state.get('step_id')
                if isinstance(step_id, str):
                    period = refine_business_period(payload.get('artifacts') or [], periods[step_id])
                    self.service.record_artifacts(run_id, step_id, payload.get('artifacts') or [], period)
                return
            if event not in {"step_succeeded", "step_failed"}:
                return
            step_id = step_state.get("step_id")
            if not isinstance(step_id, str):
                return
            status = payload.get("status") or ("failed" if event == "step_failed" else "success")
            if event == "step_failed" and status == "failed" and self.service.run_has_unanswered_human(run_id):
                status = "needs_human"
            period = refine_business_period(payload.get("artifacts") or [], periods[step_id])
            periods[step_id] = period
            if event == "step_failed":
                self.service.fail_open_components(step_id, payload.get("error_message"), human_wait=status == "needs_human")
            self.service.finish_step(step_id, status, {
                "duration_seconds": payload.get("duration_seconds"),
                "exit_code": payload.get("return_code"),
                "output_summary": payload.get("output_summary"),
                "error_message": payload.get("error_message"),
                **period,
            })
            artifacts = self.service.record_artifacts(run_id, step_id, payload.get("artifacts") or [], period)
            if event == "step_succeeded":
                if not context.get("download_only"):
                    ingest = self.service.submit_artifacts_to_ingest(run_id, step_id, artifacts)
                    warnings.extend(ingest["warnings"])
            step_state["step_id"] = None
            step_state["components"] = {}
            if cancel_requested:
                raise CancelledRun("用户请求取消")

        mcp_url = os.getenv("CLOAK_MCP_URL") or config.get("mcp_url") or DEFAULT_MCP_URL
        # Isolate new web Run checkpoints. Historic web Runs previously shared
        # the Codex date-scoped JSON; import only steps proven successful in
        # this same Run's DB audit (never successes from a different run).
        run_checkpoint = log_dir / "checkpoints" / f"automation_run_{run_id}.json"
        if int(claim.get("resume_count") or 0) > 0 and not run_checkpoint.is_file():
            legacy_file = config.get("checkpoint_file")
            legacy_dir = config.get("checkpoint_directory")
            legacy_checkpoint = (
                resolve_path(str(legacy_file))
                if legacy_file
                else (
                    resolve_path(str(legacy_dir)) if legacy_dir
                    else log_dir / "checkpoints"
                ) / f"checkpoint_{claim['business_date']}.json"
            )
            with self.service.transaction() as cursor:
                cursor.execute(
                    """SELECT DISTINCT profile_name,module_name,step_name
                       FROM ops.automation_step_run
                       WHERE automation_run_id=%s AND profile_name IS NOT NULL
                         AND status IN ('success','no_data')""",
                    (run_id,),
                )
                verified_steps = [
                    (row["profile_name"], row["module_name"], row["step_name"])
                    for row in cursor.fetchall()
                ]
            restored = restore_legacy_checkpoint(
                legacy_checkpoint, run_checkpoint,
                scope=str(claim["business_date"]), successful_steps=verified_steps,
            )
            if restored:
                logger.info(
                    "已将旧日期检查点中属于本 Run 的 %s 个成功步骤恢复为独立检查点：%s",
                    restored, run_id,
                )
            elif verified_steps:
                # Safety: never blindly replay already-successful exports.
                # Without the original JSON's exact step args, DB-only
                # reconstruction could mistake a changed step for its old one.
                raise RuntimeError(
                    "无法恢复本 Run 已成功步骤的历史检查点；为避免重复创建平台导出任务，"
                    "已停止自动续跑。请恢复原检查点文件，或新建独立任务重新执行。"
                )
        config = {**config, "checkpoint_file": str(run_checkpoint)}
        controller = DownloadController(
            config=config, config_path=config_path, destination=destination, logger=logger,
            run_id=run_id, summary_path=summary_path, mcp_url=str(mcp_url),
            checkpoint_scope=str(claim["business_date"]), execution_lane=lane, event_sink=event_sink,
        )
        run_lock = ControllerRunLock(
            path=log_dir / "controller.lock", wait_seconds=0, run_id=run_id,
            execution_lane=lane, logger=logger,
        )
        try:
            run_lock.acquire()
            try:
                exit_code = controller.run()
            except BaseException as exc:
                if isinstance(exc, DownloadStepError) and (
                    exc.return_code == 2 or self.service.run_has_unanswered_human(run_id)
                ):
                    controller.summary["status"] = "needs_human"
                elif isinstance(exc, (CancelledRun, KeyboardInterrupt)) or (
                    isinstance(exc, DownloadStepError) and exc.return_code == 130
                ):
                    controller.summary["status"] = "cancelled"
                else:
                    controller.summary["status"] = "failed"
                controller.summary["error"] = redact(exc)
                controller.write_summary()
                raise
            else:
                controller.write_summary()
        finally:
            run_lock.release()
        if exit_code != 0:
            self.service.finish_run(run_id, "failed", summary=controller.summary, error="下载总控返回失败")
            return
        self.service.sync_downstream_links(run_id)
        with self.service.transaction() as cursor:
            # Earlier failed/paused attempts remain in the audit timeline but
            # must not poison the final status once this same Run succeeds.
            cursor.execute(
                """SELECT status,COUNT(*) AS count FROM (
                       SELECT DISTINCT ON (COALESCE(profile_name,''),module_name,step_name)
                              status
                       FROM ops.automation_step_run
                       WHERE automation_run_id=%s
                       ORDER BY COALESCE(profile_name,''),module_name,step_name,sequence_no DESC
                   ) latest GROUP BY status""",
                (run_id,),
            )
            counts = {row["status"]: int(row["count"]) for row in cursor.fetchall()}
        if counts.get("needs_human"):
            final = "needs_human"
        elif counts.get("failed"):
            final = "failed"
        elif counts and set(counts) == {"skipped"}:
            final = "skipped"
        elif counts and set(counts) <= {"no_data", "skipped"}:
            final = "no_data"
        elif warnings or controller.summary.get("status") == "success_with_warnings":
            final = "success_with_warnings"
        else:
            final = "success"
        public_controller_summary = {
            key: controller.summary.get(key)
            for key in (
                "run_id", "status", "started_at", "finished_at", "execution_lane",
                "plan_count", "lane_plan_count", "profiles", "warnings", "cleanup_errors",
            )
            if key in controller.summary
        }
        self.service.finish_run(run_id, final, summary={
            "controller": public_controller_summary,
            "step_counts": counts,
            "artifact_warnings": warnings,
        }, warning="；".join(warnings[:20]) if warnings else None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Automation Workbench 独立编排 Worker")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--pg-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    return parser


def main() -> int:
    from apps.fund_split_adjust.server import load_project_env

    load_project_env()
    args = build_parser().parse_args()
    args.password = os.getenv("PGPASSWORD")
    service = AutomationService(args)
    if args.migrate:
        for item in service.migrate():
            print(f"已执行 SQL：{item}")
    worker = AutomationWorker(service)
    recovered = worker.recover_stale()
    if any(recovered.values()):
        print(f"已恢复中断 Automation 任务：{recovered}")
    if args.once:
        try:
            worker.run_once()
        finally:
            worker.stop()
        return 0
    print("AutomationWorker 已启动，按 Ctrl+C 退出")
    try:
        while True:
            if not worker.run_once():
                time.sleep(max(0.5, min(args.poll_seconds, 30)))
    except KeyboardInterrupt:
        return 0
    finally:
        worker.stop()


if __name__ == "__main__":
    raise SystemExit(main())
