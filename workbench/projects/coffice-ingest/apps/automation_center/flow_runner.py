from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
import zipfile
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from scripts.auto_download.move_report import archive_report
from scripts.auto_download.run_all_platform_downloads import (
    CloakMcpClient,
    as_list,
    first_value,
    parse_profile_note,
    redact,
)
from scripts.auto_download.playwright.component_runtime import (
    classify_error,
    component_event_sink,
    component_parent_context,
)
from scripts.auto_download.playwright.jd_download_common import (
    acquire_download_lock,
    release_download_lock,
)
from scripts.auto_download.playwright.jd_order_download import (
    _read_state,
    _state_datetime,
    _state_path,
    _write_state,
    download_task_file,
    ensure_export_created,
    new_authenticated_page,
    open_order_export_page,
    JD_PREFIX,
    decrypt_xlsx,
    extract_order_report,
    recent_month_range,
    request_file_password,
    validate_xlsx as jd_validate_order_report,
    wait_latest_report,
)

from scripts.auto_download.playwright.xiaohongshu_order_download import (
    REPORT_NAME as XHS_ORDER_REPORT_NAME,
    export_orders as xhs_export_orders,
    open_home_page as xhs_open_home_page,
    open_order_management as xhs_open_order_management,
    query_orders as xhs_query_orders,
    select_custom_date_range as xhs_select_custom_date_range,
    select_recent_30_days as xhs_select_recent_30_days,
    validate_order_report as xhs_validate_order_report,
)
from scripts.auto_download.playwright.xiaohongshu_download_common import (
    click_compat as xhs_click_compat,
    latest_bill_row as xhs_latest_bill_row,
    open_report_page as xhs_open_report_page,
    save_download as xhs_save_download,
    select_bill_mode as xhs_select_bill_mode,
    validate_fund_report as xhs_validate_fund_report,
    validate_settlement_report as xhs_validate_settlement_report,
)
from scripts.auto_download.playwright.xiaohongshu_fund_download import (
    FUND_URL as XHS_FUND_URL,
    REPORT_NAME as XHS_FUND_REPORT_NAME,
)
from scripts.auto_download.playwright.xiaohongshu_settlement_download import (
    SETTLEMENT_REPORT_NAME as XHS_SETTLEMENT_REPORT_NAME,
    SETTLEMENT_URL as XHS_SETTLEMENT_URL,
)

from .platform_atomic import PLATFORM_ATOMIC_CODES, execute_platform_atomic
from .registry import COMPONENT_REGISTRY
from .service import AutomationService


_VARIABLE_RE = re.compile(r"^\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}$")
_COMPARISON_RE = re.compile(
    r"^\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}\s*(==|!=)\s*(.*?)\s*$"
)


class FlowExecutionError(RuntimeError):
    def __init__(self, message: str, *, status: str = "failed") -> None:
        super().__init__(message)
        self.status = status


class FlowRunner:
    """Execute published Flow Studio DAGs through a strict handler map."""

    def __init__(
        self,
        *,
        service: AutomationService,
        claim: dict[str, Any],
        worker_id: str,
        destination: Path,
        logger: logging.Logger,
        mcp_url: str,
    ) -> None:
        self.service = service
        self.claim = claim
        self.worker_id = worker_id
        self.destination = Path(destination)
        self.logger = logger
        self.mcp_url = mcp_url
        self.run_id = str(claim["automation_run_id"])
        self.is_test_run = str(claim.get("trigger_type") or "") == "test"
        if claim.get("flow_version_id") and not self.is_test_run:
            self.flow = service.get_flow_version(str(claim["flow_version_id"]))
        else:
            self.flow = service.get_flow(str(claim["flow_id"]))
        self.definition = dict(self.flow.get("definition") or {})
        self.input_context = dict(claim.get("input_context") or {})
        self.business_date = claim["business_date"]
        if isinstance(self.business_date, str):
            self.business_date = date.fromisoformat(self.business_date)
        self.client = CloakMcpClient(mcp_url, logger)
        self.runtime: dict[str, Any] = {
            **dict(self.definition.get("variables") or {}),
            **self.input_context,
            "business_date": self.business_date.isoformat(),
            "run_id": self.run_id,
        }
        self.step_id: str | None = None
        self.page = None
        self.browser = None
        self.playwright = None
        self.profile_id: str | None = None
        self.profile_name = str(self.input_context.get("profile_name") or "").strip()
        self.profile_closed = False
        self.download_lock = None
        self.warnings: list[str] = []
        self.artifact_before: dict[str, tuple[int, int]] = {}
        self.component_ids: dict[str, str] = {}
        self.previous_checkpoints = (
            service.flow_successful_node_checkpoints(self.run_id)
            if int(claim.get("resume_count") or 0) > 0 else {}
        )
        self.handlers = {
            "cloak.profile.start": self._handle_cloak_start,
            "cloak.profile.stop": self._handle_cloak_stop,
            "browser.connect.cdp": self._handle_browser_connect,
            "jd.ensure_login": self._handle_jd_login,
            "jd.order.open_export": self._handle_jd_open_export,
            "report.date_range.set": self._handle_date_range,
            "jd.order.create_export": self._handle_jd_create_export,
            "report.wait_export_ready": self._handle_wait_export,
            "file.download": self._handle_download,
            "human.verification.wait": self._handle_human_verification,
            "file.archive.extract": self._handle_extract_archive,
            "report.validate.schema": self._handle_standard_validate,
            "report.archive": self._handle_standard_archive,
            "ingest.submit": self._handle_ingest_submit,
            "etl.trigger": self._handle_etl_trigger,
            "xhs.order.open_home": self._handle_xhs_order_home,
            "xhs.order.open_management": self._handle_xhs_order_management,
            "xhs.order.set_date": self._handle_xhs_order_date,
            "xhs.order.query": self._handle_xhs_order_query,
            "xhs.order.export": self._handle_xhs_order_export,
            "xhs.report.open": self._handle_xhs_report_open,
            "xhs.report.mode.select": self._handle_xhs_report_mode,
            "xhs.report.latest": self._handle_xhs_report_latest,
            "xhs.report.download": self._handle_xhs_report_download,
            **{code: self._handle_platform_atomic for code in PLATFORM_ATOMIC_CODES},
        }

    _CHECKPOINT_FIELDS = {
        "start_date", "end_date", "use_recent_preset", "downloaded_archive",
        "archived_path", "pending_artifact", "xhs_source", "xhs_business_date",
        "xhs_report_type", "xhs_report_mode", "ingest_run_id", "etl_run_id",
        "pdd_promotion_start", "pdd_promotion_end",
        "pending_artifacts", "artifact_receipts",
    }
    _SKIPPABLE_WITH_ARTIFACT = {
        "file.download", "file.archive.extract", "report.validate.schema",
        "report.archive", "xhs.order.export", "xhs.report.download",
    }

    @classmethod
    def _safe_runtime_value(cls, value):
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (str, bool, int, float)) or value is None:
            return value
        if isinstance(value, dict):
            return {
                str(key): cls._safe_runtime_value(item)
                for key, item in value.items()
                if not any(word in str(key).lower() for word in ("password", "token", "secret", "cookie", "authorization"))
            }
        if isinstance(value, (list, tuple)):
            return [cls._safe_runtime_value(item) for item in value]
        return None

    def _runtime_checkpoint(self) -> dict[str, Any]:
        # Deliberately excludes the Playwright Page, CDP endpoint and any
        # human-answer value. Durable snapshots are not a credential store.
        return {
            key: self._safe_runtime_value(value)
            for key, value in self.runtime.items() if key in self._CHECKPOINT_FIELDS
        }

    def _restore_runtime_checkpoint(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key not in self._CHECKPOINT_FIELDS:
                continue
            if key in {"downloaded_archive", "archived_path", "xhs_source"} and isinstance(value, str):
                value = Path(value)
            if key == "pending_artifact" and isinstance(value, dict):
                value = dict(value)
                for path_key in ("source_path", "archived_path"):
                    if isinstance(value.get(path_key), str):
                        value[path_key] = Path(value[path_key])
            if key == "pending_artifacts" and isinstance(value, list):
                value = [dict(item) for item in value]
                for item in value:
                    for path_key in ("source_path", "archived_path"):
                        if isinstance(item.get(path_key), str):
                            item[path_key] = Path(item[path_key])
            self.runtime[key] = value

    def _checkpoint_can_skip(self, node: dict[str, Any], previous: dict | None) -> bool:
        if not previous or previous.get("component_code") != node["component_code"]:
            return False
        code = node["component_code"]
        values = dict((previous.get("output_snapshot") or {}).get("runtime") or {})
        if code in self._SKIPPABLE_WITH_ARTIFACT:
            artifact = values.get("pending_artifact") or {}
            path = artifact.get("source_path") if isinstance(artifact, dict) else None
            if code == "file.download":
                path = values.get("downloaded_archive")
            if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
                return False
            if code == "report.validate.schema" and not artifact.get("validated"):
                return False
            if code == "report.archive":
                for receipt in values.get("artifact_receipts") or []:
                    candidate = (self.destination / receipt["relative_path"]).resolve()
                    try:
                        candidate.relative_to(self.destination.resolve())
                    except ValueError:
                        return False
                    if not candidate.is_file() or candidate.stat().st_size != receipt["file_size_bytes"]:
                        return False
        elif code == "ingest.submit":
            if not values.get("ingest_run_id"):
                return False
            with self.service.transaction() as cursor:
                cursor.execute("SELECT status FROM ops.ingest_run WHERE run_id=%s", (values["ingest_run_id"],))
                row = cursor.fetchone()
                if not row or row["status"] not in {"success", "success_with_warnings", "no_change"}:
                    return False
        elif code == "etl.trigger":
            if not values.get("etl_run_id"):
                return False
            with self.service.transaction() as cursor:
                cursor.execute("SELECT status FROM ops.etl_run WHERE etl_run_id=%s", (values["etl_run_id"],))
                row = cursor.fetchone()
                if not row or row["status"] not in {"success", "success_with_warnings", "no_change"}:
                    return False
        else:
            # Browser setup, navigation, date-selection and human verification
            # are intentionally replayed so a fresh Python process can attach
            # to the still-running Cloak Profile and reconstruct its context.
            return False
        self._restore_runtime_checkpoint(values)
        return True

    def run(self) -> dict[str, Any]:
        return asyncio.run(self._run_async())

    async def _run_async(self) -> dict[str, Any]:
        if self.flow.get("status") != "published" and not self.is_test_run:
            raise FlowExecutionError("只有已发布 Flow 可以正式执行")
        if self.flow.get("status") == "archived":
            raise FlowExecutionError("已归档 Flow 不能执行")
        definition = self.service._validate_flow_definition(
            self.definition, allow_draft_custom=False
        )
        nodes = self._topological_nodes(definition)
        if not nodes:
            raise FlowExecutionError("Flow 没有可执行节点")
        for node in nodes:
            code = node["component_code"]
            spec = COMPONENT_REGISTRY.get(code)
            if not spec or not spec.flow_executable or code not in self.handlers:
                raise FlowExecutionError(f"组件没有 Flow Handler：{code}")

        self.destination.mkdir(parents=True, exist_ok=True)
        self.artifact_before = self._artifact_snapshot()
        period = self._period()
        self.step_id = self.service.start_step(
            self.run_id,
            {
                "profile_name": self.profile_name,
                "metadata": {},
                "step_name": self.flow["flow_name"],
                "module_name": f"flow:{self.flow['flow_code']}",
                "execution_lane": self.flow["execution_lane"],
                "business_period": period,
            },
        )
        started = time.perf_counter()
        final_status = "success"
        error_message: str | None = None
        artifacts: list[dict[str, Any]] = []
        try:
            for node in nodes:
                if self._cancel_requested():
                    raise FlowExecutionError("用户请求取消 Flow", status="cancelled")
                if not self._condition_true(str(node.get("condition") or "")):
                    self.logger.info(
                        "Flow节点条件为false，跳过：node=%s component=%s",
                        node["id"],
                        node["component_code"],
                    )
                    continue
                checkpoint=self.previous_checkpoints.get(str(node["id"]))
                if self._checkpoint_can_skip(node, checkpoint):
                    self.logger.info("Flow节点沿用同一 Run 的成功检查点：node=%s component=%s", node["id"], node["component_code"])
                    continue
                result = await self._execute_node(node)
                if result == "continue":
                    continue
            artifacts = self._collect_artifacts(self.artifact_before)
            if artifacts:
                self.service.record_artifacts(
                    self.run_id, self.step_id, artifacts, period
                )
        except FlowExecutionError as exc:
            final_status = exc.status
            error_message = str(exc)
        except BaseException as exc:
            final_status = "failed"
            error_message = redact(exc)
            self.logger.exception("Flow执行失败：%s", redact(exc))
        finally:
            if not artifacts and self.runtime.get("artifact_receipts"):
                # An archived report remains usable if a later Flow node fails.
                artifacts = list(self.runtime["artifact_receipts"])
                try:
                    self.service.record_artifacts(self.run_id, self.step_id, artifacts, period)
                except Exception as exc:
                    self.logger.warning("Flow已归档文件未能登记：%s", redact(exc))
            if final_status in {"success", "success_with_warnings", "no_data"}:
                with suppress(Exception):
                    await self._close_profile()
            # Keep the actual browser tab open on failed/human-paused runs.
            # Stopping Playwright only detaches this worker's CDP client; the
            # external Cloak Profile and page remain available to the next
            # attempt or a human operator.
            if self.page is not None and final_status not in {"failed", "needs_human"}:
                with suppress(Exception):
                    if not self.page.is_closed():
                        await self.page.close()
            if self.playwright is not None:
                with suppress(Exception):
                    await self.playwright.stop()
            if self.download_lock is not None:
                with suppress(Exception):
                    await asyncio.to_thread(release_download_lock, self.download_lock)
                self.download_lock = None

        if final_status == "success" and self.warnings:
            final_status = "success_with_warnings"
        if self.step_id:
            self.service.finish_step(
                self.step_id,
                final_status,
                {
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "error_message": error_message,
                    "output_summary": (
                        f"Flow {self.flow['flow_code']} v{self.flow['version']}；"
                        f"components={len(nodes)} artifacts={len(artifacts)}"
                    ),
                    **period,
                },
            )
        return {
            "status": final_status,
            "error_message": error_message,
            "warnings": self.warnings,
            "summary": {
                "flow_id": str(self.flow["flow_id"]),
                "flow_code": self.flow["flow_code"],
                "flow_name": self.flow["flow_name"],
                "flow_version": self.flow["version"],
                "component_count": len(nodes),
                "artifact_count": len(artifacts),
                "profile_name": self.profile_name,
            },
        }

    async def _execute_node(self, node: dict[str, Any]) -> str | None:
        assert self.step_id
        code = node["component_code"]
        spec = COMPONENT_REGISTRY[code]
        configured_retries = int(node.get("retry_count") or 0)
        attempts = 1 + (configured_retries if spec.retryable else 0)
        timeout = int(node.get("timeout_seconds") or spec.timeout_seconds)
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            run_key = str(uuid.uuid4())
            component_id = self.service.start_component(
                self.step_id,
                {
                    "component": {
                        "component_run_key": run_key,
                        "component_code": code,
                        "component_name": node.get("name") or spec.name,
                        "component_version": "1.0.0",
                        "category": spec.category,
                        "attempt_no": attempt,
                        "input_snapshot": {"node_id": node["id"]},
                        "page_url": self._page_url(),
                    }
                },
            )
            self.component_ids[run_key] = component_id
            started = time.perf_counter()
            try:
                self.service.add_component_event(
                    component_id,
                    {
                        "component": {
                            "action": "attempt_started",
                            "message": f"开始第 {attempt}/{attempts} 次执行",
                            "detail": {"node_id": node["id"]},
                        }
                    },
                )
                def telemetry_sink(body: dict[str, Any]) -> None:
                    event = str(body.get("event") or "")
                    nested_key = str(body.get("component_run_key") or "")
                    if not nested_key:
                        return
                    if event == "component_started":
                        nested_id = self.service.start_component(
                            self.step_id,
                            {"component": body},
                        )
                        self.component_ids[nested_key] = nested_id
                        return
                    nested_id = self.component_ids.get(nested_key)
                    if not nested_id:
                        return
                    if event == "component_event":
                        self.service.add_component_event(
                            nested_id,
                            {"component": body},
                        )
                        return
                    if event in {"component_succeeded", "component_failed"}:
                        self.service.finish_component(
                            nested_id,
                            "success" if event == "component_succeeded" else
                            "needs_human" if body.get('error_type') == 'NEEDS_HUMAN' else "failed",
                            {"component": body},
                        )

                with component_event_sink(telemetry_sink, suppress_stdout=True), component_parent_context(run_key, code):
                    await self._await_handler(
                        self.handlers[code](node),
                        timeout_seconds=timeout,
                    )
                self.service.finish_component(
                    component_id,
                    "success",
                    {
                        "component": {
                            "duration_seconds": round(time.perf_counter() - started, 3),
                            "page_url": self._page_url(),
                            "output_snapshot": {"runtime": self._runtime_checkpoint()},
                        }
                    },
                )
                return None
            except FlowExecutionError as exc:
                if exc.status == "cancelled":
                    self.service.finish_component(
                        component_id,
                        "cancelled",
                        {
                            "component": {
                                "duration_seconds": round(time.perf_counter() - started, 3),
                                "error_type": "CANCELLED",
                                "error_message": str(exc),
                                "page_url": self._page_url(),
                            }
                        },
                    )
                    raise
                last_error = exc
            except asyncio.TimeoutError as exc:
                last_error = exc if getattr(exc, 'requires_human', False) else TimeoutError(f"组件 {code} 超过 {timeout} 秒")
            except BaseException as exc:
                last_error = exc
            screenshot = await self._capture_failure(node, attempt)
            requires_human = bool(getattr(last_error, 'requires_human', False))
            is_last = attempt >= attempts or requires_human
            failure_status = (
                "needs_human"
                if is_last and (requires_human or node.get("on_error") == "needs_human" or
                               (code == "human.verification.wait" and isinstance(last_error, (TimeoutError, asyncio.TimeoutError))))
                else "failed"
            )
            self.service.finish_component(
                component_id,
                failure_status,
                {
                    "component": {
                        "duration_seconds": round(time.perf_counter() - started, 3),
                        "error_type": classify_error(last_error),
                        "error_message": redact(last_error),
                        "page_url": self._page_url(),
                        "screenshot_path": screenshot,
                    }
                },
            )
            if requires_human:
                break
            if not is_last:
                self.logger.warning(
                    "组件失败准备重试：component=%s attempt=%s/%s error=%s",
                    code,
                    attempt,
                    attempts,
                    redact(last_error),
                )
                await asyncio.sleep(min(2 * attempt, 5))
                continue

        assert last_error is not None
        on_error = str(node.get("on_error") or "stop")
        if on_error == "continue" and not getattr(last_error, 'requires_human', False):
            warning = f"{code} 失败但配置为继续：{redact(last_error)}"
            self.warnings.append(warning)
            return "continue"
        if getattr(last_error, 'requires_human', False) or on_error == "needs_human" or (code == "human.verification.wait" and
                                         isinstance(last_error, (TimeoutError, asyncio.TimeoutError))):
            raise FlowExecutionError(
                f"{code} 需要人工处理：{redact(last_error)}", status="needs_human"
            )
        raise FlowExecutionError(f"{code} 执行失败：{redact(last_error)}")

    async def _await_handler(self, coroutine, *, timeout_seconds: int) -> Any:
        """Wait for a handler while polling cancellation without losing timeout semantics."""

        task = asyncio.create_task(coroutine)
        deadline = asyncio.get_running_loop().time() + max(1, timeout_seconds)
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise TimeoutError(f"组件执行超过 {timeout_seconds} 秒")
                done, _ = await asyncio.wait({task}, timeout=min(2.0, remaining))
                if task in done:
                    return await task
                if self._cancel_requested():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise FlowExecutionError("用户请求取消 Flow", status="cancelled")
        finally:
            if not task.done():
                task.cancel()

    def _topological_nodes(self, definition: dict[str, Any]) -> list[dict[str, Any]]:
        """Return enabled nodes while preserving dependencies through disabled nodes.

        Authors may disable downstream nodes (for example FileIngest / ETL)
        while retaining the graph for later use.  Simply dropping
        disabled nodes would also drop their incoming/outgoing edges and could
        make a later node (such as cloak.profile.stop) execute too early.  The
        execution DAG therefore contracts disabled nodes: A -> [disabled B] -> C
        becomes A -> C until B is enabled again.
        """

        all_nodes = {item["id"]: item for item in definition["nodes"]}
        enabled = {
            node_id: item
            for node_id, item in all_nodes.items()
            if item.get("enabled", True)
        }
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in all_nodes}
        for edge in definition["edges"]:
            source = edge["source"]
            target = edge["target"]
            if source in outgoing and target in all_nodes:
                outgoing[source].append(target)

        adjacency: dict[str, set[str]] = {node_id: set() for node_id in enabled}
        for source_id in enabled:
            stack = list(outgoing.get(source_id, ()))
            visited: set[str] = set()
            while stack:
                target_id = stack.pop()
                if target_id in visited:
                    continue
                visited.add(target_id)
                if target_id in enabled:
                    if target_id != source_id:
                        adjacency[source_id].add(target_id)
                    continue
                stack.extend(outgoing.get(target_id, ()))

        indegree = {node_id: 0 for node_id in enabled}
        for targets in adjacency.values():
            for target_id in targets:
                indegree[target_id] += 1

        ready = sorted(
            [item for node_id, item in enabled.items() if indegree[node_id] == 0],
            key=lambda item: (item["y"], item["x"], item["id"]),
        )
        result: list[dict[str, Any]] = []
        while ready:
            node = ready.pop(0)
            result.append(node)
            for target_id in sorted(adjacency[node["id"]]):
                indegree[target_id] -= 1
                if indegree[target_id] == 0:
                    ready.append(enabled[target_id])
                    ready.sort(key=lambda item: (item["y"], item["x"], item["id"]))
        if len(result) != len(enabled):
            raise FlowExecutionError("Flow存在循环依赖")
        return result

    def _period(self) -> dict[str, str]:
        start = str(self.input_context.get("start_date") or "").strip()
        end = str(self.input_context.get("end_date") or "").strip()
        if start and end:
            return {
                "business_date_start": start,
                "business_date_end": end,
                "period_type": "date_range",
            }
        start, end = recent_month_range(today=self.business_date)
        return {
            "business_date_start": start,
            "business_date_end": end,
            "period_type": "rolling_30_days",
        }

    def _condition_true(self, expression: str) -> bool:
        expression = expression.strip()
        if not expression:
            return True
        match = _VARIABLE_RE.fullmatch(expression)
        if match:
            return bool(self._lookup(match.group(1)))
        match = _COMPARISON_RE.fullmatch(expression)
        if match:
            left = self._lookup(match.group(1))
            right_text = match.group(3).strip().strip("\"'")
            if right_text.lower() in {"true", "false"}:
                right: Any = right_text.lower() == "true"
            elif right_text.lower() in {"null", "none"}:
                right = None
            else:
                right = right_text
            return (left == right) if match.group(2) == "==" else (left != right)
        raise FlowExecutionError(
            f"不支持的条件表达式：{expression}；仅支持 {{{{var}}}}、==、!="
        )

    def _lookup(self, dotted: str) -> Any:
        value: Any = self.runtime
        for part in dotted.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    def _node_config(self, node: dict[str, Any]) -> dict[str, Any]:
        return self._resolve_value(dict(node.get("config") or {}))

    def _resolve_value(self, value: Any) -> Any:
        if isinstance(value, str):
            match = _VARIABLE_RE.fullmatch(value.strip())
            return self._lookup(match.group(1)) if match else value
        if isinstance(value, list):
            return [self._resolve_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self._resolve_value(item) for key, item in value.items()}
        return value

    def _cancel_requested(self) -> bool:
        return self.service.heartbeat_run(self.run_id, self.worker_id)

    def _page_url(self) -> str | None:
        try:
            url = self.page.url if self.page is not None else None
        except Exception:
            url = None
        return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None

    async def _capture_failure(self, node: dict[str, Any], attempt: int) -> str | None:
        if self.page is None:
            return None
        try:
            if self.page.is_closed():
                return None
            root = self.destination / ".automation_logs" / "flow_runs" / self.run_id
            root.mkdir(parents=True, exist_ok=True)
            safe_code = re.sub(r"[^A-Za-z0-9_.-]+", "_", node["component_code"])
            path = root / f"{node['id']}_{safe_code}_attempt{attempt}.png"
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as exc:
            self.logger.warning("组件失败截图保存失败：%s", redact(exc))
            return None

    def _artifact_snapshot(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        if not self.destination.exists():
            return snapshot
        allowed = {".csv", ".xls", ".xlsx", ".xlsm", ".zip"}
        for path in self.destination.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            if any(part.startswith(".automation_") for part in path.parts):
                continue
            try:
                stat = path.stat()
                snapshot[path.relative_to(self.destination).as_posix()] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            except OSError:
                continue
        return snapshot

    def _collect_artifacts(
        self, before: dict[str, tuple[int, int]]
    ) -> list[dict[str, Any]]:
        receipts = getattr(self, "runtime", {}).get("artifact_receipts")
        if receipts is not None:
            return list(receipts)
        after = self._artifact_snapshot()
        result: list[dict[str, Any]] = []
        for relative, current in after.items():
            if before.get(relative) == current:
                continue
            path = self.destination / relative
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
            except OSError:
                continue
            result.append(
                {
                    "artifact_type": "archive" if path.suffix.lower() == ".zip" else "report_file",
                    "file_name": path.name,
                    "relative_path": relative,
                    "file_size_bytes": current[0],
                    "file_hash": digest.hexdigest(),
                }
            )
        return result

    def _expected_platform(self) -> str | None:
        codes = {str(item.get("component_code") or "") for item in self.definition.get("nodes", [])}
        mapping = (
            ("jd.", "京东"),
            ("xhs.", "小红书"),
            ("douyin.", "抖音"),
            ("qianchuan.", "抖音"),
            ("pinduoduo.", "拼多多"),
            ("kuaishou.", "快手"),
            ("tmall.", "天猫"),
        )
        platforms = {platform for prefix, platform in mapping if any(code.startswith(prefix) for code in codes)}
        if len(platforms) > 1:
            raise FlowExecutionError("单个Flow不能同时混用多个平台专属组件")
        return next(iter(platforms), None)

    def _xhs_profile(self) -> dict[str, Any]:
        profile = self.runtime.get("profile")
        if not isinstance(profile, dict) or profile.get("platform") != "小红书":
            raise FlowExecutionError("当前组件需要小红书 Cloak Profile")
        return profile

    def _xhs_work_dir(self, report_key: str) -> Path:
        profile = self._xhs_profile()
        shop = re.sub(r'[<>:"/\\|?*]+', "_", str(profile.get("shop") or self.profile_name))
        path = self.destination / ".automation_cache" / report_key / shop
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _handle_cloak_start(self, node: dict[str, Any]) -> None:
        if not self.profile_name:
            raise FlowExecutionError("缺少profile_name")
        if not self.client.tool_names:
            await asyncio.to_thread(self.client.initialize)
            await asyncio.to_thread(self.client.load_tools)
        profiles = as_list(
            await asyncio.to_thread(self.client.call, "list_profiles", {}),
            label="list_profiles",
        )
        matches = [
            item
            for item in profiles
            if isinstance(item, dict)
            and str(first_value(item, "name", "profileName") or "").strip()
            == self.profile_name
        ]
        if len(matches) != 1:
            raise FlowExecutionError(
                f"Cloak Profile匹配数量不是1：{self.profile_name} -> {len(matches)}"
            )
        profile = matches[0]
        self.profile_id = str(first_value(profile, "id", "profileId") or "").strip()
        if not self.profile_id:
            raise FlowExecutionError("Cloak Profile缺少id")
        details = await asyncio.to_thread(
            self.client.call, "get_profile", {"id": self.profile_id}
        )
        details = details if isinstance(details, dict) else {}
        note = first_value(details, "note") or first_value(profile, "note")
        metadata = parse_profile_note(note, self.profile_name)
        expected_platform = self._expected_platform()
        if expected_platform and metadata["platform"] != expected_platform:
            raise FlowExecutionError(
                f"当前Flow要求{expected_platform} Profile，实际为{metadata['platform']}"
            )
        self.runtime["profile"] = {
            "id": self.profile_id,
            "name": self.profile_name,
            **metadata,
        }
        active = as_list(
            await asyncio.to_thread(self.client.call, "list_active", {}),
            label="list_active",
        )
        endpoint = None
        for item in active:
            if (
                isinstance(item, dict)
                and str(first_value(item, "id", "profileId") or "") == self.profile_id
            ):
                endpoint = first_value(item, "wsEndpoint", "ws_endpoint")
                break
        if not endpoint:
            started = await asyncio.to_thread(
                self.client.call, "start_profile", {"id": self.profile_id}
            )
            endpoint = first_value(started, "wsEndpoint", "ws_endpoint")
        if not endpoint and "get_cdp_endpoint" in self.client.tool_names:
            endpoint = first_value(
                await asyncio.to_thread(
                    self.client.call, "get_cdp_endpoint", {"id": self.profile_id}
                ),
                "wsEndpoint",
                "ws_endpoint",
            )
        if not isinstance(endpoint, str) or not endpoint.startswith(("ws://", "wss://")):
            raise FlowExecutionError("Cloak Profile没有有效CDP endpoint")
        self.runtime["cdp_url"] = endpoint

        if self.step_id:
            with self.service.transaction() as cursor:
                dim = self.service._resolve_dim(cursor, metadata)
                cursor.execute(
                    """UPDATE ops.automation_step_run
                       SET platform_code=%s,platform_name=%s,company_code=%s,company_name=%s,
                           shop_code=%s,shop_name=%s,profile_name=%s,updated_at=NOW()
                       WHERE step_run_id=%s""",
                    (
                        dim.get("platform_code"),
                        metadata["platform"],
                        dim.get("company_code"),
                        metadata["company"],
                        dim.get("shop_code"),
                        metadata["shop"],
                        self.profile_name,
                        self.step_id,
                    ),
                )

    async def _handle_cloak_stop(self, node: dict[str, Any]) -> None:
        await self._close_profile()

    async def _close_profile(self) -> None:
        if not self.profile_id or self.profile_closed:
            return
        result = await asyncio.to_thread(
            self.client.call, "stop_profile", {"id": self.profile_id}
        )
        if isinstance(result, dict) and result.get("ok") is False:
            raise FlowExecutionError("Cloak stop_profile返回ok=false")
        self.profile_closed = True

    async def _handle_browser_connect(self, node: dict[str, Any]) -> None:
        cdp_url = str(self.runtime.get("cdp_url") or "")
        if not cdp_url:
            raise FlowExecutionError("尚未启动Cloak Profile，缺少CDP地址")
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
        if not self.browser.contexts:
            raise FlowExecutionError("CDP浏览器没有可用上下文")
        self.runtime["browser_connected"] = True

    async def _handle_jd_login(self, node: dict[str, Any]) -> None:
        if self.browser is None or not self.browser.contexts:
            raise FlowExecutionError("浏览器尚未连接")
        if self.download_lock is None:
            self.download_lock = await asyncio.to_thread(acquire_download_lock)
        context = self.browser.contexts[0]
        if int(self.claim.get("resume_count") or 0) > 0:
            # Prefer the original JD tab after an AI fix or human handoff.
            # It may contain an export dialog or a verification prompt which
            # opening an unrelated fresh home tab would discard.
            for candidate in reversed(context.pages):
                if not candidate.is_closed() and candidate.url.startswith(JD_PREFIX):
                    self.page = candidate
                    await candidate.bring_to_front()
                    self.logger.info("Flow 恢复时复用原京东浏览器标签页：%s", candidate.url)
                    break
        if self.page is None:
            self.page = await new_authenticated_page(context)
        self.runtime["logged_in"] = True

    async def _handle_jd_open_export(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用京东页面")
        self.page = await open_order_export_page(self.page)
        self.runtime["order_export_open"] = True

    async def _handle_date_range(self, node: dict[str, Any]) -> None:
        explicit_start = str(self.input_context.get("start_date") or "").strip()
        explicit_end = str(self.input_context.get("end_date") or "").strip()
        if explicit_start and explicit_end:
            start_date, end_date = explicit_start, explicit_end
            use_recent_preset = False
        else:
            start_date, end_date = recent_month_range(today=self.business_date)
            use_recent_preset = True
        self.runtime.update(
            {
                "start_date": start_date,
                "end_date": end_date,
                "use_recent_preset": use_recent_preset,
            }
        )
        profile = self.runtime.get("profile") or {}
        shop = str(profile.get("shop") or self.profile_name)
        work_dir = (
            self.destination
            / ".automation_cache"
            / "jd_order"
            / re.sub(r'[<>:"/\\|?*]+', "_", shop)
        )
        work_dir.mkdir(parents=True, exist_ok=True)
        state_path = _state_path(work_dir)
        state = _read_state(state_path)
        if (
            state.get("start_date") != start_date
            or state.get("end_date") != end_date
            or state.get("stage") == "COMPLETED"
        ):
            state = {
                "platform": profile.get("platform", "京东"),
                "company": profile.get("company", ""),
                "shop": profile.get("shop", ""),
                "start_date": start_date,
                "end_date": end_date,
                "stage": "EXPORT_NOT_CREATED",
            }
            _write_state(state_path, state)
        self.runtime["work_dir"] = work_dir
        self.runtime["state_path"] = state_path
        self.runtime["jd_state"] = state

    async def _handle_jd_create_export(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用京东订单导出页面")
        state_path = self.runtime.get("state_path")
        state = self.runtime.get("jd_state")
        if not isinstance(state_path, Path) or not isinstance(state, dict):
            raise FlowExecutionError("请先执行日期范围组件")
        await ensure_export_created(
            self.page,
            start_date=self.runtime["start_date"],
            end_date=self.runtime["end_date"],
            state_path=state_path,
            state=state,
            allow_rolling_drift=bool(self.runtime["use_recent_preset"]),
            use_recent_preset=bool(self.runtime["use_recent_preset"]),
        )

    async def _handle_wait_export(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用京东页面")
        state = self.runtime.get("jd_state")
        created_after = None
        if isinstance(state, dict) and state.get("creation_proof") == "submitted":
            submitted = _state_datetime(str(state.get("submitted_at") or ""))
            if submitted is not None:
                created_after = submitted - timedelta(minutes=5)
        task = await wait_latest_report(
            self.page,
            start_date=self.runtime["start_date"],
            end_date=self.runtime["end_date"],
            created_after=created_after,
            allow_rolling_drift=bool(self.runtime["use_recent_preset"]),
            timeout_seconds=float(node.get("timeout_seconds") or 900),
        )
        self.runtime["jd_task"] = task

    async def _handle_download(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用京东页面")
        state = self.runtime.get("jd_state")
        state_path = self.runtime.get("state_path")
        work_dir = self.runtime.get("work_dir")
        task = self.runtime.get("jd_task")
        if (
            not isinstance(state, dict)
            or not isinstance(state_path, Path)
            or not isinstance(work_dir, Path)
            or task is None
        ):
            raise FlowExecutionError("下载组件缺少上游任务状态")
        existing = str(state.get("download_path") or "").strip()
        downloaded = Path(existing) if existing else None
        if (
            downloaded is None
            or not downloaded.is_file()
            or downloaded.stat().st_size == 0
        ):
            downloaded = await download_task_file(
                self.page,
                task,
                work_dir=work_dir,
                state_path=state_path,
                state=state,
            )
        elif not zipfile.is_zipfile(downloaded):
            raise FlowExecutionError("状态中的京东订单文件不是有效ZIP")
        self.runtime["downloaded_archive"] = downloaded

    async def _handle_human_verification(self, node: dict[str, Any]) -> None:
        config = self._node_config(node)
        if str(config.get("challenge_type") or "archive_password") != "archive_password":
            raise FlowExecutionError("京东订单参考Flow只支持archive_password Challenge")
        if self.page is None:
            raise FlowExecutionError("没有可用京东页面")
        profile = self.runtime.get("profile") or {}
        state = self.runtime.get("jd_state")
        state_path = self.runtime.get("state_path")
        task = self.runtime.get("jd_task")
        if not isinstance(state, dict) or not isinstance(state_path, Path) or task is None:
            raise FlowExecutionError("Challenge组件缺少订单任务状态")
        password = await request_file_password(
            self.page,
            task,
            platform=str(profile.get("platform") or "京东"),
            company=str(profile.get("company") or ""),
            shop=str(profile.get("shop") or ""),
            state_path=state_path,
            state=state,
        )
        self.runtime["_archive_password"] = password

    async def _handle_extract_archive(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用京东页面")
        state = self.runtime.get("jd_state")
        state_path = self.runtime.get("state_path")
        archive = self.runtime.get("downloaded_archive")
        password = self.runtime.pop("_archive_password", None)
        if (
            not isinstance(state, dict)
            or not isinstance(state_path, Path)
            or not isinstance(archive, Path)
            or not isinstance(password, str)
        ):
            raise FlowExecutionError("解压组件缺少下载文件或临时密码")
        extraction_dir = archive.parent / "extracted"
        state["stage"] = "EXTRACTING"
        _write_state(state_path, state)
        extracted = await asyncio.to_thread(extract_order_report, archive, extraction_dir)
        decrypted = extracted.with_name(f"{extracted.stem}_decrypted.xlsx")
        state["stage"] = "DECRYPTING"
        _write_state(state_path, state)
        try:
            await asyncio.to_thread(decrypt_xlsx, extracted, password, decrypted)
        except ValueError as exc:
            raise FlowExecutionError("京东订单文件提取码错误，请重新运行人工提取码节点") from exc
        state["extracted_path"] = str(extracted)
        state["decrypted_path"] = str(decrypted)
        _write_state(state_path, state)
        self.runtime["pending_artifact"] = {
            "source_path": decrypted,
            "report_name": "订单",
            "validator": "jd.order",
            "business_date": str(self.runtime["end_date"]),
        }

    async def _handle_xhs_order_home(self, node: dict[str, Any]) -> None:
        if self.browser is None or not self.browser.contexts:
            raise FlowExecutionError("浏览器尚未连接")
        self._xhs_profile()
        self.page = await xhs_open_home_page(self.browser.contexts[0], self.profile_name)
        self.runtime["xhs_report_type"] = "order"

    async def _handle_xhs_order_management(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书工作台页面")
        self.page = await xhs_open_order_management(self.page)

    async def _handle_xhs_order_date(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书订单页面")
        start = str(self.input_context.get("start_date") or "").strip()
        end = str(self.input_context.get("end_date") or "").strip()
        if start and end:
            await xhs_select_custom_date_range(self.page, start, end)
            self.runtime["xhs_business_date"] = end
        else:
            await xhs_select_recent_30_days(self.page)
            self.runtime["xhs_business_date"] = self.business_date.isoformat()

    async def _handle_xhs_order_query(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书订单页面")
        await xhs_query_orders(self.page)

    async def _handle_xhs_order_export(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书订单页面")
        source = await xhs_export_orders(self.page, self._xhs_work_dir("xiaohongshu_order"))
        self.runtime["xhs_source"] = source
        self.runtime["xhs_report_type"] = "order"
        self.runtime["pending_artifact"] = {
            "source_path": source,
            "report_name": XHS_ORDER_REPORT_NAME,
            "validator": "xhs.order",
            "business_date": str(self.runtime.get("xhs_business_date") or self.business_date.isoformat()),
        }

    async def _handle_xhs_report_open(self, node: dict[str, Any]) -> None:
        if self.browser is None or not self.browser.contexts:
            raise FlowExecutionError("浏览器尚未连接")
        self._xhs_profile()
        config = self._node_config(node)
        report_type = str(config.get("report_type") or "fund")
        if report_type == "fund":
            target_url = XHS_FUND_URL
        elif report_type == "settlement":
            target_url = XHS_SETTLEMENT_URL
        else:
            raise FlowExecutionError("小红书报表类型仅支持 fund / settlement")
        self.page = await xhs_open_report_page(self.browser.contexts[0], target_url)
        self.runtime["xhs_report_type"] = report_type

    async def _handle_xhs_report_mode(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书报表页面")
        mode = str(self._node_config(node).get("mode") or "day")
        if mode not in {"day", "month"}:
            raise FlowExecutionError("小红书账单周期仅支持 day / month")
        await xhs_select_bill_mode(self.page, mode)
        self.runtime["xhs_report_mode"] = mode

    async def _handle_xhs_report_latest(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书报表页面")
        mode = str(self.runtime.get("xhs_report_mode") or "day")
        from .platform_atomic import _historical_bill_target
        row, business_date = await xhs_latest_bill_row(self.page, mode, _historical_bill_target(self, mode))
        self.runtime["xhs_report_row"] = row
        self.runtime["xhs_business_date"] = business_date

    async def _handle_xhs_report_download(self, node: dict[str, Any]) -> None:
        if self.page is None:
            raise FlowExecutionError("没有可用小红书报表页面")
        row = self.runtime.get("xhs_report_row")
        report_type = str(self.runtime.get("xhs_report_type") or "")
        if row is None or report_type not in {"fund", "settlement"}:
            raise FlowExecutionError("下载组件缺少最新账单定位结果")
        async with self.page.expect_download(timeout=120_000) as download_info:
            await xhs_click_compat(row.get_by_text("下载账单", exact=True))
        fallback = "xiaohongshu_fund.xlsx" if report_type == "fund" else "xiaohongshu_settlement.xlsx"
        source = await xhs_save_download(
            await download_info.value,
            self._xhs_work_dir(f"xiaohongshu_{report_type}"),
            fallback,
        )
        self.runtime["xhs_source"] = source
        report_name = XHS_FUND_REPORT_NAME if report_type == "fund" else XHS_SETTLEMENT_REPORT_NAME
        self.runtime["pending_artifact"] = {
            "source_path": source,
            "report_name": report_name,
            "validator": f"xhs.{report_type}",
            "business_date": str(self.runtime.get("xhs_business_date") or self.business_date.isoformat()),
        }

    async def _handle_standard_validate(self, node: dict[str, Any]) -> None:
        pending = self.runtime.get("pending_artifact")
        if not isinstance(pending, dict):
            raise FlowExecutionError("标准报表校验组件缺少上游 pending_artifact")
        source_value = pending.get("source_path")
        source = source_value if isinstance(source_value, Path) else Path(str(source_value or ""))
        if not source_value or not source.exists() or not source.is_file():
            raise FlowExecutionError(f"待校验文件不存在：{source}")
        validator = str(pending.get("validator") or "").strip()
        if validator == "ks.order":
            from scripts.auto_download.playwright.kuaishou_order_download import validate_xlsx
            await asyncio.to_thread(validate_xlsx, source)
        elif validator == "pdd.settlement":
            from scripts.auto_download.playwright.pinduoduo_settlement_download import validate_report
            await asyncio.to_thread(validate_report, source)
        elif validator == "pdd.promotion":
            from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import validate_download
            profile = self.runtime.get("profile") or {}
            start_raw = self.runtime.get("pdd_promotion_start")
            end_raw = self.runtime.get("pdd_promotion_end")
            summary = await asyncio.to_thread(
                validate_download,
                source,
                str(profile.get("shop") or ""),
                start_date=start_raw,
                end_date=end_raw,
            )
            if not end_raw and summary.get("max_date"):
                pending["business_date"] = str(summary["max_date"])
        else:
            validators = {
                "xhs.order": xhs_validate_order_report,
                "xhs.fund": xhs_validate_fund_report,
                "xhs.settlement": xhs_validate_settlement_report,
                "jd.order": jd_validate_order_report,
            }
            handler = validators.get(validator)
            if handler is None:
                raise FlowExecutionError(f"标准报表校验未注册 validator：{validator or '空'}")
            await asyncio.to_thread(handler, source)
        pending["validated"] = True
        self.runtime["pending_artifact"] = pending

    async def _handle_standard_archive(self, node: dict[str, Any]) -> None:
        multiple = self.runtime.pop("pending_artifacts", None)
        if multiple:
            for artifact in multiple:
                self.runtime["pending_artifact"] = artifact
                await self._handle_standard_archive(node)
            return
        pending = self.runtime.get("pending_artifact")
        if not isinstance(pending, dict):
            raise FlowExecutionError("标准归档组件缺少上游 pending_artifact")
        source_value = pending.get("source_path")
        source = source_value if isinstance(source_value, Path) else Path(str(source_value or ""))
        if not source_value or not source.exists() or not source.is_file():
            raise FlowExecutionError(f"待归档文件不存在：{source}")
        profile = self.runtime.get("profile")
        if not isinstance(profile, dict):
            raise FlowExecutionError("标准归档组件缺少 Profile 业务元数据")
        config = self._node_config(node)
        report_name = str(config.get("report_name") or pending.get("report_name") or "").strip()
        if not report_name:
            raise FlowExecutionError("标准归档组件无法确定标准报表名")
        business_date = str(pending.get("business_date") or self.business_date.isoformat()).strip()
        from scripts.auto_download.ledger import read_receipts
        receipt = self.destination / ".automation_logs" / "report_receipts" / f"flow_{self.run_id}_{uuid.uuid4().hex}.json"
        start, end = self.input_context.get("start_date"), self.input_context.get("end_date")
        if report_name == "千川推广费":
            start = end = None
        try:
            target = await asyncio.to_thread(
                archive_report,
                source,
                str(profile.get("platform") or ""),
                str(profile.get("company") or ""),
                str(profile.get("shop") or ""),
                report_name,
                business_date,
                self.destination,
                period_start=start, period_end=end, receipt_path=receipt,
            )
        except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
            raise FlowExecutionError(f"标准归档失败：{exc}") from exc
        pending["archived_path"] = target
        pending["source_path"] = target
        self.runtime["pending_artifact"] = pending
        self.runtime["archived_path"] = target
        self.runtime.setdefault("artifact_receipts", []).extend(read_receipts(receipt))

    async def _handle_ingest_submit(self, node: dict[str, Any]) -> None:
        assert self.step_id
        period = self._period()
        artifacts = self._collect_artifacts(self.artifact_before)
        saved = self.service.record_artifacts(self.run_id, self.step_id, artifacts, period) if artifacts else []
        if not saved:
            raise FlowExecutionError("API 上传节点没有发现可提交的报表 Artifact")
        result = self.service.submit_artifacts_to_ingest(
            self.run_id,
            self.step_id,
            saved,
            operator="AutomationFlowRunner",
            auto_refresh=False,
        )
        self.warnings.extend(result.get("warnings") or [])
        ingest_run_id = result.get("ingest_run_id")
        if not ingest_run_id:
            raise FlowExecutionError("API 上传没有识别到可导入报表")
        self.runtime["ingest_run_id"] = str(ingest_run_id)
        while True:
            if self._cancel_requested():
                raise FlowExecutionError("用户取消 API 上传等待", status="cancelled")
            with self.service.transaction() as cursor:
                cursor.execute(
                    "SELECT status,error_message FROM ops.ingest_run WHERE run_id=%s",
                    (str(ingest_run_id),),
                )
                row = cursor.fetchone()
            if not row:
                raise FlowExecutionError("FileIngest 会话不存在")
            status = str(row["status"])
            if status in {"success", "no_change"}:
                self.service.sync_downstream_links(self.run_id)
                return
            if status in {"failed", "partial_failed"}:
                raise FlowExecutionError(row.get("error_message") or "FileIngest 导入失败")
            await asyncio.sleep(1)

    async def _handle_etl_trigger(self, node: dict[str, Any]) -> None:
        assert self.step_id
        ingest_run_id = str(self.runtime.get("ingest_run_id") or "")
        if not ingest_run_id:
            raise FlowExecutionError("ETL 节点缺少上游 API 上传结果")
        result = self.service.trigger_etl_for_ingest(
            ingest_run_id,
            operator="AutomationFlowRunner",
        )
        etl_run_id = str(result.get("etl_run_id") or "")
        if not etl_run_id:
            return
        self.runtime["etl_run_id"] = etl_run_id
        with self.service.transaction() as cursor:
            cursor.execute(
                "UPDATE ops.automation_step_run SET etl_run_id=%s,updated_at=NOW() WHERE step_run_id=%s",
                (etl_run_id, self.step_id),
            )
            cursor.execute(
                "UPDATE ops.automation_run SET etl_run_id=%s,updated_at=NOW() WHERE automation_run_id=%s",
                (etl_run_id, self.run_id),
            )
        while True:
            if self._cancel_requested():
                raise FlowExecutionError("用户取消 ETL 等待", status="cancelled")
            with self.service.transaction() as cursor:
                cursor.execute(
                    "SELECT status,error_message FROM ops.etl_run WHERE etl_run_id=%s",
                    (etl_run_id,),
                )
                row = cursor.fetchone()
            if not row:
                raise FlowExecutionError("ETL 运行不存在")
            status = str(row["status"])
            if status in {"success", "success_with_warnings", "no_change"}:
                self.service.sync_downstream_links(self.run_id)
                return
            if status in {"failed", "partial_failed"}:
                raise FlowExecutionError(row.get("error_message") or f"ETL 执行失败：{status}")
            await asyncio.sleep(1)

    async def _handle_platform_atomic(self, node: dict[str, Any]) -> None:
        await execute_platform_atomic(self, node)
