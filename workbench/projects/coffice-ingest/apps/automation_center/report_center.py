"""Report calendar and historical batches on the existing automation queue."""
from __future__ import annotations

import calendar
import json
import logging
import os
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from psycopg2.extras import Json

from scripts.auto_download.ledger import atomic_json, confirmed_no_data, journal_process_running
from scripts.auto_download.run_all_platform_downloads import (
    CloakMcpClient, DownloadController, DEFAULT_MCP_URL, as_list, load_config,
)
from .dim_matching import load_dim_rows, resolve_dim
from .report_config import config_path, profile_enabled, profile_reason, report_enabled, update_profile_settings
from .report_plan import SINGLE_DAY, china_today, consecutive_ranges, dates_between, fingerprint, historical_step, selected_dates, step_reports
from .report_sync import reconcile_report_ingest


def bounded_page(value, *, default: int, maximum: int | None = None, label: str = "参数") -> int:
    if value in (None, ""):
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    return max(1, min(number, maximum) if maximum else number)


class ReportCenterMixin:
    def report_run_snapshot(self, context: dict) -> dict:
        batch_id = str(context.get('batch_id') or '')
        uuid.UUID(batch_id)
        with self.transaction() as cursor:
            cursor.execute('SELECT plan_snapshot FROM ops.automation_download_batch WHERE batch_id=%s',(batch_id,))
            batch=cursor.fetchone()
        if not batch:
            raise ValueError('补跑批次不存在')
        matches=[p for p in batch['plan_snapshot']['plans'] if p['profile_name']==context.get('profile_name')]
        if len(matches)!=1:
            raise ValueError('运行Profile与补跑批次计划不一致')
        return {'version':3,'profiles':matches}

    def _report_config(self):
        config = load_config(config_path())
        # A supplied archive root (e.g. isolated tests) wins over the desktop default.
        return config

    def report_targets(self) -> dict:
        config = self._report_config()
        cache = self.archive_root / ".automation_logs/report_ledger/inventory.json"
        snapshot = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else None
        warning = None
        if snapshot is None:
            try:
                logger = logging.getLogger("report-inventory")
                client = CloakMcpClient(os.getenv("CLOAK_MCP_URL") or config.get("mcp_url") or DEFAULT_MCP_URL, logger)
                client.initialize(); client.load_tools()
                profiles = as_list(client.call("list_profiles", {}), label="list_profiles")
                controller = DownloadController.__new__(DownloadController)
                controller.config, controller.client, controller.logger = config, client, logger
                controller.summary = {"profiles": []}
                plans = controller._materialize_profile_plans(profiles)
                snapshot = {"targets": [{"profile_name": p["profile_name"], "profile_id": p["_profile_id"],
                                         "metadata": p["_metadata"], "steps": p["steps"]} for p in plans],
                            "disabled": controller.summary["profile_inventory"]["disabled_profiles"],
                            "updated_at": datetime.now().astimezone().isoformat()}
                atomic_json(cache, snapshot)
            except Exception as exc:
                if snapshot is None:
                    raise ValueError("无法读取Cloak Profile清单，请检查 Cloak Login 或等待总控下一次同步") from exc
                warning = "Cloak暂不可用，展示上次清单；提交补跑时会再次核验"
        items = []
        with self.transaction() as cursor:
            dim_rows = load_dim_rows(cursor)
            for target in snapshot["targets"]:
                metadata = target["metadata"]
                dim = resolve_dim(dim_rows, metadata)
                shop_ok = profile_enabled(config, target["profile_name"])
                shop_reason = profile_reason(config, target["profile_name"])
                for step in target["steps"]:
                    for report in step_reports(metadata["platform"], step):
                        report_ok = report_enabled(config, target["profile_name"], report.report_type)
                        disabled_reason = None
                        if not shop_ok:
                            disabled_reason = shop_reason
                        elif not report_ok:
                            disabled_reason = "该报表已在店铺配置中停用"
                        items.append({"target_key": target["profile_name"] + "|" + report.report_type,
                                      "profile_name": target["profile_name"], "profile_id": target.get("profile_id"),
                                      **metadata, **dim, "report_type": report.report_type, "report_name": report.report_name,
                                      "enabled": bool(shop_ok and report_ok), "profile_enabled": bool(shop_ok),
                                      "report_enabled": bool(report_ok), "disabled_reason": disabled_reason, "step": step})
        return {"items": items, "disabled": snapshot.get("disabled", []),
                "updated_at": snapshot["updated_at"], "warning": warning}

    def sync_report_journals(self, *, journal_key: str | None = None) -> int:
        root = self.archive_root / ".automation_logs/report_ledger"
        imported = 0
        journals = []
        if journal_key is not None and not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', journal_key):
            raise ValueError('非法运行标识')
        paths = [root / (journal_key + '.json')] if journal_key else sorted(root.glob('*.json'))
        for path in paths:
            if path.name == "inventory.json":
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logging.getLogger(__name__).warning("下载日志尚不可读：%s", path.name)
                continue
            if not data.get("external"):
                continue
            events = data.get("events") or []
            if not any(e["event"] in {"completed", "gate"} for e in events) and journal_process_running(data) is False:
                events = events + [{"event":"completed", "payload":{"status":"failed", "reason":"执行进程已退出，等待处理后补跑"}}]
            journals.append((data, events))
        if not journals:
            return 0
        # Most files are immutable, completed history. Read their offsets in
        # one connection; only changed journals need a locking transaction.
        with self.transaction() as cursor:
            cursor.execute("SELECT journal_key,imported_events FROM ops.automation_download_journal WHERE journal_key=ANY(%s::text[])",
                           ([data["run_id"] for data, _ in journals],))
            offsets = {row["journal_key"]: row["imported_events"] for row in cursor.fetchall()}
            # Import completion is asynchronous and may happen after the last
            # journal event. Reconcile even when every event offset is current.
            reconcile_report_ingest(cursor)
            self._recover_empty_report_results(cursor)
        for data, events in journals:
            key = data["run_id"]
            if key in offsets and int(offsets[key]) >= len(events):
                continue
            run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "mock-coffice-download:" + key))
            with self.transaction() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("report-journal:" + key,))
                cursor.execute("SELECT * FROM ops.automation_download_journal WHERE journal_key=%s", (key,))
                previous = cursor.fetchone()
                offset = int(previous["imported_events"]) if previous else 0
                if offset >= len(events):
                    continue
                lane = data.get("execution_lane")
                job_code = "platform_download_overnight" if lane == "overnight" else "platform_download_interactive"
                cursor.execute("SELECT job_id FROM ops.automation_job WHERE job_code=%s", (job_code,))
                job = cursor.fetchone()
                if not job:
                    raise ValueError("请先执行自动化迁移")
                started = datetime.fromisoformat(data["started_at"])
                cursor.execute("""INSERT INTO ops.automation_run(automation_run_id,job_id,input_context,trigger_type,schedule_key,
                    business_date,status,execution_lane,operator,started_at,attempt_started_at,heartbeat_at)
                    VALUES(%s,%s,%s,%s,%s,%s,'running',%s,'ExternalDownload',%s,%s,NOW())
                    ON CONFLICT(automation_run_id) DO NOTHING""",
                    (run_id, job["job_id"], Json({"execution_source": "external", "journal_key": key}),
                     data.get("trigger_type") if data.get("trigger_type") in {"manual", "schedule"} else "manual",
                     "external:" + key, started.astimezone(ZoneInfo('Asia/Shanghai')).date(), "overnight" if lane == "overnight" else "interactive", started, started))
                refs = dict(previous["step_refs"]) if previous else {}
                plan = previous["plan_snapshot"] if previous else []
                for number, event in enumerate(events[offset:], start=offset + 1):
                    payload, kind = event["payload"], event["event"]
                    if kind == "plan":
                        plan = payload["targets"]
                    elif kind in {"step_started", "step_downloaded", "step_succeeded", "step_failed"}:
                        identity = "|".join(str(payload.get(k) or "") for k in ("profile_name", "module_name", "step_name"))
                        step_id = refs.setdefault(identity, str(uuid.uuid5(uuid.NAMESPACE_URL, run_id + identity)))
                        metadata = payload.get("metadata") or {}
                        dim = self._resolve_dim(cursor, metadata)
                        # Preserve the actual execution even when a Profile
                        # needs mapping. Its files cannot count as verified
                        # coverage or be submitted for ingest without DIM.
                        period = payload.get("business_period") or {}
                        artifacts = payload.get("artifacts") or []
                        dated = [a for a in artifacts if a.get('business_date_start') and a.get('business_date_end')]
                        if dated:
                            period = {**period, **{k: dated[0].get(k) for k in ("business_date_start", "business_date_end", "period_type")}}
                        status = "running" if kind in {"step_started", "step_downloaded"} else payload.get("status") or ("failed" if kind == "step_failed" else "success")
                        cursor.execute("""INSERT INTO ops.automation_step_run(step_run_id,automation_run_id,sequence_no,platform_code,
                            platform_name,company_code,company_name,shop_code,shop_name,profile_name,step_name,module_name,
                            execution_lane,status,business_date_start,business_date_end,period_type,started_at,finished_at,error_message)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(step_run_id) DO UPDATE SET status=EXCLUDED.status,
                            finished_at=EXCLUDED.finished_at,business_date_start=COALESCE(EXCLUDED.business_date_start,ops.automation_step_run.business_date_start),
                            business_date_end=COALESCE(EXCLUDED.business_date_end,ops.automation_step_run.business_date_end),
                            period_type=CASE WHEN EXCLUDED.period_type='unknown' THEN ops.automation_step_run.period_type ELSE EXCLUDED.period_type END,
                            error_message=EXCLUDED.error_message""",
                            (step_id, run_id, number, dim.get("platform_code"), metadata.get("platform"), dim.get("company_code"),
                             metadata.get("company"), dim.get("shop_code"), metadata.get("shop"), payload.get("profile_name"),
                             payload.get("step_name"), payload.get("module_name"), lane if lane != "all" else "interactive", status,
                             period.get("business_date_start"), period.get("business_date_end"), period.get("period_type") or "unknown",
                             payload.get("started_at") or started, None if kind == 'step_downloaded' else payload.get("finished_at"),
                             payload.get("reason") if payload.get("reason") in {'report_not_ready', 'ingest_failed'} else None))
                        for artifact in artifacts:
                            relative = str(artifact["relative_path"])
                            actual = (self.archive_root / relative).resolve()
                            actual.relative_to(self.archive_root.resolve())
                            cursor.execute("""INSERT INTO ops.automation_artifact(artifact_id,automation_run_id,step_run_id,
                                artifact_type,file_name,relative_path,file_size_bytes,file_hash,report_type,
                                business_date_start,business_date_end,period_type,coverage_verified)
                                VALUES(%s,%s,%s,'report_file',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                ON CONFLICT(automation_run_id,step_run_id,relative_path) DO NOTHING""",
                                (str(uuid.uuid5(uuid.NAMESPACE_URL, step_id + relative)), run_id, step_id,
                                 artifact["file_name"], relative, artifact["file_size_bytes"], artifact.get("file_hash"),
                                 artifact.get("report_type"), artifact.get("business_date_start"), artifact.get("business_date_end"),
                                 artifact.get("period_type") or "unknown", bool(artifact.get("coverage_verified") and dim.get("shop_code"))))
                        ingest_run_id = (payload.get('ingest') or {}).get('ingest_run_id')
                        if ingest_run_id:
                            cursor.execute('UPDATE ops.automation_step_run SET ingest_run_id=%s,updated_at=NOW() WHERE step_run_id=%s',
                                           (ingest_run_id, step_id))
                            cursor.execute('UPDATE ops.automation_run SET ingest_run_id=COALESCE(ingest_run_id,%s),updated_at=NOW() WHERE automation_run_id=%s',
                                           (ingest_run_id, run_id))
                    elif kind in {"completed", "gate"}:
                        status = payload.get("status") or "skipped"
                        if status == "skip_non_workday":
                            status = "skipped"
                        cursor.execute("""UPDATE ops.automation_run SET status=%s,result_summary=%s,
                            finished_at=%s,heartbeat_at=NOW(),updated_at=NOW() WHERE automation_run_id=%s""",
                            (status, Json(payload), payload.get("finished_at") or datetime.now().astimezone(), run_id))
                        if status in {'failed','cancelled'}:
                            cursor.execute("UPDATE ops.automation_step_run SET status=%s,finished_at=NOW() WHERE automation_run_id=%s AND status='running'", (status,run_id))
                cursor.execute("""INSERT INTO ops.automation_download_journal(journal_key,automation_run_id,imported_events,step_refs,plan_snapshot)
                    VALUES(%s,%s,%s,%s,%s) ON CONFLICT(journal_key) DO UPDATE SET imported_events=EXCLUDED.imported_events,
                    step_refs=EXCLUDED.step_refs,plan_snapshot=EXCLUDED.plan_snapshot,updated_at=NOW()""",
                    (key, run_id, len(events), Json(refs), Json(plan)))
                reconcile_report_ingest(cursor, run_id)
                imported += 1
        return imported

    def _recover_empty_report_results(self, cursor):
        """Recover old CLI empty results from their matching durable run summary."""
        cursor.execute("""SELECT s.step_run_id,s.profile_name,s.module_name,s.step_name,r.input_context->>'journal_key' AS journal_key
            FROM ops.automation_step_run s JOIN ops.automation_run r USING(automation_run_id)
            WHERE s.module_name='kuaishou_settlement_download' AND s.status='success'
              AND r.input_context ? 'journal_key'
              AND NOT EXISTS(SELECT 1 FROM ops.automation_artifact a WHERE a.step_run_id=s.step_run_id)""")
        candidates = list(cursor.fetchall())
        if not candidates:
            return
        config = self._report_config()
        log_root = Path(config.get('log_directory') or self.archive_root / '.automation_logs/all_platform_downloads')
        summaries = {}
        for step in candidates:
            key = step['journal_key']
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', key):
                continue
            if key not in summaries:
                try:
                    data = json.loads((log_root / (key+'.summary.json')).read_text(encoding='utf-8'))
                    summaries[key] = data if data.get('run_id') == key else {}
                except (OSError, ValueError):
                    summaries[key] = {}
            for profile in summaries[key].get('profiles', []):
                if (profile.get('profile_name') or profile.get('profile')) != step['profile_name']:
                    continue
                for result in profile.get('steps', []):
                    if (result.get('module') == step['module_name'] and result.get('name') == step['step_name']
                            and result.get('return_code') == 0 and not result.get('artifacts')
                            and confirmed_no_data(step['module_name'], result.get('output_summary') or '')):
                        cursor.execute("UPDATE ops.automation_step_run SET status='no_data',updated_at=NOW() WHERE step_run_id=%s", (step['step_run_id'],))

    def _report_evidence(self, first: date, last: date, *, include_executions: bool = True, date_basis: str = 'business'):
        execution_day = "(COALESCE(s.started_at,r.started_at,r.queued_at) AT TIME ZONE 'Asia/Shanghai')::date"
        artifact_window = f'{execution_day} BETWEEN %s AND %s' if date_basis == 'execution' else 'a.business_date_start<=%s AND a.business_date_end>=%s'
        step_window = f'{execution_day} BETWEEN %s AND %s' if date_basis == 'execution' else 's.business_date_start<=%s AND s.business_date_end>=%s'
        window = (first, last) if date_basis == 'execution' else (last, first)
        with self.transaction() as cursor:
            cursor.execute(f"""SELECT a.*,s.profile_name,s.status AS step_status,s.step_name,s.module_name,
                       s.finished_at AS downloaded_at,{execution_day} AS execution_date,
                       r.finished_at,r.automation_run_id,r.status AS run_status,
                       CASE WHEN t.status IN ('uploaded','processing') AND ir.status IN ('failed','partial_failed') THEN 'failed'
                            ELSE COALESCE(t.status,CASE WHEN s.error_message='ingest_failed' THEN 'failed' END) END AS ingest_file_status,
                       t.finished_at AS ingest_finished_at,COALESCE(t.error_message,ir.error_message) AS ingest_error
                       FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id)
                       JOIN ops.automation_run r ON r.automation_run_id=s.automation_run_id
                       LEFT JOIN ops.ingest_file_task t ON t.file_task_id=a.ingest_file_task_id
                       LEFT JOIN ops.ingest_run ir ON ir.run_id=t.run_id
                       WHERE r.trigger_type <> 'test' AND {artifact_window}
                       ORDER BY s.started_at DESC,a.created_at DESC""", window)
            artifacts = [dict(row) for row in cursor.fetchall()]
            cursor.execute(f"""SELECT s.*,r.status AS run_status,{execution_day} AS execution_date FROM ops.automation_step_run s
                       JOIN ops.automation_run r USING(automation_run_id)
                       WHERE r.trigger_type <> 'test' AND {step_window}
                       ORDER BY s.started_at DESC,s.sequence_no DESC""", window)
            steps = [dict(row) for row in cursor.fetchall()]
            runs = []
            if include_executions:
                cursor.execute("""SELECT r.automation_run_id,r.business_date,r.status,r.result_summary,r.started_at,r.finished_at,r.input_context,
                       (COALESCE(r.started_at,r.queued_at) AT TIME ZONE 'Asia/Shanghai')::date AS execution_date,
                       ARRAY(SELECT DISTINCT s.profile_name FROM ops.automation_step_run s
                             WHERE s.automation_run_id=r.automation_run_id AND s.profile_name IS NOT NULL)
                       || CASE WHEN r.input_context ? 'profile_name' THEN ARRAY[r.input_context->>'profile_name'] ELSE ARRAY[]::text[] END AS profiles
                       FROM ops.automation_run r JOIN ops.automation_job j USING(job_id)
                       WHERE r.trigger_type <> 'test' AND j.job_type IN ('platform_download','flow')
                         AND (COALESCE(r.started_at,r.queued_at) AT TIME ZONE 'Asia/Shanghai')::date BETWEEN %s AND %s
                       ORDER BY r.created_at DESC""", (first, last))
                runs = [dict(row) for row in cursor.fetchall()]
            # Queued child runs already describe exact requested dates even
            # before a Worker has produced its first step.
            cursor.execute("""SELECT automation_run_id,status,input_context,created_at FROM ops.automation_run
                       WHERE trigger_type <> 'test' AND input_context ? 'batch_id'
                       ORDER BY created_at DESC LIMIT 2000""")
            pending_runs = [dict(row) for row in cursor.fetchall()]
        from .registry import business_period
        for run in pending_runs:
            context = run["input_context"]
            for plan in (context.get("config_snapshot") or {}).get("profiles", []):
                for step in plan.get("steps", []):
                    period = business_period(step["module"], step.get("args") or [], last)
                    steps.append({"profile_name": plan["profile_name"], "module_name": step["module"],
                                  "step_name": step["name"], "status": run["status"], "automation_run_id": run["automation_run_id"],
                                  "started_at": run["created_at"], 'execution_date': run['created_at'].astimezone(ZoneInfo('Asia/Shanghai')).date(),
                                  "business_date_start": date.fromisoformat(period["business_date_start"]),
                                  "business_date_end": date.fromisoformat(period["business_date_end"])})
        steps.sort(key=lambda step: step["started_at"] or datetime.min.astimezone(), reverse=True)
        archive_root = self.archive_root.resolve()
        file_sizes = {}
        for artifact in artifacts:
            relative = artifact["relative_path"]
            if relative not in file_sizes:
                try:
                    path = (archive_root / relative).resolve()
                    path.relative_to(archive_root)
                    file_sizes[relative] = path.stat().st_size if path.is_file() else None
                except (ValueError, OSError):
                    file_sizes[relative] = None
            artifact["file_exists"] = file_sizes[relative] is not None and file_sizes[relative] == artifact["file_size_bytes"]
        return artifacts, steps, runs

    @staticmethod
    def _index_report_evidence(artifacts, steps):
        by_report, by_module = defaultdict(list), defaultdict(list)
        for artifact in artifacts:
            by_report[(artifact["profile_name"], artifact.get("report_type"))].append(artifact)
        for step in steps:
            by_module[(step["profile_name"], step["module_name"])].append(step)
        return by_report, by_module

    @staticmethod
    def _report_outcome(target, day, artifacts, steps, *, date_basis='business'):
        if isinstance(artifacts, dict):
            artifacts = artifacts.get((target["profile_name"], target["report_type"]), [])
        if isinstance(steps, dict):
            steps = steps.get((target["profile_name"], target["step"]["module"]), [])
        # 完成判定只看「文件存在 + 业务期间覆盖 + 非月报」。
        # coverage_verified 仍用于上传/审计（写入时要求 DIM 唯一匹配），但历史数据里
        # 它曾因全/半角括号导致的映射失败被误置为 False；若这里再依赖该标记，
        # 已经下载成功的报表会永远显示“未获取”。读取时以归档事实为准。
        matches = [a for a in artifacts if a["profile_name"] == target["profile_name"] and
                   a.get("report_type") == target["report_type"] and
                   (a.get('execution_date') == day if date_basis == 'execution' else
                    a.get('business_date_start') and a.get('business_date_end') and a['business_date_start'] <= day <= a['business_date_end'])]
        valid = [a for a in matches if a["file_exists"] and (date_basis == 'execution' or a.get("period_type") != "month")]
        if valid:
            return "success", valid[0]
        if matches:
            return ("monthly_only" if any(a["file_exists"] for a in matches) else "missing_file"), matches[0]
        if not target["enabled"]:
            return "disabled", None
        empty = None
        latest = None
        for step in steps:
            named_report = target["report_name"] in step["step_name"] or step["step_name"] == target["step"].get("name")
            covered = step.get('execution_date') == day if date_basis == 'execution' else (
                step.get('business_date_start') and step.get('business_date_end') and step['business_date_start'] <= day <= step['business_date_end'])
            if step["profile_name"] == target["profile_name"] and step["module_name"] == target["step"]["module"] and named_report and covered:
                if step['status'] == 'no_data':
                    empty = step
                if latest is None:
                    latest = step
        if empty:
            return 'no_data', empty
        if latest:
            if "REPORT_NOT_READY" in (latest.get("output_summary") or "") or latest.get("error_message") == "report_not_ready":
                return "not_ready", latest
            return latest["status"] if latest["status"] not in {"success", "skipped", "success_with_warnings"} else "unverified", latest
        return "missing", None

    @staticmethod
    def _report_date_basis(query):
        basis = str(query.get('date_basis') or 'business')
        if basis not in {'business', 'execution'}:
            raise ValueError('date_basis仅支持business、execution')
        return basis

    @staticmethod
    def _filter_targets(targets: list[dict], query: dict) -> list[dict]:
        for field in ("platform", "company", "shop", "profile_name", "report_type"):
            if query.get(field):
                targets = [item for item in targets if str(item.get(field) or "") == str(query[field])]
        for plural, field in (("profiles", "profile_name"), ("report_types", "report_type")):
            if query.get(plural):
                selected = {value for value in str(query[plural]).split(",") if value}
                targets = [item for item in targets if item.get(field) in selected]
        keyword = str(query.get("keyword") or "").strip()
        if keyword:
            needle = keyword.casefold()
            targets = [item for item in targets
                       if needle in " ".join(str(item.get(key) or "") for key in
                                             ("platform", "shop", "company", "profile_name", "report_name")).casefold()]
        return targets

    @staticmethod
    def _upload_status(artifact: dict | None) -> str:
        if not artifact:
            return "not_uploaded"
        return str(artifact.get("ingest_file_status") or "not_uploaded")

    def _shop_groups(self, items: list[dict]) -> list[dict]:
        """按 Profile 聚合报表；同一店铺的不同账号（如财务账号）必须保持独立可配置。"""

        groups: dict[str, dict] = {}
        order: list[str] = []
        for item in items:
            key = str(item["profile_name"])
            group = groups.get(key)
            if group is None:
                group = {
                    "key": key, "profile_name": item["profile_name"], "platform": item.get("platform"),
                    "company": item.get("company"), "shop": item.get("shop"), "shop_code": item.get("shop_code"),
                    "mapping_status": item.get("mapping_status"), "mapping_ok": bool(item.get("mapping_ok")),
                    "mapping_label": item.get("mapping_label"), "mapping_reason": item.get("mapping_reason"),
                    "mapping_candidates": item.get("mapping_candidates") or [],
                    "enabled": bool(item.get("profile_enabled")), "disabled_reason": item.get("disabled_reason"),
                    "reports": [],
                }
                groups[key] = group
                order.append(key)
            artifact = item.get("artifact") or None
            group["reports"].append({
                "report_type": item["report_type"], "report_name": item["report_name"],
                "enabled": bool(item.get("enabled")), "report_enabled": bool(item.get("report_enabled")),
                "status": item["status"], "upload_status": 'not_required' if item['status'] == 'no_data' else self._upload_status(artifact),
                "run_id": item.get("run_id"),
                "recent_done": item.get("recent_done"), "recent_days": item.get("recent_days"),
                "artifact": None if not artifact else {
                    key: artifact.get(key) for key in
                    ("file_name", "relative_path", "file_exists", "coverage_verified", "period_type",
                     "business_date_start", "business_date_end", "created_at", "downloaded_at", "execution_date",
                     "ingest_file_task_id", "ingest_file_status", "ingest_finished_at", "ingest_error")
                },
            })
        result = []
        for key in order:
            group = groups[key]
            active = [report for report in group["reports"] if report["enabled"]]
            done = [report for report in active if report["status"] in {"success", "no_data"}]
            failed = [report for report in active if report["status"] in {"failed", "missing_file", "needs_human"}]
            uploaded = [report for report in active if report["upload_status"] in {"success", "duplicate"}]
            upload_total = sum(report['upload_status'] != 'not_required' for report in active)
            if not active:
                state = "disabled"
            elif len(done) == len(active):
                state = "success"
            elif done:
                state = "partial"
            else:
                state = "failed" if failed else "pending"
            group.update(
                total=len(active), done=len(done), failed=len(failed), pending=len(active) - len(done),
                uploaded=len(uploaded), upload_total=upload_total, state=state,
            )
            result.append(group)
        shop_names: dict[tuple[str, str], int] = {}
        for group in result:
            identity = (str(group.get("platform") or ""), str(group.get("shop") or ""))
            shop_names[identity] = shop_names.get(identity, 0) + 1
        for group in result:
            identity = (str(group.get("platform") or ""), str(group.get("shop") or ""))
            group["duplicate_shop"] = shop_names.get(identity, 0) > 1
        return result

    @staticmethod
    def _summarize(items: list[dict], shops: list[dict]) -> dict:
        active = [item for item in items if item.get("enabled")]
        done = [item for item in active if item["status"] in {"success", "no_data"}]
        uploaded = [item for item in active
                    if ReportCenterMixin._upload_status(item.get("artifact")) in {"success", "duplicate"}]
        return {
            "shops": len(shops),
            "reports": len(active),
            "download_success": len(done),
            "upload_success": len(uploaded),
            "upload_total": sum(item['status'] != 'no_data' for item in active),
            "pending": len(active) - len(done),
            "failed": sum(1 for item in active if item["status"] in {"failed", "missing_file", "needs_human"}),
            "mapping_issues": sum(1 for shop in shops if not shop["mapping_ok"]),
            "disabled_shops": sum(1 for shop in shops if not shop["enabled"]),
            "disabled_reports": sum(1 for item in items if not item.get("report_enabled")),
            "completion": round(len(done) / len(active) * 100) if active else 0,
        }

    def report_calendar(self, query: dict) -> dict:
        basis = self._report_date_basis(query)
        first = date.fromisoformat(str(query.get("month") or china_today().strftime("%Y-%m")) + "-01")
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        self.sync_report_journals()
        inventory = self.report_targets()
        targets = self._filter_targets(inventory["items"], query)
        artifacts, steps, runs = self._report_evidence(first, last, **({'date_basis': basis} if basis == 'execution' else {}))
        artifacts, steps = self._index_report_evidence(artifacts, steps)
        selected_profiles = {target['profile_name'] for target in targets}
        runs = [run for run in runs if not run['profiles'] or selected_profiles.intersection(run['profiles'])]
        days = []
        for day in dates_between(first, last):
            items = []
            for target in targets:
                status, evidence = self._report_outcome(target, day, artifacts, steps, date_basis=basis)
                artifact = evidence if evidence and "artifact_id" in evidence else None
                items.append({**{k: v for k, v in target.items() if k != "step"}, "status": status,
                              "artifact": artifact,
                              "run_id": str(evidence["automation_run_id"]) if evidence else None})
            shops = self._shop_groups(items)
            executions = [r for r in runs if r["execution_date"] == day]
            counts = {status: sum(1 for i in items if i["status"] == status) for status in {i["status"] for i in items}}
            days.append({"date": day.isoformat(), "items": items, "shops": shops, "counts": counts,
                         "summary": self._summarize(items, shops),
                         "executions": executions,
                         "holiday_skipped": any((r.get("result_summary") or {}).get("status") == "skip_non_workday" for r in executions),
                         "future": day > china_today()})
        if str(query.get("compact") or "").lower() in {"1", "true"}:
            # Calendar cells, gap details and backfill need statuses and
            # identities, not repeated artifact receipts and run snapshots.
            days = [{**{k: v for k, v in day.items() if k not in {"items", "shops", "executions"}},
                     "shops": [self._compact_calendar_shop(shop) for shop in day["shops"]]} for day in days]
            inventory = self._report_inventory_summary(inventory)
        return {"month": first.strftime("%Y-%m"), "days": days, "inventory": inventory,
                "expectation_basis": "current_inventory", "date_semantics": 'execution_date' if basis == 'execution' else 'report_business_date'}

    def report_day(self, query: dict) -> dict:
        """单日 · 按店铺分组的报表状态，供列表视图使用（支持分页）。"""

        day = date.fromisoformat(str(query.get("date") or china_today().isoformat()))
        basis = self._report_date_basis(query)
        page = bounded_page(query.get("page"), default=1, label="page")
        page_size = bounded_page(query.get("page_size") or query.get("limit"), default=20, maximum=100, label="page_size")
        self.sync_report_journals()
        inventory = self.report_targets()
        targets = self._filter_targets(inventory["items"], query)
        recent_days = 7
        artifacts, steps, _ = self._report_evidence(day - timedelta(days=recent_days - 1), day, include_executions=False,
                                                 **({'date_basis': basis} if basis == 'execution' else {}))
        artifacts, steps = self._index_report_evidence(artifacts, steps)
        recent: dict[tuple[str, str], int] = {}
        for cursor_day in dates_between(day - timedelta(days=recent_days - 1), day):
            for target in targets:
                status, _ = self._report_outcome(target, cursor_day, artifacts, steps, date_basis=basis)
                if status in {"success", "no_data"}:
                    key = (target["profile_name"], target["report_type"])
                    recent[key] = recent.get(key, 0) + 1
        items = []
        for target in targets:
            status, evidence = self._report_outcome(target, day, artifacts, steps, date_basis=basis)
            artifact = evidence if evidence and "artifact_id" in evidence else None
            items.append({**{k: v for k, v in target.items() if k != "step"}, "status": status,
                          "artifact": artifact,
                          "run_id": str(evidence["automation_run_id"]) if evidence else None,
                          "recent_done": recent.get((target["profile_name"], target["report_type"]), 0),
                          "recent_days": recent_days})
        shops = self._shop_groups(items)
        total = len(shops)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        window = shops[(page - 1) * page_size:page * page_size]
        return {"date": day.isoformat(), "shops": window, "items": items,
                "summary": self._summarize(items, shops),
                "total": total, "page": page, "page_size": page_size, "pages": pages,
                "inventory": self._report_inventory_summary(inventory),
                "date_semantics": 'execution_date' if basis == 'execution' else 'report_business_date'}

    @staticmethod
    def _report_inventory_summary(inventory):
        return {"updated_at": inventory.get("updated_at"), "warning": inventory.get("warning"),
                "items": [{"company": item.get("company"), "platform": item.get("platform")}
                          for item in inventory["items"]]}

    @staticmethod
    def _compact_calendar_shop(shop):
        result = {key: shop[key] for key in ("key", "profile_name", "platform", "shop", "enabled", "state")}
        result["reports"] = [{**{key: report[key] for key in
            ("report_type", "report_name", "enabled", "status", "upload_status", "run_id")},
            "artifact": {"ingest_finished_at": report["artifact"].get("ingest_finished_at")} if report["artifact"] else None}
            for report in shop["reports"]]
        return result

    def update_report_settings(self, payload: dict, operator: str, ip_address=None) -> dict:
        """写入 Codex 明天读取的同一份 JSON，并返回最新目标清单。"""

        profile_name = str(payload.get("profile_name") or "").strip()
        enabled = payload.get("enabled")
        reports = payload.get("reports")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("enabled 必须是布尔值")
        if reports is not None and not isinstance(reports, dict):
            raise ValueError("reports 必须是对象")
        if enabled is None and not reports:
            raise ValueError("请提供店铺启停或报表启停设置")
        update_profile_settings(profile_name, enabled=enabled, reports=reports,
                                reason=str(payload.get("reason") or ""))
        with self.transaction() as cursor:
            self._audit(cursor, "automation_report_settings", "report_target", profile_name, operator,
                        "更新报表任务配置",
                        {"enabled": enabled, "reports": reports}, ip_address)
        return self.report_targets()

    def preview_report_batch(self, payload: dict) -> dict:
        days = selected_dates(payload)
        basis = self._report_date_basis(payload)
        profiles, types = payload.get("profiles"), payload.get("report_types")
        if not isinstance(profiles, list) or not profiles or any(not isinstance(p, str) for p in profiles):
            raise ValueError("请选择店铺对应的Profile")
        if types is not None and (not isinstance(types, list) or any(not isinstance(t, str) for t in types)):
            raise ValueError("报表类型必须是数组")
        if not isinstance(payload.get("force", False), bool):
            raise ValueError("重新获取选项必须是布尔值")
        self.sync_report_journals()
        inventory = self.report_targets()
        available = {t["profile_name"] for t in inventory["items"]}
        if set(profiles) - available:
            raise ValueError("所选Profile不在当前报表清单中，请刷新店铺")
        targets = [t for t in inventory["items"] if t["profile_name"] in profiles and (not types or t["report_type"] in types)]
        if not targets:
            raise ValueError("所选店铺或报表不在当前目标清单中，请刷新店铺后重试")
        disabled = [t for t in targets if not t["enabled"]]
        if disabled:
            names = "、".join(sorted({f"{t.get('shop') or t['profile_name']}·{t['report_name']}" for t in disabled})[:3])
            raise ValueError(f"所选报表已停用：{names}；请先在店铺配置中启用")
        artifacts, steps, _ = self._report_evidence(days[0], days[-1], include_executions=False,
                                                 **({'date_basis': basis} if basis == 'execution' else {}))
        artifacts, steps = self._index_report_evidence(artifacts, steps)
        plans, skipped, files = {}, 0, 0
        for target in targets:
            missing = set()
            for day in days:
                status, evidence = self._report_outcome(target, day, artifacts, steps, date_basis=basis)
                if status in {"success", "no_data"} and not payload.get("force"):
                    skipped += 1
                else:
                    if basis == 'execution':
                        from .registry import business_period
                        period = business_period(target['step']['module'], target['step'].get('args') or [], day)
                        # An attempted historical task keeps its actual requested
                        # range; never send its execution day to the selectors.
                        if evidence and evidence.get('business_date_start') and evidence.get('business_date_end'):
                            period = evidence
                        start = date.fromisoformat(str(period['business_date_start']))
                        end = date.fromisoformat(str(period['business_date_end']))
                        missing.update(dates_between(start, end))
                    else:
                        missing.add(day)
            if not missing:
                continue
            chunks = [(day, day) for day in sorted(missing)] if target["step"]["module"] in SINGLE_DAY else consecutive_ranges(missing)
            plan = plans.setdefault(target["profile_name"], {
                "profile_name": target["profile_name"], "platform": target["platform"], "steps": [],
                "expected_profile_id": target.get("profile_id"),
                "expected_metadata": {key: target[key] for key in ('platform','company','shop')},
            })
            for start, end in chunks:
                plan["steps"].append(historical_step(target["step"], target["report_name"], start, end))
                files += (end - start).days + 1 if target["step"]["module"] == "qianchuan_promotion_fee_download" else 1
        return {"dates": [day.isoformat() for day in days], "plans": list(plans.values()), "skipped": skipped,
                "step_count": sum(len(p["steps"]) for p in plans.values()), "estimated_files": files,
                "plan_hash": fingerprint({"plans": list(plans.values()), "force": payload.get("force", False)})}

    def create_report_batch(self, payload: dict, operator: str, ip_address=None) -> dict:
        request_key = str(payload.get("request_key") or "")
        try:
            uuid.UUID(request_key)
        except ValueError as exc:
            raise ValueError("补跑请求必须携带UUID幂等键") from exc
        with self.transaction() as cursor:
            cursor.execute("SELECT batch_id FROM ops.automation_download_batch WHERE request_key=%s", (request_key,))
            existing = cursor.fetchone()
        if existing:
            return self.report_batch(str(existing["batch_id"]))
        preview = self.preview_report_batch(payload)
        if not preview["plans"]:
            raise ValueError("所选报表已全部补齐，无需重复获取")
        batch_id = str(uuid.uuid4())
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("backfill-request:" + request_key,))
            cursor.execute("SELECT batch_id FROM ops.automation_download_batch WHERE request_key=%s", (request_key,))
            duplicate = cursor.fetchone()
            if duplicate:
                return self.report_batch(str(duplicate["batch_id"]))
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("backfill:" + preview["plan_hash"],))
            cursor.execute("""SELECT b.batch_id FROM ops.automation_download_batch b WHERE b.plan_hash=%s
                AND EXISTS(SELECT 1 FROM ops.automation_run r WHERE r.input_context->>'batch_id'=b.batch_id::text
                           AND r.status IN ('queued','running','needs_human','failed')) LIMIT 1""", (preview["plan_hash"],))
            existing = cursor.fetchone()
            if existing:
                batch_id = str(existing["batch_id"])
            else:
                cursor.execute("SELECT * FROM ops.automation_job WHERE job_code='platform_download_backfill' AND enabled AND deleted_at IS NULL")
                job = cursor.fetchone()
                if not job:
                    raise ValueError("历史补跑任务未启用，请执行迁移并检查任务配置")
                cursor.execute("""INSERT INTO ops.automation_download_batch(batch_id,request_key,plan_hash,request_context,plan_snapshot,operator)
                    VALUES(%s,%s,%s,%s,%s,%s)""", (batch_id, request_key, preview["plan_hash"],
                    Json({k: payload[k] for k in ("profiles", "report_types", "force", "date_basis") if k in payload} | {"dates": preview["dates"]}), Json(preview), operator))
                for plan in preview["plans"]:
                    context = {"batch_id": batch_id, "profile_name": plan["profile_name"], "download_only": False,
                               "config_snapshot": {"version": 3, "profiles": [plan]}}
                    cursor.execute("""INSERT INTO ops.automation_run(automation_run_id,job_id,input_context,trigger_type,
                        business_date,status,execution_lane,operator,resource_key)
                        VALUES(%s,%s,%s,'manual',%s,'queued','interactive',%s,'download:controller')""",
                        (str(uuid.uuid4()), job["job_id"], Json(context), date.fromisoformat(preview["dates"][-1]), operator))
                self._audit(cursor, "automation_report_batch", "automation_download_batch", batch_id, operator,
                            "创建历史报表补跑批次", {"steps": preview["step_count"], "profiles": len(preview["plans"])}, ip_address)
        return self.report_batch(batch_id)

    def report_batch(self, batch_id: str) -> dict:
        uuid.UUID(batch_id)
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_download_batch WHERE batch_id=%s", (batch_id,))
            batch = cursor.fetchone()
            if not batch:
                raise ValueError("补跑批次不存在")
            cursor.execute("""SELECT automation_run_id,status,error_message,warning_message,input_context->>'profile_name' AS profile_name,
                started_at,finished_at FROM ops.automation_run WHERE input_context->>'batch_id'=%s ORDER BY created_at""", (batch_id,))
            history = [dict(row) for row in cursor.fetchall()]
            by_profile = {run["profile_name"]: run for run in history}
            runs = list(by_profile.values())
        return {**dict(batch), "runs": runs, "history": history, "completed": sum(r["status"] in {"success", "no_data", "success_with_warnings"} for r in runs), "total": len(runs)}
