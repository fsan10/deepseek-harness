from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from psycopg2 import errors
from psycopg2.extras import Json, RealDictCursor

from apps.file_ingest.registry import REPORT_BY_TYPE
from apps.file_ingest.service import FileIngestService
from scripts.auto_download.run_all_platform_downloads import redact

from .dim_matching import load_dim_rows, resolve_dim
from .registry import ARCHIVE_ROOT, DOWNLOAD_CONFIG, COMPONENT_REGISTRY, JOB_REGISTRY, PROJECT_ROOT, component_registry_payload, require_job_spec
from .report_center import ReportCenterMixin
from .report_plan import REPORT_NAMES


MIGRATION_FILE = PROJECT_ROOT / "sql/common/430_automation_center_postgres.sql"
LEGACY_ETL_SCHEDULE_RETIREMENT_MIGRATION = (
    PROJECT_ROOT / "sql/common/431_retire_legacy_etl_nightly_schedule_postgres.sql"
)
TERMINAL_STATUSES = {
    "success", "success_with_warnings", "no_data", "needs_human", "failed", "cancelled", "skipped"
}
FINAL_RUN_STATUSES = TERMINAL_STATUSES - {"needs_human"}
RUN_STATUSES = {"queued", "running", *TERMINAL_STATUSES}
SCHEDULE_TYPES = {"manual", "daily"}
OUTPUT_LIMIT = 20_000


def _dict(row) -> dict:
    return dict(row) if row else {}


class AutomationNotFoundError(LookupError):
    http_status = 404


def _iso_date(value: Any, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as exc:
        raise ValueError(f"{label}必须为 YYYY-MM-DD") from exc


def bounded_int(value: Any, *, default: int, minimum: int = 1, maximum: int | None = None, label: str) -> int:
    """解析分页等整数入参。

    前端一旦把 ``NaN`` 之类的非数字写进查询串，裸 ``int()`` 会抛
    ``ValueError: invalid literal for int() with base 10: 'NaN'`` 并被当作 500 返回。
    这里统一转成带字段名的中文提示（服务端映射为 400），数值越界则按边界收敛。
    """

    text = "" if value is None else str(value).strip()
    if not text:
        return default
    try:
        number = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if maximum is not None:
        number = min(number, maximum)
    return max(minimum, number)


class AutomationService(ReportCenterMixin):
    def __init__(self, args, *, file_ingest_service: FileIngestService | None = None, archive_root: Path | None = None):
        self.connect_kwargs = {
            "host": args.host,
            "port": getattr(args, "pg_port", getattr(args, "port", 5432)),
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        }
        self.file_ingest = file_ingest_service or FileIngestService(args)
        if archive_root is None and not os.getenv("AUTOMATION_ARCHIVE_ROOT"):
            from scripts.auto_download.run_all_platform_downloads import load_config, resolve_path
            archive_root = resolve_path(load_config(DOWNLOAD_CONFIG).get("destination") or str(ARCHIVE_ROOT))
        self.archive_root = Path(archive_root or os.getenv("AUTOMATION_ARCHIVE_ROOT") or ARCHIVE_ROOT)

    def connect(self):
        return self.file_ingest.connect()

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> list[str]:
        with self.transaction() as cursor:
            cursor.execute(MIGRATION_FILE.read_text(encoding="utf-8"))
            cursor.execute(LEGACY_ETL_SCHEDULE_RETIREMENT_MIGRATION.read_text(encoding="utf-8"))
            cursor.execute((PROJECT_ROOT / "sql/common/432_automation_report_calendar_postgres.sql").read_text(encoding="utf-8"))
        return [
            str(MIGRATION_FILE.relative_to(PROJECT_ROOT)),
            str(LEGACY_ETL_SCHEDULE_RETIREMENT_MIGRATION.relative_to(PROJECT_ROOT)),
            "sql/common/432_automation_report_calendar_postgres.sql",
        ]

    @staticmethod
    def _validate_schedule(schedule_type: str, config: Any) -> dict:
        if schedule_type not in SCHEDULE_TYPES:
            raise ValueError("schedule_type仅支持 manual 或 daily")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("schedule_config必须是JSON对象")
        if schedule_type == "manual":
            return {}
        raw_times = config.get("times")
        if not isinstance(raw_times, list) or not raw_times:
            raise ValueError("daily调度必须提供至少一个 times 时间")
        normalized: list[str] = []
        for value in raw_times:
            text = str(value or "").strip()
            try:
                parsed = datetime.strptime(text, "%H:%M")
            except ValueError as exc:
                raise ValueError("调度时间必须是 HH:MM") from exc
            item = parsed.strftime("%H:%M")
            if item not in normalized:
                normalized.append(item)
        return {"times": sorted(normalized)}

    @staticmethod
    def _validate_timezone(value: Any) -> str:
        timezone_name = str(value or "Asia/Shanghai").strip()
        if len(timezone_name) > 64:
            raise ValueError("时区名称过长")
        try:
            ZoneInfo(timezone_name)
        except Exception as exc:
            raise ValueError("时区必须是有效的 IANA 时区") from exc
        return timezone_name

    @staticmethod
    def _audit(cursor, operation_type: str, target_type: str, target_key: str, operator: str, description: str, detail: dict | None = None, ip_address: str | None = None) -> None:
        cursor.execute(
            """INSERT INTO ops.operation_log(operation_type,target_type,target_key,operator,ip_address,description,change_detail)
               VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (operation_type, target_type, target_key, operator[:100], ip_address, description, Json(detail or {})),
        )

    @staticmethod
    def _enqueue_notification_cursor(cursor, run: dict) -> None:
        if not run or run.get("trigger_type") == "test":
            return
        event_type = str(run.get("status") or "")
        if event_type not in {"success", "success_with_warnings", "no_data", "needs_human", "failed", "cancelled"}:
            return
        cursor.execute("SELECT to_regclass('ops.automation_notification_policy') AS relation")
        if not cursor.fetchone()["relation"]:
            return
        cursor.execute(
            """SELECT enabled,event_types FROM ops.automation_notification_policy
               WHERE policy_code='default'"""
        )
        policy = cursor.fetchone()
        configured = {str(item) for item in ((policy or {}).get("event_types") or [])}
        if not policy or not policy["enabled"] or event_type not in configured:
            return
        event_key = f"{event_type}:{int(run.get('resume_count') or 0)}"
        payload = {
            "business_date": str(run.get("business_date") or ""),
            "execution_lane": run.get("execution_lane"),
            "resource_key": run.get("resource_key"),
            "resume_count": int(run.get("resume_count") or 0),
        }
        cursor.execute(
            """INSERT INTO ops.automation_notification_outbox(
                   automation_run_id,event_key,event_type,payload,status,next_attempt_at)
               VALUES(%s,%s,%s,%s,'pending',NOW())
               ON CONFLICT(automation_run_id,event_key) DO NOTHING""",
            (str(run["automation_run_id"]), event_key, event_type, Json(payload)),
        )

    def list_jobs(self, *, include_internal: bool = False) -> dict:
        """Return user-facing automation tasks with seven-day health metrics.

        Legacy registry jobs remain execution primitives. Published Flows are
        projected as first-class schedulable tasks using the scheduling fields
        stored on ops.automation_flow.
        """
        success_statuses = "('success','success_with_warnings','no_data','skipped')"
        with self.transaction() as cursor:
            cursor.execute(
                f"""SELECT j.*,
                          recent.automation_run_id AS recent_run_id,
                          recent.status AS recent_status,recent.finished_at AS recent_finished_at,
                          today.status AS today_status,today.automation_run_id AS today_run_id,
                          health.runs_7d,health.success_7d,health.failed_7d,
                          health.avg_duration_seconds,health.last_success_at
                   FROM ops.automation_job j
                   LEFT JOIN LATERAL (
                       SELECT r.automation_run_id,r.status,r.finished_at
                       FROM ops.automation_run r WHERE r.job_id=j.job_id AND r.trigger_type <> 'test'
                       ORDER BY r.created_at DESC LIMIT 1
                   ) recent ON TRUE
                   LEFT JOIN LATERAL (
                       SELECT r.automation_run_id,r.status
                       FROM ops.automation_run r
                       WHERE r.job_id=j.job_id AND r.business_date=CURRENT_DATE AND r.trigger_type <> 'test'
                       ORDER BY r.created_at DESC LIMIT 1
                   ) today ON TRUE
                   LEFT JOIN LATERAL (
                       SELECT COUNT(*) FILTER(WHERE r.status NOT IN ('queued','running'))::int AS runs_7d,
                              COUNT(*) FILTER(WHERE r.status IN {success_statuses})::int AS success_7d,
                              COUNT(*) FILTER(WHERE r.status='failed')::int AS failed_7d,
                              ROUND((AVG(EXTRACT(EPOCH FROM (r.finished_at-r.started_at)))
                                    FILTER (WHERE r.started_at IS NOT NULL AND r.finished_at IS NOT NULL))::numeric,1)
                                    AS avg_duration_seconds,
                              MAX(r.finished_at) FILTER(WHERE r.status IN {success_statuses}) AS last_success_at
                       FROM ops.automation_run r
                       WHERE r.job_id=j.job_id AND r.trigger_type <> 'test'
                         AND r.created_at>=NOW()-INTERVAL '7 days'
                   ) health ON TRUE
                   WHERE j.deleted_at IS NULL AND (%s OR j.job_type <> 'flow')
                   ORDER BY j.job_id""",
                (include_internal,)
            )
            items = [dict(row) for row in cursor.fetchall()]
            flows = []
            if not include_internal:
                cursor.execute(
                    f"""SELECT f.*,
                              recent.automation_run_id AS recent_run_id,
                              recent.status AS recent_status,recent.finished_at AS recent_finished_at,
                              today.status AS today_status,today.automation_run_id AS today_run_id,
                              health.runs_7d,health.success_7d,health.failed_7d,
                              health.avg_duration_seconds,health.last_success_at
                       FROM ops.automation_flow f
                       LEFT JOIN LATERAL (
                           SELECT r.automation_run_id,r.status,r.finished_at
                           FROM ops.automation_run r WHERE r.flow_id=f.flow_id AND r.trigger_type <> 'test'
                           ORDER BY r.created_at DESC LIMIT 1
                       ) recent ON TRUE
                       LEFT JOIN LATERAL (
                           SELECT r.automation_run_id,r.status
                           FROM ops.automation_run r
                           WHERE r.flow_id=f.flow_id AND r.business_date=CURRENT_DATE AND r.trigger_type <> 'test'
                           ORDER BY r.created_at DESC LIMIT 1
                       ) today ON TRUE
                       LEFT JOIN LATERAL (
                           SELECT COUNT(*) FILTER(WHERE r.status NOT IN ('queued','running'))::int AS runs_7d,
                                  COUNT(*) FILTER(WHERE r.status IN {success_statuses})::int AS success_7d,
                                  COUNT(*) FILTER(WHERE r.status='failed')::int AS failed_7d,
                                  ROUND((AVG(EXTRACT(EPOCH FROM (r.finished_at-r.started_at)))
                                        FILTER (WHERE r.started_at IS NOT NULL AND r.finished_at IS NOT NULL))::numeric,1)
                                        AS avg_duration_seconds,
                                  MAX(r.finished_at) FILTER(WHERE r.status IN {success_statuses}) AS last_success_at
                           FROM ops.automation_run r
                           WHERE r.flow_id=f.flow_id AND r.trigger_type <> 'test'
                             AND r.created_at>=NOW()-INTERVAL '7 days'
                       ) health ON TRUE
                       WHERE f.status='published' AND f.deleted_at IS NULL
                       ORDER BY f.updated_at DESC,f.flow_name"""
                )
                flows = [dict(row) for row in cursor.fetchall()]
        now = datetime.now(timezone.utc)
        for item in items:
            spec = require_job_spec(item["job_code"])
            item["registry"] = spec.__dict__ if hasattr(spec, "__dict__") else {
                "code": item["job_code"], "job_type": item["job_type"], "execution_lane": item["execution_lane"]
            }
            item["next_run_at"] = self._next_run(item, now)
            item["source_kind"] = "job"
            item["task_key"] = f"job:{item['job_id']}"
            steps = self.job_steps(item)
            item["platforms"] = sorted({step["platform"] for step in steps if step.get("platform")})
            item["report_names"] = sorted({name for step in steps for name in REPORT_NAMES.get(step.get("module"), ())})
        for flow in flows:
            flow_id = str(flow["flow_id"])
            item = {
                "job_id": f"flow:{flow_id}",
                "task_key": f"flow:{flow_id}",
                "source_kind": "flow",
                "flow_id": flow_id,
                "flow_code": flow["flow_code"],
                "flow_version": flow["version"],
                "job_code": flow["flow_code"],
                "job_name": flow["flow_name"],
                "job_type": "flow",
                "enabled": bool(flow.get("enabled", True)),
                "execution_lane": flow["execution_lane"],
                "schedule_type": flow.get("schedule_type") or "manual",
                "schedule_config": flow.get("schedule_config") or {},
                "timezone": flow.get("timezone") or "Asia/Shanghai",
                "retry_policy": flow.get("retry_policy") or {"max_attempts": 1},
                "timeout_seconds": int(flow.get("timeout_seconds") or 21600),
                "default_profile_name": flow.get("default_profile_name"),
                "description": flow.get("description"),
                "recent_run_id": flow.get("recent_run_id"),
                "recent_status": flow.get("recent_status"),
                "recent_finished_at": flow.get("recent_finished_at"),
                "today_status": flow.get("today_status"),
                "today_run_id": flow.get("today_run_id"),
                "runs_7d": int(flow.get("runs_7d") or 0),
                "success_7d": int(flow.get("success_7d") or 0),
                "failed_7d": int(flow.get("failed_7d") or 0),
                "avg_duration_seconds": flow.get("avg_duration_seconds"),
                "last_success_at": flow.get("last_success_at"),
                "registry": {
                    "code": flow["flow_code"],
                    "job_type": "flow",
                    "execution_lane": flow["execution_lane"],
                },
            }
            item["next_run_at"] = self._next_run(item, now)
            item.update(self.flow_report_metadata(flow.get("definition") or {}))
            items.append(item)
        return {"items": items, "total": len(items)}

    @staticmethod
    def flow_report_metadata(definition: dict) -> dict:
        platforms, reports = set(), set()
        platform_names = {"jd": "京东", "douyin": "抖音", "qianchuan": "抖音", "pinduoduo": "拼多多", "kuaishou": "快手", "tmall": "天猫", "xhs": "小红书"}
        report_names = {"order": "订单", "fund": "资金", "settlement": "结算", "aggregate_fund": "聚合账户资金", "alipay": "支付宝账户资金", "union": "淘宝联盟推广费", "wanxiangtai": "万相台推广费", "promotion": "推广费"}
        for node in definition.get("nodes") or []:
            code = str(node.get("component_code") or node.get("code") or "").split(".")
            if not code or code[0] not in platform_names or node.get("enabled") is False:
                continue
            platforms.add(platform_names[code[0]])
            kind = code[1] if len(code) > 1 else ""
            config = node.get("config") or {}
            if code[0] == "qianchuan":
                reports.add("千川推广费")
            elif code[0] == "douyin" and kind == "bill":
                if config.get("report"):
                    reports.add(config["report"])
            elif code[0] == "xhs" and kind == "report":
                if config.get("report_type"):
                    reports.add(report_names.get(config["report_type"], config["report_type"]))
            elif code[0] == "jd" and kind == "promotion":
                if config.get("report_key"):
                    reports.add("京东联盟推广费" if config["report_key"] == "union" else "京东通推广费")
            elif kind in report_names:
                reports.add(report_names[kind])
        return {"platforms": sorted(platforms), "report_names": sorted(reports)}

    def get_job(self, job_id: int) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_job WHERE job_id=%s AND deleted_at IS NULL", (job_id,))
            item = cursor.fetchone()
            if not item:
                raise AutomationNotFoundError("自动化任务不存在")
            result = dict(item)
        result["steps"] = self.job_steps(result)
        result["next_run_at"] = self._next_run(result, datetime.now(timezone.utc))
        return result

    @staticmethod
    def _next_run(job: dict, now_utc: datetime) -> str | None:
        if not job.get("enabled") or job.get("schedule_type") != "daily":
            return None
        try:
            zone = ZoneInfo(job.get("timezone") or "Asia/Shanghai")
            times = (job.get("schedule_config") or {}).get("times") or []
            local_now = now_utc.astimezone(zone)
            candidates = []
            for offset in (0, 1):
                day = local_now.date() + timedelta(days=offset)
                for value in times:
                    hour, minute = (int(part) for part in value.split(":"))
                    candidate = datetime.combine(day, datetime.min.time(), zone).replace(hour=hour, minute=minute)
                    if candidate > local_now:
                        candidates.append(candidate)
            return min(candidates).isoformat() if candidates else None
        except Exception:
            return None

    def update_job(self, job_id: int, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        allowed = {"enabled", "schedule_type", "schedule_config", "timezone", "retry_policy", "timeout_seconds", "description"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"不允许修改字段：{', '.join(sorted(unknown))}")
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_job WHERE job_id=%s AND deleted_at IS NULL FOR UPDATE", (job_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化任务不存在")
            before = dict(row)
            require_job_spec(before["job_code"])
            enabled = payload.get("enabled", before["enabled"])
            if not isinstance(enabled, bool):
                raise ValueError("enabled必须是布尔值")
            schedule_type = str(payload.get("schedule_type", before["schedule_type"])).strip()
            if before['job_code'] == 'full_etl' and schedule_type != 'manual':
                raise ValueError('全量ETL只允许人工创建，不支持定时调度')
            schedule_config = self._validate_schedule(schedule_type, payload.get("schedule_config", before["schedule_config"]))
            timezone_name = self._validate_timezone(payload.get("timezone", before["timezone"]))
            retry_policy = payload.get("retry_policy", before["retry_policy"])
            if not isinstance(retry_policy, dict):
                raise ValueError("retry_policy必须是JSON对象")
            max_attempts = int(retry_policy.get("max_attempts", 1))
            if max_attempts < 1 or max_attempts > 5:
                raise ValueError("max_attempts必须在1到5之间")
            timeout_seconds = int(payload.get("timeout_seconds", before["timeout_seconds"]))
            if timeout_seconds < 60 or timeout_seconds > 86400:
                raise ValueError("timeout_seconds必须在60到86400之间")
            description = str(payload.get("description", before.get("description") or "")).strip()[:2000] or None
            cursor.execute(
                """UPDATE ops.automation_job SET enabled=%s,schedule_type=%s,schedule_config=%s,timezone=%s,
                          retry_policy=%s,timeout_seconds=%s,description=%s,updated_by=%s,updated_at=NOW()
                   WHERE job_id=%s RETURNING *""",
                (enabled, schedule_type, Json(schedule_config), timezone_name, Json({"max_attempts": max_attempts}), timeout_seconds, description, operator, job_id),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_job_update", "automation_job", str(job_id), operator, "更新自动化任务", {
                "before": {key: before.get(key) for key in allowed}, "after": {key: result.get(key) for key in allowed}
            }, ip_address)
        return result

    def set_job_enabled(self, job_id: int, enabled: bool, operator: str, ip_address: str | None = None) -> dict:
        return self.update_job(job_id, {"enabled": bool(enabled)}, operator, ip_address)

    def delete_job(self, job_id: int, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_job WHERE job_id=%s AND deleted_at IS NULL FOR UPDATE", (job_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化任务不存在")
            if row["job_type"] == "flow":
                raise ValueError("内部 Flow 执行器不能删除")
            cursor.execute(
                """UPDATE ops.automation_job
                   SET enabled=FALSE,deleted_at=NOW(),updated_by=%s,updated_at=NOW()
                   WHERE job_id=%s RETURNING *""",
                (operator[:100], job_id),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_job_delete", "automation_job", str(job_id), operator, "删除自动化任务", {"soft_delete": True}, ip_address)
        return result

    def set_flow_enabled(self, flow_id: str, enabled: bool, operator: str, ip_address: str | None = None) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled必须是布尔值")
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s AND deleted_at IS NULL FOR UPDATE", (flow_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化流程不存在")
            cursor.execute(
                """UPDATE ops.automation_flow SET enabled=%s,updated_by=%s,updated_at=NOW()
                   WHERE flow_id=%s RETURNING *""",
                (enabled, operator[:100], flow_id),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_flow_enabled", "automation_flow", flow_id, operator, "启用/停用自动化流程", {"enabled": enabled}, ip_address)
        return result

    def delete_flow(self, flow_id: str, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s AND deleted_at IS NULL FOR UPDATE", (flow_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化流程不存在")
            cursor.execute(
                """UPDATE ops.automation_flow
                   SET enabled=FALSE,status='archived',deleted_at=NOW(),updated_by=%s,updated_at=NOW()
                   WHERE flow_id=%s RETURNING *""",
                (operator[:100], flow_id),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_flow_delete", "automation_flow", flow_id, operator, "删除自动化流程", {"soft_delete": True}, ip_address)
        return result

    def job_steps(self, job: dict) -> list[dict]:
        spec = require_job_spec(job["job_code"])
        if spec.job_type == "full_etl":
            return [{"name": "全量 ETL", "module": "apps.file_ingest.service", "lane": "etl"}]
        if spec.job_type == "flow":
            return [{"name": "由 Flow Studio 选择已发布流程", "module": "apps.automation_center.flow_runner", "lane": spec.execution_lane}]
        config_path = PROJECT_ROOT / "scripts/auto_download/all_platform_downloads.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        result = []
        for rule in data.get("profile_rules", []):
            for step in rule.get("steps", []):
                lanes = step.get("lanes") or ["overnight", "interactive"]
                if spec.execution_lane in lanes:
                    result.append({
                        "platform": rule.get("platform"), "profile_rule": rule.get("name"),
                        "name": step.get("name"), "module": step.get("module"), "lane": spec.execution_lane,
                    })
        return result

    def create_run(self, job_id: int, *, trigger_type: str, operator: str, business_date: date | str | None = None,
                   schedule_key: str | None = None, parent_run_id: str | None = None, ip_address: str | None = None,
                   flow_id: str | None = None, flow_version_id: str | None = None,
                   input_context: dict[str, Any] | None = None) -> dict:
        if trigger_type not in {"manual", "schedule", "retry", "test"}:
            raise ValueError("trigger_type无效")
        business = _iso_date(business_date or date.today(), "business_date")
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_job WHERE job_id=%s AND deleted_at IS NULL FOR SHARE", (job_id,))
            job = cursor.fetchone()
            if not job:
                raise AutomationNotFoundError("自动化任务不存在")
            if not job["enabled"] and trigger_type != "retry":
                raise ValueError("自动化任务已暂停")
            spec = require_job_spec(job["job_code"])
            if spec.job_type == 'full_etl' and trigger_type == 'schedule':
                raise ValueError('全量ETL只允许人工创建，不支持定时调度')
            if job["job_type"] != spec.job_type or job["execution_lane"] != spec.execution_lane:
                raise ValueError("数据库任务定义与 Automation registry 不一致")
            safe_context = input_context or {}
            if not isinstance(safe_context, dict):
                raise ValueError("input_context必须是JSON对象")
            forbidden_context = {"password", "passwd", "token", "secret", "authorization", "cookie", "verification_code"}
            if forbidden_context.intersection(key.lower() for key in safe_context):
                raise ValueError("Flow运行输入禁止保存密码、验证码、Cookie、Token等秘密")

            resolved_flow_version_id = None
            flow = None
            if spec.job_type == "flow":
                if not flow_id:
                    raise ValueError("Flow任务必须提供flow_id")
                cursor.execute(
                    "SELECT * FROM ops.automation_flow WHERE flow_id=%s AND (deleted_at IS NULL OR %s='retry')",
                    (flow_id, trigger_type),
                )
                flow = cursor.fetchone()
                if not flow:
                    raise AutomationNotFoundError("自动化流程不存在")
                historical_retry = trigger_type == "retry" and bool(flow_version_id)
                if trigger_type == "test":
                    if flow["status"] == "archived":
                        raise ValueError("已归档流程不能测试运行")
                elif not historical_retry:
                    if flow["status"] != "published":
                        raise ValueError("只有已发布流程可以运行")
                    if not flow["enabled"]:
                        raise ValueError("自动化流程已停用")
                if trigger_type != "test":
                    if flow_version_id:
                        cursor.execute(
                            """SELECT flow_version_id,execution_lane,flow_name
                               FROM ops.automation_flow_version
                               WHERE flow_version_id=%s AND flow_id=%s""",
                            (flow_version_id, flow_id),
                        )
                        version_row = cursor.fetchone()
                        if not version_row:
                            raise ValueError("指定 Flow 发布版本不存在或不属于当前流程")
                        if version_row["execution_lane"] != spec.execution_lane:
                            raise ValueError("Flow发布版本执行通道与原任务通道不一致")
                        resolved_flow_version_id = str(version_row["flow_version_id"])
                    else:
                        if flow["execution_lane"] != spec.execution_lane:
                            raise ValueError("Flow执行通道与任务通道不一致")
                        cursor.execute(
                            """SELECT flow_version_id FROM ops.automation_flow_version
                               WHERE flow_id=%s AND version=%s""",
                            (flow_id, flow["version"]),
                        )
                        version_row = cursor.fetchone()
                        if not version_row:
                            cursor.execute(
                                """INSERT INTO ops.automation_flow_version(
                                       flow_id,version,flow_code,flow_name,execution_lane,definition,published_by,published_at)
                                   VALUES(%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,NOW()))
                                   ON CONFLICT(flow_id,version) DO NOTHING
                                   RETURNING flow_version_id""",
                                (flow_id, flow["version"], flow["flow_code"], flow["flow_name"],
                                 flow["execution_lane"], Json(flow["definition"]),
                                 flow.get("updated_by") or flow.get("created_by") or "system",
                                 flow.get("updated_at")),
                            )
                            version_row = cursor.fetchone()
                            if not version_row:
                                cursor.execute(
                                    "SELECT flow_version_id FROM ops.automation_flow_version WHERE flow_id=%s AND version=%s",
                                    (flow_id, flow["version"]),
                                )
                                version_row = cursor.fetchone()
                        resolved_flow_version_id = str(version_row["flow_version_id"]) if version_row else None
            elif flow_id or flow_version_id:
                raise ValueError("非Flow任务不能绑定Flow版本")

            profile_name = str(safe_context.get("profile_name") or "").strip()
            if flow_id:
                resource_key = f"profile:{profile_name.casefold()}" if profile_name else f"flow:{flow_id}"
            elif job["job_code"] == "full_etl":
                resource_key = "etl:full"
            else:
                resource_key = "download:controller" if spec.job_type == "platform_download" else f"job:{job['job_code']}"

            run_id = uuid.uuid4()
            try:
                cursor.execute(
                    """INSERT INTO ops.automation_run(
                           automation_run_id,job_id,flow_id,flow_version_id,input_context,trigger_type,schedule_key,
                           business_date,status,execution_lane,operator,parent_run_id,resource_key)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s) RETURNING *""",
                    (str(run_id), job_id, flow_id, resolved_flow_version_id, Json(safe_context),
                     trigger_type, schedule_key, business, spec.execution_lane, operator, parent_run_id, resource_key),
                )
            except errors.UniqueViolation:
                raise
            result = dict(cursor.fetchone())
            result["job_code"] = job["job_code"]
            result["job_name"] = flow["flow_name"] if flow else job["job_name"]
            self._audit(cursor, "automation_run_create", "automation_run", str(run_id), operator, "创建自动化运行", {
                "job_code": job["job_code"], "trigger_type": trigger_type, "schedule_key": schedule_key,
                "flow_id": flow_id, "flow_version_id": resolved_flow_version_id, "resource_key": resource_key,
            }, ip_address)
        return result

    def create_scheduled_run(self, job_id: int, schedule_key: str, business_date: date, operator: str = "AutomationScheduler") -> tuple[dict, bool]:
        try:
            return self.create_run(job_id, trigger_type="schedule", operator=operator, business_date=business_date, schedule_key=schedule_key), True
        except errors.UniqueViolation:
            with self.transaction() as cursor:
                cursor.execute("SELECT * FROM ops.automation_run WHERE job_id=%s AND schedule_key=%s", (job_id, schedule_key))
                return dict(cursor.fetchone()), False

    def create_scheduled_flow_run(self, flow_id: str, schedule_key: str, business_date: date,
                                  operator: str = "AutomationScheduler") -> tuple[dict, bool]:
        flow = self.get_flow(flow_id)
        context = {"profile_name": str(flow.get("default_profile_name") or "").strip()}
        if flow["execution_lane"] != "etl" and not context["profile_name"]:
            raise ValueError(f"Flow {flow['flow_name']} 缺少默认 Cloak Profile，无法定时运行")
        job_id = self._flow_executor_job_id(flow)
        try:
            return self.create_run(
                job_id, trigger_type="schedule", operator=operator, business_date=business_date,
                schedule_key=schedule_key, flow_id=flow_id, input_context=context,
            ), True
        except errors.UniqueViolation:
            with self.transaction() as cursor:
                cursor.execute(
                    "SELECT * FROM ops.automation_run WHERE job_id=%s AND schedule_key=%s",
                    (job_id, schedule_key),
                )
                return dict(cursor.fetchone()), False

    def retry_run(self, run_id: str, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_run WHERE automation_run_id=%s", (run_id,))
            source = cursor.fetchone()
            if not source:
                raise AutomationNotFoundError("自动化运行不存在")
            if (source.get("input_context") or {}).get("execution_source") == "external":
                raise ValueError("Codex/CLI运行请从原入口重试，或在报表日历选择缺失日期补跑")
            if source["status"] not in FINAL_RUN_STATUSES:
                raise ValueError("只有已完成运行可以重试；等待人工请使用继续任务")
        new_run = self.create_run(
            source["job_id"], trigger_type="retry", operator=operator,
            business_date=source["business_date"], parent_run_id=run_id, ip_address=ip_address,
            flow_id=str(source["flow_id"]) if source.get("flow_id") else None,
            flow_version_id=str(source["flow_version_id"]) if source.get("flow_version_id") else None,
            input_context=dict(source.get("input_context") or {}),
        )
        with self.transaction() as cursor:
            # A new Retry Run can inherit the source Run's paused reservation.
            # The previous failed Run stays in the audit trail; the new Run
            # alone may reclaim the Profile after this ownership transfer.
            cursor.execute(
                """UPDATE ops.automation_resource_lock SET automation_run_id=%s
                   WHERE automation_run_id=%s AND lock_state='paused'""",
                (str(new_run["automation_run_id"]), run_id),
            )
        return new_run

    def _flow_run_context(self, payload: dict, *, default_profile_name: str | None = None,
                          require_profile: bool = True) -> tuple[str, dict, date]:
        profile_name = str(payload.get("profile_name") or default_profile_name or "").strip()
        if require_profile and not profile_name:
            raise ValueError("运行Flow必须提供Cloak profile_name")
        if len(profile_name) > 200:
            raise ValueError("profile_name过长")
        context = {
            "profile_name": profile_name,
            "start_date": str(payload.get("start_date") or "").strip() or None,
            "end_date": str(payload.get("end_date") or "").strip() or None,
        }
        if bool(context["start_date"]) != bool(context["end_date"]):
            raise ValueError("start_date和end_date必须同时提供")
        if context["start_date"] and context["end_date"]:
            start = _iso_date(context["start_date"], "start_date")
            end = _iso_date(context["end_date"], "end_date")
            if start > end:
                raise ValueError("start_date不能晚于end_date")
            context["start_date"] = start.isoformat()
            context["end_date"] = end.isoformat()
        business = _iso_date(payload.get("business_date") or date.today(), "business_date")
        return profile_name, context, business

    def _flow_executor_job_id(self, flow: dict) -> int:
        job_code = f"flow_{flow['execution_lane']}"
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT job_id FROM ops.automation_job WHERE job_code=%s AND enabled AND deleted_at IS NULL",
                (job_code,),
            )
            job = cursor.fetchone()
            if not job:
                raise ValueError(f"Flow执行任务{job_code}未启用，请先执行Automation迁移")
            return int(job["job_id"])

    def create_flow_run(self, flow_id: str, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        flow = self.get_flow(flow_id)
        if flow["status"] != "published":
            raise ValueError("只有已发布流程可以运行")
        if not flow.get("enabled", True):
            raise ValueError("自动化流程已停用")
        _, context, business = self._flow_run_context(
            payload, default_profile_name=flow.get("default_profile_name"),
            require_profile=flow.get("execution_lane") != "etl",
        )
        return self.create_run(
            self._flow_executor_job_id(flow), trigger_type="manual", operator=operator,
            business_date=business, flow_id=flow_id, input_context=context, ip_address=ip_address,
        )

    def create_flow_test_run(self, flow_id: str, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        flow = self.get_flow(flow_id)
        if flow["status"] == "archived":
            raise ValueError("已归档流程不能测试运行")
        _, context, business = self._flow_run_context(
            payload, default_profile_name=flow.get("default_profile_name"),
            require_profile=flow.get("execution_lane") != "etl",
        )
        return self.create_run(
            self._flow_executor_job_id(flow), trigger_type="test", operator=operator,
            business_date=business, flow_id=flow_id, input_context=context, ip_address=ip_address,
        )

    def resume_run(self, run_id: str, operator: str, ip_address: str | None = None,
                   reason: str = "manual") -> dict:
        reason = str(reason or "manual").strip()[:120] or "manual"
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT * FROM ops.automation_run
                   WHERE automation_run_id=%s FOR UPDATE""",
                (run_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化运行不存在")
            if (row.get("input_context") or {}).get("execution_source") == "external":
                raise ValueError("Codex/CLI运行由原执行入口续跑；可在报表日历中补跑缺失日期")
            if row["status"] not in {"needs_human", "failed"}:
                raise ValueError("只有等待人工或失败的运行可以继续；取消或已成功的运行请新建")
            if row["status"] == "failed" and reason == "challenge_answered":
                raise ValueError("失败 Run 必须由负责人确认修复后手工继续")
            cursor.execute(
                """UPDATE ops.automation_run
                   SET status='queued',worker_id=NULL,heartbeat_at=NULL,attempt_started_at=NULL,cancel_requested_at=NULL,
                       finished_at=NULL,waiting_since=NULL,resumed_at=NOW(),resume_count=resume_count+1,
                       resume_reason=%s,error_message=NULL,warning_message=NULL,
                       attention_acknowledged_at=NULL,attention_acknowledged_by=NULL,
                       attention_acknowledged_reason=NULL,updated_at=NOW()
                   WHERE automation_run_id=%s RETURNING *""",
                (reason, run_id),
            )
            result = dict(cursor.fetchone())
            self._audit(
                cursor, "automation_run_resume", "automation_run", run_id, operator,
                "继续等待人工后的自动化运行",
                {"reason": reason, "resume_count": result["resume_count"]},
                ip_address,
            )
            return result

    def acknowledge_run(self, run_id: str, operator: str, reason: str,
                        ip_address: str | None = None) -> dict:
        """Hide an old alert without rewriting the factual run outcome."""
        reason = str(reason or "").strip()
        if not reason or len(reason) > 500:
            raise ValueError("忽略提醒时必须填写 1–500 字原因")
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT * FROM ops.automation_run WHERE automation_run_id=%s FOR UPDATE",
                (run_id,),
            )
            run = cursor.fetchone()
            if not run:
                raise AutomationNotFoundError("自动化运行不存在")
            if run["status"] not in {"failed", "success_with_warnings"}:
                raise ValueError("仅已失败或成功有提醒的运行可忽略；等待人工请继续或取消任务")
            cursor.execute(
                """UPDATE ops.automation_run SET attention_acknowledged_at=NOW(),
                       attention_acknowledged_by=%s,attention_acknowledged_reason=%s,updated_at=NOW()
                   WHERE automation_run_id=%s RETURNING *""",
                (operator[:100], reason, run_id),
            )
            result = dict(cursor.fetchone())
            # Explicitly discarding a failed alert also gives up its reserved
            # browser scene so future schedules are no longer blocked.
            cursor.execute(
                """DELETE FROM ops.automation_resource_lock
                   WHERE automation_run_id=%s AND lock_state='paused'""",
                (run_id,),
            )
            self._audit(
                cursor, "automation_run_attention_acknowledge", "automation_run", run_id,
                operator, "人工忽略自动化异常提醒；保留原失败状态", {"reason": reason},
                ip_address,
            )
            return result

    def run_has_unanswered_human(self, run_id: str) -> bool:
        """A timed-out verification child may exit 1 instead of the legacy exit 2."""
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT EXISTS (
                       SELECT 1 FROM ops.automation_step_run s
                       JOIN ops.automation_run r ON r.automation_run_id=s.automation_run_id
                       JOIN ops.automation_component_run c ON c.step_run_id=s.step_run_id
                       WHERE s.automation_run_id=%s
                         AND s.started_at>=COALESCE(r.resumed_at,r.created_at)
                         AND s.sequence_no=(
                             SELECT MAX(s2.sequence_no) FROM ops.automation_step_run s2
                             WHERE s2.automation_run_id=%s
                         )
                         AND EXISTS(
                             SELECT 1 FROM ops.automation_component_event e
                             WHERE e.component_run_id=c.component_run_id AND e.event_type='waiting_human'
                         )
                         AND NOT EXISTS(
                             SELECT 1 FROM ops.automation_component_event e
                             WHERE e.component_run_id=c.component_run_id AND e.event_type='human_answered'
                         )
                   ) AS pending""",
                (run_id, run_id),
            )
            return bool(cursor.fetchone()["pending"])

    def resume_answered_runs(self, *, limit: int = 20, operator: str = "AutomationWorker") -> list[str]:
        limit = max(1, min(int(limit), 100))
        with self.transaction() as cursor:
            cursor.execute("SELECT to_regclass('ai.verification_challenge') AS relation")
            if not cursor.fetchone()["relation"]:
                return []
            cursor.execute(
                """SELECT DISTINCT r.automation_run_id
                   FROM ops.automation_run r
                   WHERE r.status='needs_human'
                     AND EXISTS (
                         SELECT 1
                         FROM ai.verification_challenge vc
                         WHERE vc.status='answered'
                           AND vc.answered_at IS NOT NULL
                           AND vc.challenge_uuid=COALESCE(
                               (
                                   SELECT c.verification_challenge_id
                                   FROM ops.automation_component_run c
                                   JOIN ops.automation_step_run s ON s.step_run_id=c.step_run_id
                                   WHERE s.automation_run_id=r.automation_run_id
                                     AND s.sequence_no=(
                                         SELECT MAX(s2.sequence_no)
                                         FROM ops.automation_step_run s2
                                         WHERE s2.automation_run_id=r.automation_run_id
                                     )
                                     AND c.verification_challenge_id IS NOT NULL
                                     AND EXISTS (
                                         SELECT 1 FROM ops.automation_component_event e
                                         WHERE e.component_run_id=c.component_run_id
                                           AND e.event_type='waiting_human'
                                     )
                                     AND NOT EXISTS (
                                         SELECT 1 FROM ops.automation_component_event e
                                         WHERE e.component_run_id=c.component_run_id
                                           AND e.event_type='human_answered'
                                     )
                                   ORDER BY c.created_at DESC LIMIT 1
                               ),
                               (
                                   SELECT s.verification_challenge_id FROM ops.automation_step_run s
                                   WHERE s.automation_run_id=r.automation_run_id
                                   ORDER BY s.sequence_no DESC LIMIT 1
                               )
                           )
                     )
                   ORDER BY r.automation_run_id
                   LIMIT %s""",
                (limit,),
            )
            run_ids = [str(row["automation_run_id"]) for row in cursor.fetchall()]
            resumed: list[str] = []
            for candidate in run_ids:
                cursor.execute(
                    """UPDATE ops.automation_run
                       SET status='queued',worker_id=NULL,heartbeat_at=NULL,attempt_started_at=NULL,cancel_requested_at=NULL,
                           finished_at=NULL,waiting_since=NULL,resumed_at=NOW(),resume_count=resume_count+1,
                           resume_reason='challenge_answered',error_message=NULL,updated_at=NOW()
                       WHERE automation_run_id=%s AND status='needs_human'
                       RETURNING resume_count""",
                    (candidate,),
                )
                row = cursor.fetchone()
                if not row:
                    continue
                resumed.append(candidate)
                self._audit(
                    cursor, "automation_run_resume", "automation_run", candidate, operator,
                    "飞书 Challenge 已回复，自动恢复运行",
                    {"reason": "challenge_answered", "resume_count": row["resume_count"]},
                )
            return resumed

    def cancel_run(self, run_id: str, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT status FROM ops.automation_run WHERE automation_run_id=%s FOR UPDATE", (run_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化运行不存在")
            if row["status"] in FINAL_RUN_STATUSES:
                return self._run_detail_cursor(cursor, run_id)
            if row["status"] in {"queued", "needs_human"}:
                cursor.execute(
                    """UPDATE ops.automation_run
                       SET status='cancelled',cancel_requested_at=NOW(),finished_at=NOW(),
                           waiting_since=NULL,worker_id=NULL,heartbeat_at=NULL,updated_at=NOW()
                       WHERE automation_run_id=%s RETURNING *""",
                    (run_id,),
                )
                cancelled = dict(cursor.fetchone())
                cursor.execute("DELETE FROM ops.automation_resource_lock WHERE automation_run_id=%s", (run_id,))
                self._enqueue_notification_cursor(cursor, cancelled)
            else:
                cursor.execute(
                    "UPDATE ops.automation_run SET cancel_requested_at=NOW(),updated_at=NOW() WHERE automation_run_id=%s",
                    (run_id,),
                )
            self._audit(cursor, "automation_run_cancel", "automation_run", run_id, operator, "请求取消自动化运行", None, ip_address)
            return self._run_detail_cursor(cursor, run_id)

    def list_runs(self, query: dict | None = None) -> dict:
        query = query or {}
        page = bounded_int(query.get("page"), default=1, label="page")
        page_size = bounded_int(
            query.get("page_size") or query.get("limit"), default=20, maximum=100, label="page_size"
        )
        conditions = ["r.trigger_type <> 'test'"]
        params: list[Any] = []
        for key, column in {"status": "r.status", "job_id": "r.job_id", "flow_id": "r.flow_id"}.items():
            if query.get(key):
                conditions.append(f"{column}=%s")
                params.append(query[key])
        if query.get("date_from"):
            conditions.append("r.business_date >= %s")
            params.append(_iso_date(query["date_from"], "开始日期"))
        if query.get("date_to"):
            conditions.append("r.business_date <= %s")
            params.append(_iso_date(query["date_to"], "结束日期"))
        keyword = str(query.get("keyword") or "").strip()
        if keyword:
            needle = f"%{keyword}%"
            conditions.append(
                '''(r.automation_run_id::text ILIKE %s
                    OR EXISTS (SELECT 1 FROM ops.automation_job j2 WHERE j2.job_id=r.job_id AND j2.job_name ILIKE %s)
                    OR EXISTS (SELECT 1 FROM ops.automation_flow f2 WHERE f2.flow_id=r.flow_id AND f2.flow_name ILIKE %s)
                    OR EXISTS (SELECT 1 FROM ops.automation_flow_version fv2 WHERE fv2.flow_version_id=r.flow_version_id AND fv2.flow_name ILIKE %s)
                    OR EXISTS (SELECT 1 FROM ops.automation_step_run s WHERE s.automation_run_id=r.automation_run_id
                               AND (s.shop_name ILIKE %s OR s.platform_name ILIKE %s)))'''
            )
            params.extend([needle] * 6)
        where = " AND ".join(conditions)
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM ops.automation_run r WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                """SELECT COUNT(*)::int AS total,
                          COUNT(*) FILTER(WHERE status='failed')::int AS failed
                   FROM ops.automation_run
                   WHERE trigger_type<>'test'"""
            )
            counts = dict(cursor.fetchone())
            cursor.execute(
                f"""SELECT r.*,j.job_code,
                            COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                            j.job_name AS base_job_name,j.job_type,
                            COALESCE(fv.flow_code,f.flow_code) AS flow_code,
                            COALESCE(fv.flow_name,f.flow_name) AS flow_name,
                            COALESCE(fv.version,f.version) AS flow_version,
                            (SELECT COUNT(*) FROM ops.automation_step_run s WHERE s.automation_run_id=r.automation_run_id) AS step_count,
                            (SELECT COUNT(*) FROM ops.automation_artifact a WHERE a.automation_run_id=r.automation_run_id) AS artifact_count
                     FROM ops.automation_run r
                     JOIN ops.automation_job j ON j.job_id=r.job_id
                     LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                     LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                     WHERE {where} ORDER BY r.created_at DESC LIMIT %s OFFSET %s""",
                (*params, page_size, (page - 1) * page_size),
            )
            items = [dict(row) for row in cursor.fetchall()]
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "pages": max(1, (total + page_size - 1) // page_size), "counts": counts}

    def get_run(self, run_id: str) -> dict:
        with self.transaction() as cursor:
            result = self._run_detail_cursor(cursor, run_id)
        if not result:
            raise AutomationNotFoundError("自动化运行不存在")
        return result

    @staticmethod
    def _run_detail_cursor(cursor, run_id: str) -> dict:
        cursor.execute(
            """SELECT r.*,j.job_code,COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                      j.job_name AS base_job_name,j.job_type,
                      COALESCE(fv.flow_code,f.flow_code) AS flow_code,
                      COALESCE(fv.flow_name,f.flow_name) AS flow_name,
                      COALESCE(fv.version,f.version) AS flow_version
               FROM ops.automation_run r
               JOIN ops.automation_job j ON j.job_id=r.job_id
               LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
               LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
               WHERE r.automation_run_id=%s""",
            (run_id,),
        )
        row = cursor.fetchone()
        if not row:
            return {}
        result = dict(row)
        cursor.execute("SELECT * FROM ops.automation_step_run WHERE automation_run_id=%s ORDER BY sequence_no", (run_id,))
        steps = [dict(item) for item in cursor.fetchall()]
        cursor.execute(
            "SELECT * FROM ops.automation_component_run WHERE automation_run_id=%s ORDER BY step_run_id,sequence_no",
            (run_id,),
        )
        components = [dict(item) for item in cursor.fetchall()]
        component_ids = [str(item["component_run_id"]) for item in components]
        events_by_component: dict[str, list[dict]] = {}
        if component_ids:
            cursor.execute(
                """SELECT * FROM ops.automation_component_event
                   WHERE component_run_id = ANY(%s::uuid[]) ORDER BY component_event_id""",
                (component_ids,),
            )
            for event in cursor.fetchall():
                item = dict(event)
                events_by_component.setdefault(str(item["component_run_id"]), []).append(item)
        components_by_step: dict[str, list[dict]] = {}
        for component in components:
            component["events"] = events_by_component.get(str(component["component_run_id"]), [])
            components_by_step.setdefault(str(component["step_run_id"]), []).append(component)
        cursor.execute(
            """SELECT a.*,ft.status AS ingest_file_status,ft.batch_id AS current_batch_id
               FROM ops.automation_artifact a
               LEFT JOIN ops.ingest_file_task ft ON ft.file_task_id=a.ingest_file_task_id
               WHERE a.automation_run_id=%s ORDER BY a.created_at""", (run_id,)
        )
        artifacts = [dict(item) for item in cursor.fetchall()]
        by_step: dict[str, list[dict]] = {}
        for artifact in artifacts:
            by_step.setdefault(str(artifact["step_run_id"]), []).append(artifact)
        for step in steps:
            step["artifacts"] = by_step.get(str(step["step_run_id"]), [])
            step["components"] = components_by_step.get(str(step["step_run_id"]), [])
            if step.get("ingest_run_id"):
                cursor.execute("SELECT * FROM ops.ingest_run WHERE run_id=%s", (step["ingest_run_id"],))
                step["ingest"] = _dict(cursor.fetchone())
                cursor.execute(
                    """SELECT * FROM ops.etl_run WHERE ingest_run_id=%s
                       ORDER BY created_at DESC LIMIT 1""", (step["ingest_run_id"],)
                )
                linked_etl = cursor.fetchone()
                if linked_etl:
                    step["etl"] = dict(linked_etl)
                    step["etl_run_id"] = linked_etl["etl_run_id"]
                    cursor.execute("SELECT * FROM ops.etl_task WHERE etl_run_id=%s ORDER BY sequence_no", (linked_etl["etl_run_id"],))
                    step["etl_tasks"] = [dict(item) for item in cursor.fetchall()]
        result["steps"] = steps
        result["artifacts"] = artifacts
        if result.get("etl_run_id"):
            cursor.execute("SELECT * FROM ops.etl_run WHERE etl_run_id=%s", (result["etl_run_id"],))
            result["etl"] = _dict(cursor.fetchone())
            cursor.execute("SELECT * FROM ops.etl_task WHERE etl_run_id=%s ORDER BY sequence_no", (result["etl_run_id"],))
            result["etl_tasks"] = [dict(item) for item in cursor.fetchall()]
        return result

    def dashboard(self, business_date: date | str | None = None) -> dict:
        target = _iso_date(business_date or date.today(), "date")
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT COUNT(*) AS planned,
                          COUNT(*) FILTER(WHERE status IN ('success','success_with_warnings','no_data','skipped')) AS completed,
                          COUNT(*) FILTER(WHERE status IN ('queued','running')) AS active,
                          COUNT(*) FILTER(WHERE status='needs_human') AS needs_human,
                          COUNT(*) FILTER(WHERE status='failed') AS failed
                   FROM ops.automation_run WHERE business_date=%s AND trigger_type <> 'test'""", (target,)
            )
            summary = dict(cursor.fetchone())
            cursor.execute(
                """SELECT r.*,COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,j.job_code
                   FROM ops.automation_run r
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   WHERE r.status IN ('queued','running') AND r.trigger_type <> 'test'
                   ORDER BY r.queued_at"""
            )
            current = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT r.automation_run_id,r.status,r.business_date,r.finished_at,r.error_message,r.warning_message,
                          COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name
                   FROM ops.automation_run r
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   WHERE r.trigger_type <> 'test'
                     AND r.attention_acknowledged_at IS NULL
                     AND (r.status IN ('failed','needs_human','success_with_warnings')
                          OR (r.status='running' AND COALESCE(r.attempt_started_at,r.started_at)<NOW()-INTERVAL '30 minutes'))
                   ORDER BY COALESCE(r.waiting_since,r.finished_at,r.started_at,r.queued_at) DESC
                   LIMIT 8"""
            )
            attention = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """WITH latest AS (
                       SELECT s.*,
                              ROW_NUMBER() OVER (
                                  PARTITION BY s.automation_run_id,COALESCE(s.profile_name,''),
                                               s.module_name,s.step_name
                                  ORDER BY s.sequence_no DESC
                              ) AS outcome_rank
                       FROM ops.automation_step_run s
                       JOIN ops.automation_run r ON r.automation_run_id=s.automation_run_id
                       WHERE r.business_date=%s AND r.trigger_type <> 'test'
                   )
                   SELECT s.*,r.status AS run_status,r.automation_run_id
                   FROM latest s
                   JOIN ops.automation_run r ON r.automation_run_id=s.automation_run_id
                   WHERE s.outcome_rank=1
                   ORDER BY s.platform_name,s.shop_name,s.sequence_no""",
                (target,),
            )
            steps = [dict(row) for row in cursor.fetchall()]
            for item in steps:
                item.pop("outcome_rank", None)
            cursor.execute("SELECT to_regclass('ai.verification_challenge') AS challenge_table")
            has_verification = bool(cursor.fetchone()["challenge_table"])
            challenge_join = (
                "LEFT JOIN ai.verification_challenge vc "
                "ON vc.challenge_uuid=COALESCE(c.verification_challenge_id,s.verification_challenge_id)"
                if has_verification else
                "LEFT JOIN LATERAL (SELECT NULL::varchar AS status,NULL::timestamptz AS expires_at) vc ON TRUE"
            )
            cursor.execute(
                f"""SELECT r.automation_run_id,r.status AS run_status,r.business_date,r.waiting_since,
                          r.error_message AS run_error,j.job_name,
                          s.step_run_id,s.platform_name,s.company_name,s.shop_name,
                          s.profile_name,s.step_name,s.error_message,
                          c.component_run_id,c.component_name,c.error_message AS component_error,
                          COALESCE(c.verification_challenge_id,s.verification_challenge_id) AS verification_challenge_id,
                          vc.status AS challenge_status,vc.expires_at AS challenge_expires_at
                   FROM ops.automation_run r
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN LATERAL (
                       SELECT * FROM ops.automation_step_run s
                       WHERE s.automation_run_id=r.automation_run_id
                       ORDER BY s.sequence_no DESC LIMIT 1
                   ) s ON TRUE
                   LEFT JOIN LATERAL (
                       SELECT c.* FROM ops.automation_component_run c
                       WHERE c.step_run_id=s.step_run_id
                         AND s.started_at>=COALESCE(r.resumed_at,r.created_at)
                         AND EXISTS (
                             SELECT 1 FROM ops.automation_component_event e
                             WHERE e.component_run_id=c.component_run_id
                               AND e.event_type='waiting_human'
                         )
                         AND NOT EXISTS (
                             SELECT 1 FROM ops.automation_component_event e
                             WHERE e.component_run_id=c.component_run_id
                               AND e.event_type='human_answered'
                         )
                       ORDER BY c.created_at DESC LIMIT 1
                   ) c ON TRUE
                   {challenge_join}
                   WHERE r.trigger_type <> 'test'
                     AND (r.status='needs_human'
                          OR (r.status='running' AND c.component_run_id IS NOT NULL))
                   ORDER BY COALESCE(r.waiting_since,s.started_at,r.queued_at) DESC
                   LIMIT 40"""
            )
            humans = [dict(row) for row in cursor.fetchall()]
            # Dashboard card covers active component-level waits as well as
            # whole Run pauses, but continues to display today's count.
            summary["needs_human"] = sum(
                1 for item in humans if item.get("business_date") == target
            )
        return {"date": target, "summary": summary, "current_runs": current,
                "attention": attention, "steps": steps, "human_tasks": humans}

    def daily_results(self, query: dict | None = None) -> dict:
        query = query or {}
        target = _iso_date(query.get("date") or date.today(), "date")
        with self.transaction() as cursor:
            cursor.execute(
                """WITH ranked_steps AS (
                       SELECT s.*,
                              ROW_NUMBER() OVER (
                                  PARTITION BY s.automation_run_id,
                                               COALESCE(s.platform_name,''),
                                               COALESCE(s.shop_name,''),
                                               COALESCE(s.profile_name,''),
                                               s.module_name,s.step_name
                                  ORDER BY s.sequence_no DESC
                              ) AS outcome_rank
                       FROM ops.automation_step_run s
                       JOIN ops.automation_run rr ON rr.automation_run_id=s.automation_run_id
                       WHERE rr.business_date=%s AND rr.trigger_type <> 'test'
                   )
                   SELECT s.*,r.status AS run_status,r.job_id,
                          COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                          COALESCE(fv.version,f.version) AS flow_version,
                          ir.status AS ingest_status,COALESCE(er.status,linked_etl.status) AS etl_status,
                          COALESCE(s.etl_run_id,r.etl_run_id,linked_etl.etl_run_id) AS current_etl_run_id
                   FROM ranked_steps s
                   JOIN ops.automation_run r ON r.automation_run_id=s.automation_run_id
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   LEFT JOIN ops.ingest_run ir ON ir.run_id=s.ingest_run_id
                   LEFT JOIN ops.etl_run er ON er.etl_run_id=COALESCE(s.etl_run_id,r.etl_run_id)
                   LEFT JOIN LATERAL (
                       SELECT e.etl_run_id,e.status FROM ops.etl_run e
                       WHERE e.ingest_run_id=s.ingest_run_id ORDER BY e.created_at DESC LIMIT 1
                   ) linked_etl ON TRUE
                   WHERE s.outcome_rank=1
                   ORDER BY COALESCE(s.platform_name,''),COALESCE(s.shop_name,''),s.sequence_no""",
                (target,),
            )
            items = [dict(row) for row in cursor.fetchall()]
            step_ids = [row["step_run_id"] for row in items]
            artifacts_by_step: dict[str, list[dict]] = {}
            if step_ids:
                cursor.execute(
                    """SELECT a.*,ft.status AS ingest_file_status,ft.batch_id AS current_batch_id
                       FROM ops.automation_artifact a
                       LEFT JOIN ops.ingest_file_task ft ON ft.file_task_id=a.ingest_file_task_id
                       WHERE a.step_run_id = ANY(%s::uuid[]) ORDER BY a.created_at""", (step_ids,)
                )
                for artifact in cursor.fetchall():
                    item = dict(artifact)
                    artifacts_by_step.setdefault(str(item["step_run_id"]), []).append(item)
            for item in items:
                item.pop("outcome_rank", None)
                item["artifacts"] = artifacts_by_step.get(str(item["step_run_id"]), [])
            summary = {
                "steps": len(items),
                "success_steps": sum(1 for item in items if item.get("status") in {"success", "success_with_warnings", "no_data", "skipped"}),
                "failed_steps": sum(1 for item in items if item.get("status") in {"failed", "needs_human"}),
                "artifacts": sum(len(item.get("artifacts") or []) for item in items),
                "ingest_success": sum(1 for item in items if item.get("ingest_status") in {"success", "no_change"}),
                "etl_success": sum(1 for item in items if item.get("etl_status") in {"success", "success_with_warnings", "no_change"}),
            }
        return {"date": target, "date_semantics": "business_date", "items": items, "total": len(items), "summary": summary}

    def fault_center(self, query: dict | None = None) -> dict:
        query = query or {}
        days = bounded_int(query.get("days"), default=7, maximum=90, label="days")
        status = str(query.get("status") or "").strip()
        if status and status not in {"failed", "needs_human", "success_with_warnings", "stalled"}:
            raise ValueError("故障状态筛选无效")
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT
                       COUNT(*) FILTER(WHERE r.status='failed')::int AS failed,
                       COUNT(*) FILTER(WHERE r.status='needs_human')::int AS needs_human,
                       COUNT(*) FILTER(WHERE r.status='success_with_warnings')::int AS warnings,
                       COUNT(*) FILTER(WHERE r.status='running' AND COALESCE(r.attempt_started_at,r.started_at)<NOW()-INTERVAL '30 minutes')::int AS stalled
                   FROM ops.automation_run r
                   WHERE r.trigger_type <> 'test'
                     AND r.created_at>=NOW()-(%s*INTERVAL '1 day')""",
                (days,),
            )
            summary = dict(cursor.fetchone())
            conditions = [
                "r.trigger_type <> 'test'",
                "r.created_at>=NOW()-(%s*INTERVAL '1 day')",
            ]
            params: list[Any] = [days]
            if status == "stalled":
                conditions.append("r.status='running' AND COALESCE(r.attempt_started_at,r.started_at)<NOW()-INTERVAL '30 minutes'")
            elif status:
                conditions.append("r.status=%s")
                params.append(status)
            else:
                conditions.append(
                    "(r.status IN ('failed','needs_human','success_with_warnings') "
                    "OR (r.status='running' AND COALESCE(r.attempt_started_at,r.started_at)<NOW()-INTERVAL '30 minutes'))"
                )
            where = " AND ".join(conditions)
            cursor.execute(
                f"""SELECT r.automation_run_id,r.status,r.business_date,r.execution_lane,r.created_at,
                           r.started_at,r.attempt_started_at,r.finished_at,r.waiting_since,r.resume_count,r.error_message,r.warning_message,
                           r.attention_acknowledged_at,r.attention_acknowledged_by,
                           COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                           COALESCE(fv.version,f.version) AS flow_version,
                           first_step.platform_name,first_step.company_name,first_step.shop_name,
                           failed_component.component_run_id,failed_component.component_code,
                           failed_component.component_name,failed_component.error_type,
                           failed_component.error_message AS component_error
                    FROM ops.automation_run r
                    JOIN ops.automation_job j ON j.job_id=r.job_id
                    LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                    LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                    LEFT JOIN LATERAL (
                        SELECT platform_name,company_name,shop_name
                        FROM ops.automation_step_run s
                        WHERE s.automation_run_id=r.automation_run_id
                        ORDER BY sequence_no DESC LIMIT 1
                    ) first_step ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT component_run_id,component_code,component_name,error_type,error_message
                        FROM ops.automation_component_run c
                        WHERE c.automation_run_id=r.automation_run_id
                          AND c.status IN ('failed','needs_human')
                        ORDER BY c.created_at DESC LIMIT 1
                    ) failed_component ON TRUE
                    WHERE {where}
                    ORDER BY COALESCE(r.waiting_since,r.finished_at,r.started_at,r.created_at) DESC
                    LIMIT 100""",
                params,
            )
            items = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT COALESCE(error_type,'UNKNOWN') AS error_type,COUNT(*)::int AS total
                   FROM ops.automation_component_run
                   WHERE status IN ('failed','needs_human')
                     AND created_at>=NOW()-(%s*INTERVAL '1 day')
                   GROUP BY COALESCE(error_type,'UNKNOWN')
                   ORDER BY total DESC,error_type LIMIT 8""",
                (days,),
            )
            top_errors = [dict(row) for row in cursor.fetchall()]
        return {"days": days, "status": status or None, "summary": summary, "items": items, "top_errors": top_errors}

    def runtime_resources(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT worker_id,worker_name,process_id,status,current_run_id,started_at,last_seen_at,stopped_at,
                          (last_seen_at>=NOW()-INTERVAL '15 seconds' AND status IN ('starting','idle','busy')) AS alive
                   FROM ops.automation_worker_heartbeat
                   ORDER BY alive DESC,last_seen_at DESC"""
            )
            workers = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT l.resource_key,l.automation_run_id,l.worker_id,l.lock_state,l.acquired_at,
                          COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                          r.status,r.business_date,r.started_at
                   FROM ops.automation_resource_lock l
                   JOIN ops.automation_run r ON r.automation_run_id=l.automation_run_id
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   ORDER BY l.acquired_at"""
            )
            locks = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT r.automation_run_id,r.queued_at,r.resource_key,r.business_date,
                          COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                          EXISTS(
                              SELECT 1 FROM ops.automation_resource_lock l
                              JOIN ops.automation_run holder ON holder.automation_run_id=l.automation_run_id
                              WHERE (l.resource_key=r.resource_key
                                     OR (holder.execution_lane <> 'etl' AND r.execution_lane <> 'etl'
                                         AND (r.resource_key='download:controller' OR l.resource_key='download:controller'
                                              OR r.resource_key LIKE 'job:platform_download%' OR l.resource_key LIKE 'job:platform_download%')))
                                AND NOT (l.automation_run_id=r.automation_run_id
                                         AND l.lock_state='paused')
                          ) AS blocked
                   FROM ops.automation_run r
                   JOIN ops.automation_job j ON j.job_id=r.job_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   WHERE r.status='queued'
                     AND COALESCE(r.input_context->>'execution_source','') <> 'external'
                   ORDER BY r.queued_at LIMIT 100"""
            )
            queue = [dict(row) for row in cursor.fetchall()]
        alive_workers = sum(1 for item in workers if item.get("alive"))
        busy_workers = sum(1 for item in workers if item.get("alive") and item.get("status") == "busy")
        blocked = sum(1 for item in queue if item.get("blocked"))
        return {
            "summary": {
                "alive_workers": alive_workers,
                "busy_workers": busy_workers,
                "known_workers": len(workers),
                "queued_runs": len(queue),
                "blocked_runs": blocked,
                "resource_locks": len(locks),
            },
            "workers": workers,
            "locks": locks,
            "queue": queue,
        }

    def notification_policy(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_notification_policy WHERE policy_code='default'")
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化通知策略不存在")
            result = dict(row)
            cursor.execute(
                """SELECT status,COUNT(*)::int AS total
                   FROM ops.automation_notification_outbox
                   GROUP BY status"""
            )
            result["outbox"] = {item["status"]: int(item["total"]) for item in cursor.fetchall()}
        return result

    def enqueue_stalled_notifications(self, minutes: int = 30, limit: int = 50) -> int:
        """把超过运行时长阈值仍在执行的 Run 写入通知 Outbox。

        事件键带 resume_count，同一 Run 的同一次尝试只会入队一次；策略关闭或未勾选
        “长时间运行”时不做任何写入。
        """

        with self.transaction() as cursor:
            cursor.execute("SELECT to_regclass('ops.automation_notification_outbox') AS relation")
            if not cursor.fetchone()["relation"]:
                return 0
            cursor.execute(
                """SELECT enabled,event_types FROM ops.automation_notification_policy
                   WHERE policy_code='default'"""
            )
            policy = cursor.fetchone()
            configured = {str(item) for item in ((policy or {}).get("event_types") or [])}
            if not policy or not policy["enabled"] or "stalled" not in configured:
                return 0
            cursor.execute(
                """INSERT INTO ops.automation_notification_outbox(
                       automation_run_id,event_key,event_type,payload,status,next_attempt_at)
                   SELECT r.automation_run_id,
                          'stalled:' || COALESCE(r.resume_count,0),
                          'stalled',
                          jsonb_build_object('business_date',r.business_date,
                                             'execution_lane',r.execution_lane,
                                             'resource_key',r.resource_key,
                                             'resume_count',COALESCE(r.resume_count,0)),
                          'pending',NOW()
                   FROM ops.automation_run r
                   WHERE r.trigger_type<>'test' AND r.status='running'
                     AND COALESCE(r.attempt_started_at,r.started_at)<NOW()-(%s*INTERVAL '1 minute')
                   ORDER BY r.automation_run_id
                   LIMIT %s
                   ON CONFLICT(automation_run_id,event_key) DO NOTHING""",
                (minutes, limit),
            )
            return int(cursor.rowcount)

    def update_notification_policy(self, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        allowed_events = {"failed", "needs_human", "success_with_warnings", "success", "no_data", "cancelled", "stalled"}
        events = payload.get("event_types")
        if isinstance(events, str):
            events = [part.strip() for part in events.split(",") if part.strip()]
        if not isinstance(events, list) or not events:
            raise ValueError("通知事件至少选择一个")
        normalized: list[str] = []
        for event in events:
            value = str(event).strip()
            if value not in allowed_events:
                raise ValueError(f"不支持的通知事件：{value}")
            if value not in normalized:
                normalized.append(value)
        enabled = bool(payload.get("enabled", False))
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_notification_policy
                   SET enabled=%s,event_types=%s,updated_by=%s,updated_at=NOW()
                   WHERE policy_code='default' RETURNING *""",
                (enabled, Json(normalized), operator[:100]),
            )
            result = dict(cursor.fetchone())
            cursor.execute(
                """UPDATE ops.automation_notification_outbox
                   SET status='failed',last_error='通知策略已变更，旧待发送事件已终止'
                   WHERE status='pending'
                     AND (NOT %s OR NOT (event_type=ANY(%s)))""",
                (enabled, normalized),
            )
            self._audit(
                cursor, "automation_notification_policy_update", "automation_notification_policy",
                "default", operator, "更新自动化飞书通知策略",
                {"enabled": enabled, "event_types": normalized},
                ip_address,
            )
        return result

    def health(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT to_regclass('ops.automation_job') IS NOT NULL AS database_ready,
                          COUNT(*) FILTER(WHERE status IN ('starting','idle','busy') AND last_seen_at>=NOW()-INTERVAL '15 seconds') AS active_worker_count,
                          MAX(last_seen_at) AS worker_last_seen_at
                   FROM ops.automation_worker_heartbeat"""
            )
            result = dict(cursor.fetchone())
            cursor.execute("SELECT COUNT(*) AS queued_runs FROM ops.automation_run WHERE status='queued'")
            result.update(dict(cursor.fetchone()))
        result["automation_worker_ready"] = int(result.get("active_worker_count") or 0) > 0
        result["file_ingest"] = self.file_ingest.health()
        result["cloak_login"] = self._cloak_health()
        return result

    @staticmethod
    def _cloak_health() -> dict:
        raw = os.getenv("CLOAK_MCP_URL", "http://127.0.0.1:19610/mcp")
        parsed = urlparse(raw)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return {"reachable": True}
        except OSError:
            return {"reachable": False}


    @staticmethod
    def _ensure_optional_downstream_nodes(definition: Any) -> Any:
        """Default new API upload and ETL nodes to enabled.

        System reference flows are fully wired by the SQL migration.  This
        normalizer covers user-created/API-created flows so authors never need
        to drag the two standard downstream nodes onto every new canvas.
        Existing nodes keep their enabled state and configuration.
        """
        if not isinstance(definition, dict):
            return definition
        raw_nodes = definition.get("nodes")
        raw_edges = definition.get("edges")
        if raw_nodes is not None and not isinstance(raw_nodes, list):
            return definition
        if raw_edges is not None and not isinstance(raw_edges, list):
            return definition

        nodes = [dict(item) if isinstance(item, dict) else item for item in (raw_nodes or [])]
        edges = [dict(item) if isinstance(item, dict) else item for item in (raw_edges or [])]
        existing_ids = {
            str(item.get("id") or "")
            for item in nodes
            if isinstance(item, dict) and item.get("id")
        }

        def unique_id(base: str) -> str:
            if base not in existing_ids:
                existing_ids.add(base)
                return base
            sequence = 2
            while f"{base}_{sequence}" in existing_ids:
                sequence += 1
            value = f"{base}_{sequence}"
            existing_ids.add(value)
            return value

        max_x = 0
        max_y = 120
        for item in nodes:
            if not isinstance(item, dict):
                continue
            try:
                max_x = max(max_x, int(item.get("x") or 0))
                max_y = max(max_y, int(item.get("y") or 0))
            except (TypeError, ValueError):
                continue

        by_code = {
            str(item.get("component_code") or item.get("code") or ""): item
            for item in nodes
            if isinstance(item, dict)
        }
        ingest = by_code.get("ingest.submit")
        if ingest is None:
            ingest = {
                "id": unique_id("downstream_ingest"),
                "component_code": "ingest.submit",
                "name": "API 上传 / FileIngest",
                "x": max_x + 280,
                "y": max_y,
                "enabled": True,
                "timeout_seconds": 1800,
                "retry_count": 0,
                "on_error": "stop",
                "condition": "",
                "config": {},
            }
            nodes.append(ingest)

        etl = by_code.get("etl.trigger")
        if etl is None:
            etl = {
                "id": unique_id("downstream_etl"),
                "component_code": "etl.trigger",
                "name": "触发受影响 ETL",
                "x": max_x + 560,
                "y": max_y,
                "enabled": True,
                "timeout_seconds": 3600,
                "retry_count": 0,
                "on_error": "stop",
                "condition": "",
                "config": {},
            }
            nodes.append(etl)

        ingest_id = str(ingest.get("id") or "")
        etl_id = str(etl.get("id") or "")
        # Connect newly added downstream nodes after every terminal archive.
        if ingest_id and not any(isinstance(edge, dict) and edge.get("target") == ingest_id for edge in edges):
            archives = [node for node in nodes if isinstance(node, dict) and node.get("component_code") == "report.archive"]
            stops = {node["id"] for node in nodes if isinstance(node, dict) and node.get("component_code") == "cloak.profile.stop"}
            for archive in archives:
                outgoing = [edge for edge in edges if isinstance(edge, dict) and edge.get("source") == archive["id"]]
                if any(edge.get("target") not in stops for edge in outgoing):
                    continue
                for edge in outgoing:
                    edge["source"] = etl_id
                edges.append({"source": archive["id"], "target": ingest_id, "source_port": "right", "target_port": "left", "label": ""})
        if ingest_id and etl_id and not any(
            isinstance(edge, dict)
            and str(edge.get("source") or "") == ingest_id
            and str(edge.get("target") or "") == etl_id
            for edge in edges
        ):
            edges.append(
                {
                    "source": ingest_id,
                    "target": etl_id,
                    "source_port": "right",
                    "target_port": "left",
                    "label": "",
                }
            )

        result = dict(definition)
        result["nodes"] = nodes
        result["edges"] = edges
        if "variables" not in result:
            result["variables"] = {}
        return result

    @staticmethod
    def _validate_flow_definition(definition: Any, *, allow_draft_custom: bool) -> dict:
        if not isinstance(definition, dict):
            raise ValueError("definition必须是JSON对象")
        nodes = definition.get("nodes") or []
        edges = definition.get("edges") or []
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("definition.nodes和definition.edges必须是数组")
        if len(nodes) > 200 or len(edges) > 400:
            raise ValueError("单个流程最多200个节点、400条连线")
        node_ids: set[str] = set()
        normalized_nodes: list[dict] = []
        forbidden = {"module", "script", "command", "shell", "python", "executable"}
        secret_keys = {"password", "passwd", "token", "secret", "authorization", "cookie", "verification_code"}

        def validate_safe_mapping(value: Any, *, reject_secrets: bool = False) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    lowered = str(key).strip().lower()
                    if lowered in forbidden:
                        raise ValueError("组件配置禁止出现脚本、命令、模块或可执行文件字段")
                    if reject_secrets and lowered in secret_keys:
                        raise ValueError("Flow定义禁止保存密码、验证码、Cookie、Token等秘密")
                    validate_safe_mapping(item, reject_secrets=reject_secrets)
            elif isinstance(value, list):
                for item in value:
                    validate_safe_mapping(item, reject_secrets=reject_secrets)

        for raw in nodes:
            if not isinstance(raw, dict):
                raise ValueError("流程节点必须是JSON对象")
            node_id = str(raw.get("id") or "").strip()
            code = str(raw.get("component_code") or raw.get("code") or "").strip()
            if not node_id or len(node_id) > 120 or node_id in node_ids:
                raise ValueError("流程节点ID不能为空、重复或过长")
            if code not in COMPONENT_REGISTRY:
                if not (allow_draft_custom and code.startswith("custom.")):
                    raise ValueError(f"组件未注册：{code}")
            elif not allow_draft_custom and not COMPONENT_REGISTRY[code].flow_executable:
                raise ValueError(f"组件尚未提供 Flow 执行 Handler：{code}")
            config = raw.get("config") or {}
            if not isinstance(config, dict):
                raise ValueError(f"节点 {node_id} config必须是JSON对象")
            validate_safe_mapping(config, reject_secrets=True)
            node_ids.add(node_id)
            normalized_nodes.append({
                "id": node_id,
                "component_code": code,
                "name": str(raw.get("name") or (COMPONENT_REGISTRY.get(code).name if code in COMPONENT_REGISTRY else code))[:160],
                "x": max(-5000, min(5000, int(raw.get("x") or 0))),
                "y": max(-5000, min(5000, int(raw.get("y") or 0))),
                "enabled": bool(raw.get("enabled", True)),
                "timeout_seconds": max(1, min(86400, int(raw.get("timeout_seconds") or (COMPONENT_REGISTRY.get(code).timeout_seconds if code in COMPONENT_REGISTRY else 60)))),
                "retry_count": max(0, min(5, int(raw.get("retry_count") or 0))),
                "on_error": str(raw.get("on_error") or "stop") if str(raw.get("on_error") or "stop") in {"stop", "continue", "needs_human"} else "stop",
                "condition": str(raw.get("condition") or "")[:1000],
                "config": config,
            })
        normalized_edges: list[dict] = []
        seen_edges: set[tuple[str, str]] = set()
        for raw in edges:
            if not isinstance(raw, dict):
                raise ValueError("流程连线必须是JSON对象")
            source, target = str(raw.get("source") or ""), str(raw.get("target") or "")
            if source not in node_ids or target not in node_ids or source == target:
                raise ValueError("流程连线引用了不存在节点或自连接")
            pair = (source, target)
            if pair in seen_edges:
                continue
            seen_edges.add(pair)
            valid_ports = {"top", "right", "bottom", "left"}
            source_port = str(raw.get("source_port") or "right").strip().lower()
            target_port = str(raw.get("target_port") or "left").strip().lower()
            if source_port not in valid_ports or target_port not in valid_ports:
                raise ValueError("流程连线端口仅支持 top/right/bottom/left")
            normalized_edges.append({
                "source": source,
                "target": target,
                "source_port": source_port,
                "target_port": target_port,
                "label": str(raw.get("label") or "")[:120],
            })
        enabled_ids = {item["id"] for item in normalized_nodes if item["enabled"]}
        indegree = {node_id: 0 for node_id in enabled_ids}
        adjacency = {node_id: [] for node_id in enabled_ids}
        for edge in normalized_edges:
            if edge["source"] in enabled_ids and edge["target"] in enabled_ids:
                adjacency[edge["source"]].append(edge["target"])
                indegree[edge["target"]] += 1
        queue = [node_id for node_id, count in indegree.items() if count == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for target in adjacency[current]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        if visited != len(enabled_ids):
            raise ValueError("流程存在循环依赖，当前 FlowRunner 仅支持有向无环图")
        variables = definition.get("variables") if isinstance(definition.get("variables"), dict) else {}
        validate_safe_mapping(variables, reject_secrets=True)
        return {"nodes": normalized_nodes, "edges": normalized_edges, "variables": variables}

    def list_components(self) -> dict:
        items = component_registry_payload()
        return {"items": items, "total": len(items)}

    def component_repair_context(self, component_run_id: str) -> dict:
        source_hints = {
            "human.verification.wait": "scripts/auto_download/playwright/automation_challenge.py",
            "pinduoduo.ensure_login": "scripts/auto_download/playwright/pinduoduo_login.py",
            "cloak.profile.start": "apps/automation_center/flow_runner.py",
            "cloak.profile.stop": "apps/automation_center/flow_runner.py",
            "browser.connect.cdp": "apps/automation_center/flow_runner.py",
        }
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT c.*,s.step_name,s.module_name,s.platform_name,s.company_name,s.shop_name,s.profile_name,
                          r.business_date,r.flow_id,
                          COALESCE(fv.flow_code,f.flow_code) AS flow_code,
                          COALESCE(fv.flow_name,f.flow_name) AS flow_name,
                          COALESCE(fv.version,f.version) AS flow_version
                   FROM ops.automation_component_run c
                   JOIN ops.automation_step_run s ON s.step_run_id=c.step_run_id
                   JOIN ops.automation_run r ON r.automation_run_id=c.automation_run_id
                   LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                   LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                   WHERE c.component_run_id=%s""",
                (component_run_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("原子组件运行不存在")
            item = dict(row)
            cursor.execute(
                """SELECT event_type,message,detail,created_at
                   FROM ops.automation_component_event
                   WHERE component_run_id=%s ORDER BY component_event_id DESC LIMIT 30""",
                (component_run_id,),
            )
            events = [dict(event) for event in reversed(cursor.fetchall())]
        module_name = str(item.get("module_name") or "")
        if item["component_code"] in source_hints:
            source_hint = source_hints[item["component_code"]]
        elif module_name and not module_name.startswith("flow:"):
            source_hint = f"scripts/auto_download/playwright/{module_name}.py"
        elif str(item["component_code"]).startswith("jd.") or item["component_code"] in {
            "report.date_range.set", "report.wait_export_ready", "file.download",
            "file.archive.extract", "report.validate.schema",
        }:
            source_hint = "scripts/auto_download/playwright/jd_order_download.py"
        else:
            source_hint = "apps/automation_center/flow_runner.py"
        prompt = (
            f"仅修复 mock_coffice 自动化原子组件 {item['component_code']}，"
            f"不要扩大修改范围到无关 Flow 或平台脚本。错误类型：{item.get('error_type') or 'UNKNOWN'}。"
            f"优先检查 {source_hint}，结合 page_url、失败截图和组件事件定位问题；"
            "保持 Component Registry/输入输出契约兼容，并补充或更新对应测试。"
        )
        return {
            "repair_scope": "component_only",
            "component_run_id": str(item["component_run_id"]),
            "component_code": item["component_code"],
            "component_name": item["component_name"],
            "component_version": item["component_version"],
            "status": item["status"],
            "error_type": item.get("error_type"),
            "error_message": item.get("error_message"),
            "page_url": item.get("page_url"),
            "screenshot_path": item.get("screenshot_path"),
            "trace_path": item.get("trace_path"),
            "source_hint": source_hint,
            "flow": {
                "flow_id": str(item["flow_id"]) if item.get("flow_id") else None,
                "flow_code": item.get("flow_code"),
                "flow_name": item.get("flow_name"),
                "version": item.get("flow_version"),
            },
            "business": {
                "business_date": item.get("business_date"),
                "platform": item.get("platform_name"),
                "company": item.get("company_name"),
                "shop": item.get("shop_name"),
                "profile_name": item.get("profile_name"),
                "step_name": item.get("step_name"),
            },
            "events": events,
            "repair_prompt": prompt,
        }

    def list_flows(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute("""SELECT flow_id,flow_code,flow_name,description,status,enabled,version,execution_lane,
                                     schedule_type,schedule_config,timezone,retry_policy,timeout_seconds,default_profile_name,
                                     created_by,updated_by,created_at,updated_at,
                                     jsonb_array_length(COALESCE(definition->'nodes','[]'::jsonb)) AS node_count
                              FROM ops.automation_flow WHERE deleted_at IS NULL ORDER BY updated_at DESC""")
            items = [dict(row) for row in cursor.fetchall()]
        return {"items": items, "total": len(items)}

    def get_flow(self, flow_id: str) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s AND deleted_at IS NULL", (flow_id,))
            row = cursor.fetchone()
        if not row:
            raise AutomationNotFoundError("自动化流程不存在")
        return dict(row)

    def get_flow_version(self, flow_version_id: str) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT v.*,f.description,f.enabled,f.status AS current_flow_status,
                          f.default_profile_name,'published'::varchar AS status
                   FROM ops.automation_flow_version v
                   JOIN ops.automation_flow f ON f.flow_id=v.flow_id
                   WHERE v.flow_version_id=%s""",
                (flow_version_id,),
            )
            row = cursor.fetchone()
        if not row:
            raise AutomationNotFoundError("Flow发布版本不存在")
        return dict(row)

    @staticmethod
    def _flow_definition_diff(left: dict | None, right: dict | None) -> dict:
        left = left or {}
        right = right or {}
        left_nodes = {str(item.get("id")): item for item in (left.get("nodes") or []) if isinstance(item, dict)}
        right_nodes = {str(item.get("id")): item for item in (right.get("nodes") or []) if isinstance(item, dict)}
        left_edges = {
            (str(item.get("source")), str(item.get("target")), str(item.get("source_port") or ""), str(item.get("target_port") or ""))
            for item in (left.get("edges") or []) if isinstance(item, dict)
        }
        right_edges = {
            (str(item.get("source")), str(item.get("target")), str(item.get("source_port") or ""), str(item.get("target_port") or ""))
            for item in (right.get("edges") or []) if isinstance(item, dict)
        }
        shared = set(left_nodes) & set(right_nodes)
        changed = sum(
            1 for node_id in shared
            if json.dumps(left_nodes[node_id], ensure_ascii=False, sort_keys=True)
            != json.dumps(right_nodes[node_id], ensure_ascii=False, sort_keys=True)
        )
        return {
            "nodes_added": len(set(right_nodes) - set(left_nodes)),
            "nodes_removed": len(set(left_nodes) - set(right_nodes)),
            "nodes_changed": changed,
            "edges_added": len(right_edges - left_edges),
            "edges_removed": len(left_edges - right_edges),
        }

    def list_flow_versions(self, flow_id: str) -> dict:
        flow = self.get_flow(flow_id)
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT flow_version_id,flow_id,version,flow_code,flow_name,execution_lane,definition,
                          published_by,published_at
                   FROM ops.automation_flow_version
                   WHERE flow_id=%s ORDER BY version DESC""",
                (flow_id,),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        current_definition = dict(flow.get("definition") or {})
        items = []
        for row in rows:
            definition = dict(row.pop("definition") or {})
            row["node_count"] = len(definition.get("nodes") or [])
            row["edge_count"] = len(definition.get("edges") or [])
            row["is_current"] = int(row["version"]) == int(flow["version"]) and flow["status"] == "published"
            row["diff_from_current"] = self._flow_definition_diff(definition, current_definition)
            items.append(row)
        return {
            "flow_id": str(flow["flow_id"]),
            "flow_name": flow["flow_name"],
            "current_version": flow["version"],
            "current_status": flow["status"],
            "items": items,
            "total": len(items),
        }

    def rollback_flow_version(self, flow_id: str, version: int, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s AND deleted_at IS NULL FOR UPDATE", (flow_id,))
            flow = cursor.fetchone()
            if not flow:
                raise AutomationNotFoundError("自动化流程不存在")
            cursor.execute(
                """SELECT * FROM ops.automation_flow_version
                   WHERE flow_id=%s AND version=%s""",
                (flow_id, int(version)),
            )
            source = cursor.fetchone()
            if not source:
                raise AutomationNotFoundError("Flow发布版本不存在")
            definition = self._validate_flow_definition(dict(source["definition"] or {}), allow_draft_custom=False)
            if (
                flow.get("schedule_type") == "daily"
                and source["execution_lane"] != "etl"
                and not str(flow.get("default_profile_name") or "").strip()
            ):
                raise ValueError("该历史版本需要浏览器 Profile；请先配置默认 Cloak Profile，或把调度改为仅手工")
            new_version = int(flow["version"]) + 1
            cursor.execute(
                """UPDATE ops.automation_flow
                   SET definition=%s,execution_lane=%s,status='published',version=%s,
                       updated_by=%s,updated_at=NOW()
                   WHERE flow_id=%s RETURNING *""",
                (Json(definition), source["execution_lane"], new_version, operator[:100], flow_id),
            )
            result = dict(cursor.fetchone())
            cursor.execute(
                """INSERT INTO ops.automation_flow_version(
                       flow_id,version,flow_code,flow_name,execution_lane,definition,published_by,published_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,NOW()) RETURNING flow_version_id""",
                (flow_id, new_version, result["flow_code"], result["flow_name"],
                 result["execution_lane"], Json(definition), operator[:100]),
            )
            version_row = cursor.fetchone()
            result["flow_version_id"] = str(version_row["flow_version_id"])
            result["rolled_back_from_version"] = int(version)
            self._audit(
                cursor, "automation_flow_rollback", "automation_flow", flow_id, operator,
                "回滚 Flow 发布版本并生成新版本",
                {"source_version": int(version), "new_version": new_version, "flow_version_id": result["flow_version_id"]},
                ip_address,
            )
        return result

    def create_flow(self, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        name = str(payload.get("flow_name") or payload.get("name") or "").strip()
        if not name:
            raise ValueError("flow_name不能为空")
        code = str(payload.get("flow_code") or "").strip().lower()
        if not code:
            code = "flow_" + uuid.uuid4().hex[:12]
        if not __import__("re").fullmatch(r"[a-z][a-z0-9_.-]{2,119}", code):
            raise ValueError("flow_code格式无效")
        lane = str(payload.get("execution_lane") or "interactive")
        if lane not in {"overnight", "interactive", "etl"}:
            raise ValueError("execution_lane无效")
        raw_definition = self._ensure_optional_downstream_nodes(
            payload.get("definition") or {"nodes": [], "edges": [], "variables": {}}
        )
        definition = self._validate_flow_definition(raw_definition, allow_draft_custom=True)
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO ops.automation_flow(flow_code,flow_name,description,status,version,execution_lane,definition,created_by,updated_by)
                   VALUES(%s,%s,%s,'draft',1,%s,%s,%s,%s) RETURNING *""",
                (code, name[:160], str(payload.get("description") or "")[:4000] or None, lane, Json(definition), operator[:100], operator[:100]),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_flow_create", "automation_flow", str(result["flow_id"]), operator, "创建自动化流程", {"flow_code": code}, ip_address)
        return result

    def update_flow(self, flow_id: str, payload: dict, operator: str, ip_address: str | None = None) -> dict:
        allowed = {
            "flow_name", "description", "execution_lane", "definition",
            "schedule_type", "schedule_config", "timezone", "retry_policy",
            "timeout_seconds", "default_profile_name",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"不允许修改字段：{', '.join(sorted(unknown))}")
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s FOR UPDATE", (flow_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化流程不存在")
            before = dict(row)
            name = str(payload.get("flow_name", before["flow_name"])).strip()
            if not name:
                raise ValueError("flow_name不能为空")
            lane = str(payload.get("execution_lane", before["execution_lane"]))
            if lane not in {"overnight", "interactive", "etl"}:
                raise ValueError("execution_lane无效")
            schedule_type = str(payload.get("schedule_type", before.get("schedule_type") or "manual")).strip()
            schedule_config = self._validate_schedule(
                schedule_type, payload.get("schedule_config", before.get("schedule_config") or {})
            )
            timezone_name = self._validate_timezone(payload.get("timezone", before.get("timezone") or "Asia/Shanghai"))
            retry_policy = payload.get("retry_policy", before.get("retry_policy") or {"max_attempts": 1})
            if not isinstance(retry_policy, dict):
                raise ValueError("retry_policy必须是JSON对象")
            max_attempts = int(retry_policy.get("max_attempts", 1))
            if max_attempts < 1 or max_attempts > 5:
                raise ValueError("max_attempts必须在1到5之间")
            timeout_seconds = int(payload.get("timeout_seconds", before.get("timeout_seconds") or 21600))
            if timeout_seconds < 60 or timeout_seconds > 86400:
                raise ValueError("timeout_seconds必须在60到86400之间")
            profile_name = str(payload.get("default_profile_name", before.get("default_profile_name") or "")).strip() or None
            if profile_name and len(profile_name) > 200:
                raise ValueError("default_profile_name过长")
            if schedule_type == "daily" and not profile_name and lane != "etl":
                raise ValueError("Flow启用每日调度前必须配置默认 Cloak Profile")
            raw_definition = self._ensure_optional_downstream_nodes(
                payload.get("definition", before["definition"])
            )
            definition = self._validate_flow_definition(raw_definition, allow_draft_custom=True)
            definition_changed = "definition" in payload or (
                "execution_lane" in payload and lane != before["execution_lane"]
            )
            next_status = "draft" if definition_changed else before["status"]
            cursor.execute(
                """UPDATE ops.automation_flow SET flow_name=%s,description=%s,execution_lane=%s,definition=%s,
                          schedule_type=%s,schedule_config=%s,timezone=%s,retry_policy=%s,timeout_seconds=%s,
                          default_profile_name=%s,status=%s,updated_by=%s,updated_at=NOW()
                   WHERE flow_id=%s RETURNING *""",
                (name[:160], str(payload.get("description", before.get("description") or ""))[:4000] or None,
                 lane, Json(definition), schedule_type, Json(schedule_config), timezone_name,
                 Json({"max_attempts": max_attempts}), timeout_seconds, profile_name, next_status,
                 operator[:100], flow_id),
            )
            result = dict(cursor.fetchone())
            self._audit(cursor, "automation_flow_update", "automation_flow", flow_id, operator, "更新自动化流程", {
                "flow_code": result["flow_code"], "schedule_type": schedule_type,
                "definition_changed": definition_changed,
            }, ip_address)
        return result

    def publish_flow(self, flow_id: str, operator: str, ip_address: str | None = None) -> dict:
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM ops.automation_flow WHERE flow_id=%s FOR UPDATE", (flow_id,))
            row = cursor.fetchone()
            if not row:
                raise AutomationNotFoundError("自动化流程不存在")
            raw_definition = self._ensure_optional_downstream_nodes(row["definition"])
            definition = self._validate_flow_definition(raw_definition, allow_draft_custom=False)
            if not definition["nodes"]:
                raise ValueError("空流程不能发布")
            cursor.execute(
                """UPDATE ops.automation_flow SET definition=%s,status='published',
                          version=CASE WHEN status='published' THEN version ELSE version+1 END,
                          updated_by=%s,updated_at=NOW() WHERE flow_id=%s RETURNING *""",
                (Json(definition), operator[:100], flow_id),
            )
            result = dict(cursor.fetchone())
            cursor.execute(
                """INSERT INTO ops.automation_flow_version(
                       flow_id,version,flow_code,flow_name,execution_lane,definition,published_by,published_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT(flow_id,version) DO NOTHING
                   RETURNING flow_version_id""",
                (flow_id, result["version"], result["flow_code"], result["flow_name"],
                 result["execution_lane"], Json(definition), operator[:100]),
            )
            version_row = cursor.fetchone()
            if version_row:
                result["flow_version_id"] = str(version_row["flow_version_id"])
            else:
                cursor.execute(
                    "SELECT flow_version_id FROM ops.automation_flow_version WHERE flow_id=%s AND version=%s",
                    (flow_id, result["version"]),
                )
                existing = cursor.fetchone()
                result["flow_version_id"] = str(existing["flow_version_id"]) if existing else None
            self._audit(cursor, "automation_flow_publish", "automation_flow", flow_id, operator, "发布自动化流程", {
                "version": result["version"], "flow_version_id": result.get("flow_version_id")
            }, ip_address)
        return result

    def flow_successful_node_checkpoints(self, run_id: str) -> dict[str, dict]:
        """Return completed top-level nodes from this Run only, never another Run or Flow."""
        with self.transaction() as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (c.input_snapshot->>'node_id')
                          c.input_snapshot->>'node_id' AS node_id,
                          c.component_code,c.output_snapshot
                   FROM ops.automation_component_run c
                   WHERE c.automation_run_id=%s
                     AND c.parent_component_run_id IS NULL
                     AND c.status='success'
                     AND c.input_snapshot ? 'node_id'
                     AND c.output_snapshot ? 'runtime'
                   ORDER BY c.input_snapshot->>'node_id',c.created_at DESC""",
                (run_id,),
            )
            return {str(row["node_id"]): dict(row) for row in cursor.fetchall()}

    def start_component(self, step_id: str, payload: dict) -> str:
        component = payload.get("component") or payload
        run_key = str(component.get("component_run_key") or "")
        try:
            uuid.UUID(run_key)
        except (ValueError, TypeError) as exc:
            raise ValueError("component_run_key无效") from exc
        code = str(component.get("component_code") or "")
        spec = COMPONENT_REGISTRY.get(code)
        name = str(component.get("component_name") or (spec.name if spec else code) or "原子组件")[:160]
        category = str(component.get("category") or (spec.category if spec else "business"))[:32]
        with self.transaction() as cursor:
            cursor.execute("SELECT automation_run_id FROM ops.automation_step_run WHERE step_run_id=%s", (step_id,))
            step = cursor.fetchone()
            if not step:
                raise AutomationNotFoundError("Automation step不存在")
            cursor.execute("SELECT COALESCE(MAX(sequence_no),0)+1 AS sequence_no FROM ops.automation_component_run WHERE step_run_id=%s", (step_id,))
            sequence = int(cursor.fetchone()["sequence_no"])
            component_id = uuid.uuid4()
            parent_component_id = None
            parent_run_key = str(component.get("parent_component_run_key") or "").strip()
            if parent_run_key:
                try:
                    uuid.UUID(parent_run_key)
                except ValueError:
                    parent_run_key = ""
                if parent_run_key:
                    cursor.execute(
                        """SELECT component_run_id FROM ops.automation_component_run
                           WHERE step_run_id=%s AND component_run_key=%s""",
                        (step_id, parent_run_key),
                    )
                    parent_row = cursor.fetchone()
                    if parent_row:
                        parent_component_id = str(parent_row["component_run_id"])
            cursor.execute(
                """INSERT INTO ops.automation_component_run(
                       component_run_id,parent_component_run_id,automation_run_id,step_run_id,sequence_no,component_run_key,component_code,
                       component_version,component_name,category,status,attempt_no,input_snapshot,page_url,started_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,NOW())
                   ON CONFLICT(step_run_id,component_run_key) DO UPDATE SET updated_at=NOW()
                   RETURNING component_run_id""",
                (str(component_id), parent_component_id, str(step["automation_run_id"]), step_id, sequence, run_key, code[:120],
                 str(component.get("component_version") or "1.0.0")[:32], name, category,
                 max(1, min(6, int(component.get("attempt_no") or 1))),
                 Json(component.get("input_snapshot") if isinstance(component.get("input_snapshot"), dict) else {}),
                 str(component.get("page_url") or "")[:2000] or None),
            )
            return str(cursor.fetchone()["component_run_id"])

    def add_component_event(self, component_id: str, payload: dict) -> None:
        component = payload.get("component") or payload
        detail = component.get("detail") if isinstance(component.get("detail"), dict) else {}
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO ops.automation_component_event(component_run_id,event_type,message,detail)
                   VALUES(%s,%s,%s,%s)""",
                (component_id, str(component.get("action") or component.get("event") or "observation")[:80],
                 redact(component.get("message"))[:4000] if component.get("message") else None, Json(detail)),
            )
            if str(component.get("action")) == "waiting_human":
                challenge_id = str(detail.get("challenge_id") or "")
                if challenge_id:
                    try:
                        uuid.UUID(challenge_id)
                    except ValueError:
                        challenge_id = ""
                cursor.execute(
                    """UPDATE ops.automation_component_run SET status='needs_human',
                              verification_challenge_id=COALESCE(%s,verification_challenge_id),updated_at=NOW()
                       WHERE component_run_id=%s""",
                    (challenge_id or None, component_id),
                )

    def finish_component(self, component_id: str, status: str, payload: dict) -> dict:
        if status not in {"success", "failed", "needs_human", "cancelled", "skipped"}:
            raise ValueError("component终态无效")
        component = payload.get("component") or payload
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_component_run SET status=%s,finished_at=NOW(),duration_seconds=%s,
                          error_type=%s,error_message=%s,page_url=COALESCE(%s,page_url),
                          screenshot_path=COALESCE(%s,screenshot_path),trace_path=COALESCE(%s,trace_path),
                          output_snapshot=%s,updated_at=NOW()
                   WHERE component_run_id=%s RETURNING *""",
                (status, component.get("duration_seconds"), str(component.get("error_type") or "")[:100] or None,
                 redact(component.get("error_message"))[:OUTPUT_LIMIT] if component.get("error_message") else None,
                 str(component.get("page_url") or "")[:2000] or None,
                 str(component.get("screenshot_path") or "")[:4000] or None,
                 str(component.get("trace_path") or "")[:4000] or None,
                 Json(component.get("output_snapshot") if isinstance(component.get("output_snapshot"), dict) else {}),
                 component_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}

    def fail_open_components(self, step_id: str, error_message: str | None = None,
                             *, human_wait: bool = False) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_component_run
                   SET status=CASE WHEN %s AND status='needs_human' THEN 'needs_human' ELSE 'failed' END,
                       finished_at=NOW(),error_type=COALESCE(error_type,'STEP_ABORTED'),
                       error_message=COALESCE(error_message,%s),updated_at=NOW()
                   WHERE step_run_id=%s AND status IN ('running','needs_human')""",
                (human_wait, redact(error_message)[:OUTPUT_LIMIT] if error_message else "父步骤异常终止", step_id),
            )

    def due_jobs(self, now_utc: datetime | None = None) -> list[dict]:
        now_utc = now_utc or datetime.now(timezone.utc)
        due: list[dict] = []
        for job in self.list_jobs(include_internal=False)["items"]:
            if not job["enabled"] or job["schedule_type"] != "daily":
                continue
            zone = ZoneInfo(job["timezone"])
            local_now = now_utc.astimezone(zone)
            for value in (job["schedule_config"] or {}).get("times", []):
                hour, minute = (int(part) for part in value.split(":"))
                scheduled = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if scheduled <= local_now:
                    due.append({
                        **job, "local_date": local_now.date(), "scheduled_time": value,
                        "schedule_key": f"{job['task_key']}:{local_now.date().isoformat()}:{value}",
                    })
        return due

    def claim_run(self, worker_id: str) -> dict | None:
        with self.transaction() as cursor:
            # Serialize eligibility and lock acquisition across Workers, including
            # controller runs whose resource key differs from a Flow's Profile.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('automation:claim-run'))")
            cursor.execute(
                """SELECT r.automation_run_id,r.resource_key
                   FROM ops.automation_run r
                   WHERE r.status='queued'
                     AND COALESCE(r.input_context->>'execution_source','') <> 'external'
                     AND NOT EXISTS (
                         SELECT 1 FROM ops.automation_resource_lock l
                         JOIN ops.automation_run holder ON holder.automation_run_id=l.automation_run_id
                         WHERE l.automation_run_id <> r.automation_run_id
                           AND holder.execution_lane <> 'etl' AND r.execution_lane <> 'etl'
                           AND (r.resource_key='download:controller' OR l.resource_key='download:controller'
                                OR r.resource_key LIKE 'job:platform_download%' OR l.resource_key LIKE 'job:platform_download%')
                     )
                     AND (r.resource_key IS NULL OR NOT EXISTS (
                         SELECT 1 FROM ops.automation_resource_lock l
                         WHERE l.resource_key=r.resource_key
                           AND NOT (l.automation_run_id=r.automation_run_id AND l.lock_state='paused')
                     ))
                   ORDER BY r.queued_at
                   FOR UPDATE SKIP LOCKED LIMIT 1"""
            )
            row = cursor.fetchone()
            if not row:
                return None
            resource_key = row.get("resource_key")
            if resource_key:
                cursor.execute(
                    """INSERT INTO ops.automation_resource_lock(
                           resource_key,automation_run_id,worker_id,lock_state)
                       VALUES(%s,%s,%s,'running')
                       ON CONFLICT(resource_key) DO UPDATE SET
                           worker_id=EXCLUDED.worker_id,lock_state='running',acquired_at=NOW()
                       WHERE ops.automation_resource_lock.automation_run_id=EXCLUDED.automation_run_id
                         AND ops.automation_resource_lock.lock_state='paused'
                       RETURNING resource_key""",
                    (resource_key, row["automation_run_id"], worker_id),
                )
                if not cursor.fetchone():
                    return None
            cursor.execute(
                """UPDATE ops.automation_run SET status='running',worker_id=%s,attempt_count=attempt_count+1,
                          started_at=COALESCE(started_at,NOW()),attempt_started_at=NOW(),heartbeat_at=NOW(),updated_at=NOW()
                   WHERE automation_run_id=%s
                   RETURNING *""", (worker_id, row["automation_run_id"])
            )
            claimed = dict(cursor.fetchone())
            cursor.execute("SELECT * FROM ops.automation_job WHERE job_id=%s", (claimed["job_id"],))
            claimed["job"] = dict(cursor.fetchone())
            return claimed

    def heartbeat_run(self, run_id: str, worker_id: str) -> bool:
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_run SET heartbeat_at=NOW(),updated_at=NOW()
                   WHERE automation_run_id=%s AND worker_id=%s AND status='running'
                   RETURNING cancel_requested_at""", (run_id, worker_id)
            )
            row = cursor.fetchone()
            return bool(row and row["cancel_requested_at"])

    def finish_run(self, run_id: str, status: str, *, summary: dict | None = None,
                   error: str | None = None, warning: str | None = None,
                   ingest_run_id: str | None = None, etl_run_id: str | None = None) -> dict:
        if status not in TERMINAL_STATUSES:
            raise ValueError("Automation run状态无效")
        with self.transaction() as cursor:
            if status == "needs_human":
                cursor.execute(
                    """UPDATE ops.automation_run
                       SET status=%s,result_summary=%s,error_message=%s,warning_message=%s,
                           ingest_run_id=COALESCE(%s,ingest_run_id),etl_run_id=COALESCE(%s,etl_run_id),
                           finished_at=NULL,waiting_since=COALESCE(waiting_since,NOW()),
                           worker_id=NULL,heartbeat_at=NULL,updated_at=NOW()
                       WHERE automation_run_id=%s RETURNING *""",
                    (status, Json(summary or {}), redact(error)[:OUTPUT_LIMIT] if error else None,
                     redact(warning)[:OUTPUT_LIMIT] if warning else None, ingest_run_id, etl_run_id, run_id),
                )
            else:
                cursor.execute(
                    """UPDATE ops.automation_run
                       SET status=%s,result_summary=%s,error_message=%s,warning_message=%s,
                           ingest_run_id=COALESCE(%s,ingest_run_id),etl_run_id=COALESCE(%s,etl_run_id),
                           finished_at=NOW(),waiting_since=NULL,heartbeat_at=NOW(),updated_at=NOW()
                       WHERE automation_run_id=%s RETURNING *""",
                    (status, Json(summary or {}), redact(error)[:OUTPUT_LIMIT] if error else None,
                     redact(warning)[:OUTPUT_LIMIT] if warning else None, ingest_run_id, etl_run_id, run_id),
                )
            result = dict(cursor.fetchone())
            # Pausing frees the Worker, NOT the browser reservation. Otherwise
            # the next scheduled task can reuse the same Profile and destroy
            # the preserved verification/error scene before a human returns.
            if status in {"needs_human", "failed"} and result["execution_lane"] in {"interactive", "overnight"}:
                cursor.execute(
                    """UPDATE ops.automation_resource_lock SET lock_state='paused'
                       WHERE automation_run_id=%s""", (run_id,),
                )
            else:
                cursor.execute(
                    "DELETE FROM ops.automation_resource_lock WHERE automation_run_id=%s", (run_id,),
                )
            if status in {"success", "no_data", "success_with_warnings", "skipped"} and result.get("parent_run_id"):
                cursor.execute(
                    """WITH RECURSIVE predecessors AS (
                           SELECT automation_run_id,parent_run_id FROM ops.automation_run
                           WHERE automation_run_id=%s
                           UNION ALL
                           SELECT parent.automation_run_id,parent.parent_run_id
                           FROM ops.automation_run parent
                           JOIN predecessors p ON p.parent_run_id=parent.automation_run_id
                       )
                       UPDATE ops.automation_run r
                       SET attention_acknowledged_at=COALESCE(r.attention_acknowledged_at,NOW()),
                           attention_acknowledged_by=COALESCE(r.attention_acknowledged_by,'automation_recovery'),
                           attention_acknowledged_reason=COALESCE(r.attention_acknowledged_reason,'后续 Retry Run 已完成'),
                           updated_at=NOW()
                       WHERE r.automation_run_id IN (SELECT automation_run_id FROM predecessors)
                         AND r.status IN ('failed','success_with_warnings')""",
                    (str(result["parent_run_id"]),),
                )
            self._enqueue_notification_cursor(cursor, result)
            return result

    def start_step(self, run_id: str, payload: dict) -> str:
        period = payload.get("business_period") or {}
        with self.transaction() as cursor:
            cursor.execute("SELECT COALESCE(MAX(sequence_no),0)+1 AS sequence_no FROM ops.automation_step_run WHERE automation_run_id=%s", (run_id,))
            sequence = int(cursor.fetchone()["sequence_no"])
            metadata = payload.get("metadata") or {}
            dim = self._resolve_dim(cursor, metadata)
            step_id = uuid.uuid4()
            cursor.execute(
                """INSERT INTO ops.automation_step_run(
                       step_run_id,automation_run_id,sequence_no,platform_code,platform_name,company_code,company_name,
                       shop_code,shop_name,profile_name,step_name,module_name,execution_lane,status,
                       business_date_start,business_date_end,period_type,attempt_count,started_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'running',%s,%s,%s,1,NOW())""",
                (str(step_id), run_id, sequence, dim.get("platform_code"), metadata.get("platform"), dim.get("company_code"), metadata.get("company"),
                 dim.get("shop_code"), metadata.get("shop"), payload.get("profile_name"), payload.get("step_name") or "步骤",
                 payload.get("module_name") or "unknown", payload.get("execution_lane") or "interactive",
                 period.get("business_date_start"), period.get("business_date_end"), period.get("period_type") or "unknown"),
            )
            return str(step_id)

    @staticmethod
    def _resolve_dim(cursor, metadata: dict) -> dict:
        """DIM 解析委托给 dim_matching：编码优先、名称归一化（全/半角等价）、公司名软校验。"""

        return resolve_dim(load_dim_rows(cursor), metadata)

    def finish_step(self, step_id: str, status: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        if status not in TERMINAL_STATUSES:
            raise ValueError("Automation step终态无效")
        with self.transaction() as cursor:
            challenge_id = self._pending_challenge(cursor, step_id) if status == "needs_human" else None
            cursor.execute(
                """UPDATE ops.automation_step_run SET status=%s,finished_at=NOW(),duration_seconds=%s,exit_code=%s,
                          output_summary=%s,error_message=%s,verification_challenge_id=%s,
                          business_date_start=COALESCE(%s,business_date_start),business_date_end=COALESCE(%s,business_date_end),
                          period_type=COALESCE(%s,period_type),updated_at=NOW()
                   WHERE step_run_id=%s RETURNING *""",
                (status, payload.get("duration_seconds"), payload.get("exit_code"),
                 redact(payload.get("output_summary"))[:OUTPUT_LIMIT] if payload.get("output_summary") else None,
                 redact(payload.get("error_message"))[:OUTPUT_LIMIT] if payload.get("error_message") else None,
                 challenge_id, payload.get("business_date_start"), payload.get("business_date_end"),
                 payload.get("period_type"), step_id),
            )
            return dict(cursor.fetchone())

    @staticmethod
    def _pending_challenge(cursor, step_id: str) -> str | None:
        # Prefer the exact component->Challenge relation. Matching only by
        # shop/time can accidentally bind a parallel run's verification code.
        cursor.execute(
            """SELECT c.verification_challenge_id
               FROM ops.automation_component_run c
               WHERE c.step_run_id=%s AND c.verification_challenge_id IS NOT NULL
                 AND EXISTS (
                     SELECT 1 FROM ops.automation_component_event e
                     WHERE e.component_run_id=c.component_run_id AND e.event_type='waiting_human'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM ops.automation_component_event e
                     WHERE e.component_run_id=c.component_run_id AND e.event_type='human_answered'
                 )
               ORDER BY c.created_at DESC LIMIT 1""",
            (step_id,),
        )
        linked = cursor.fetchone()
        if linked:
            return str(linked["verification_challenge_id"])
        cursor.execute("SELECT platform_name,company_name,shop_name,started_at FROM ops.automation_step_run WHERE step_run_id=%s", (step_id,))
        step = cursor.fetchone()
        if not step:
            return None
        cursor.execute("SELECT to_regclass('ai.verification_challenge') AS relation")
        if not cursor.fetchone()["relation"]:
            return None
        cursor.execute(
            """SELECT challenge_uuid FROM ai.verification_challenge
               WHERE status='pending' AND platform_name=%s AND company_name=%s AND shop_name=%s
                 AND created_at>=COALESCE(%s,NOW()-INTERVAL '1 hour')
               ORDER BY created_at DESC LIMIT 1""",
            (step["platform_name"], step["company_name"], step["shop_name"], step["started_at"]),
        )
        row = cursor.fetchone()
        return str(row["challenge_uuid"]) if row else None

    def record_artifacts(self, run_id: str, step_id: str, artifacts: Iterable[dict], period: dict) -> list[dict]:
        artifacts = list(artifacts)
        if not artifacts:
            return []
        saved: list[dict] = []
        with self.transaction() as cursor:
            cursor.execute("SELECT shop_code FROM ops.automation_step_run WHERE step_run_id=%s AND automation_run_id=%s", (step_id,run_id))
            step = cursor.fetchone()
            mapped = bool(step and step.get('shop_code'))
            for item in artifacts:
                relative = str(item["relative_path"]).replace("\\", "/")
                cursor.execute(
                    """INSERT INTO ops.automation_artifact(
                           artifact_id,automation_run_id,step_run_id,artifact_type,file_name,relative_path,
                           file_size_bytes,file_hash,business_date_start,business_date_end,report_type,period_type,coverage_verified)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT(automation_run_id,step_run_id,relative_path) DO UPDATE SET
                           file_size_bytes=EXCLUDED.file_size_bytes,file_hash=EXCLUDED.file_hash,
                           report_type=EXCLUDED.report_type,business_date_start=EXCLUDED.business_date_start,
                           business_date_end=EXCLUDED.business_date_end,period_type=EXCLUDED.period_type,
                           coverage_verified=EXCLUDED.coverage_verified
                       RETURNING *""",
                    (str(uuid.uuid4()), run_id, step_id, item.get("artifact_type") or "report_file", item["file_name"], relative,
                     int(item.get("file_size_bytes") or 0), item.get("file_hash"),
                     item.get("business_date_start") or period.get("business_date_start"),
                     item.get("business_date_end") or period.get("business_date_end"), item.get("report_type"),
                     item.get("period_type") or "unknown", bool(item.get("coverage_verified") and mapped)),
                )
                saved.append(dict(cursor.fetchone()))
        return saved

    def submit_artifacts_to_ingest(
        self,
        run_id: str,
        step_id: str,
        artifacts: list[dict],
        operator: str = "AutomationWorker",
        *,
        auto_refresh: bool = True,
    ) -> dict:
        recognized: list[tuple[dict, dict, Path]] = []
        warnings: list[str] = []
        for artifact in artifacts:
            if artifact.get("artifact_type") == "archive" or Path(artifact["file_name"]).suffix.lower() == ".zip":
                warnings.append(f"归档文件已下载，待现有流程解压后导入：{artifact['file_name']}")
                continue
            path = (self.archive_root / artifact["relative_path"]).resolve()
            try:
                path.relative_to(self.archive_root.resolve())
            except ValueError:
                warnings.append(f"归档路径越界：{artifact['file_name']}")
                continue
            if not path.is_file():
                warnings.append(f"归档文件不存在：{artifact['file_name']}")
                continue
            try:
                guessed = self.file_ingest.guess(artifact["file_name"])
            except Exception as exc:
                warnings.append(f"文件识别失败：{artifact['file_name']}；{redact(exc)}")
                continue
            if not guessed.get("matched"):
                warnings.append(f"待人工导入：{artifact['file_name']}")
                continue
            recognized.append((artifact, guessed, path))
        if not recognized:
            return {"ingest_run_id": None, "recognized": 0, "warnings": warnings}
        ingest = self.file_ingest.create_run({
            "idempotency_key": f"automation:{run_id}:{step_id}",
            "expected_file_count": len(recognized), "auto_refresh": bool(auto_refresh),
        }, operator, "api")
        ingest_run_id = str(ingest["run_id"])
        uploaded_count = 0
        submission_failed = False
        for artifact, guessed, path in recognized:
            with self.transaction() as cursor:
                cursor.execute(
                    "UPDATE ops.automation_artifact SET report_type=%s WHERE artifact_id=%s",
                    (guessed["report_type"], artifact["artifact_id"]),
                )
                cursor.execute('''SELECT s.platform_code,s.shop_code,a.coverage_verified,
                    a.business_date_start,a.business_date_end,a.file_hash
                    FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id)
                    WHERE a.artifact_id=%s''', (artifact['artifact_id'],))
                receipt = dict(cursor.fetchone())
            metadata = {'client_file_id':str(artifact['artifact_id']), 'report_type':guessed['report_type'],
                        'shop_code':receipt['shop_code']}
            if receipt['platform_code'] != guessed['platform_code']:
                warnings.append('下载回执平台与文件识别平台不一致，停止提交该文件')
                continue
            if receipt['file_hash'] and hashlib.sha256(path.read_bytes()).hexdigest() != receipt['file_hash']:
                warnings.append('下载成果SHA256不一致，停止提交该文件')
                continue
            if guessed['report_type'] in {'douyin_fund','douyin_settlement','jd_fund','jd_settlement'} and receipt['coverage_verified'] and receipt['business_date_start'] and receipt['business_date_end']:
                metadata['coverage'] = {'start':str(receipt['business_date_start']), 'end':str(receipt['business_date_end']),
                    'complete_export':True, 'artifact_id':artifact['artifact_id'], 'reason':'下载请求与归档回执一致'}
            try:
                task = self.file_ingest.save_upload(
                    ingest_run_id, filename=artifact["file_name"], content=path.read_bytes(),
                    metadata=metadata,
                    operator=operator, ip_address=None,
                )
            except Exception as exc:
                warnings.append(f"自动导入提交失败：{artifact['file_name']}；{redact(exc)}")
                continue
            uploaded_count += 1
            with self.transaction() as cursor:
                cursor.execute(
                    """UPDATE ops.automation_artifact SET report_type=%s,ingest_file_task_id=%s,batch_id=%s
                       WHERE artifact_id=%s""",
                    (guessed["report_type"], task["file_task_id"], task.get("batch_id"), artifact["artifact_id"]),
                )
        try:
            if uploaded_count != len(recognized):
                submission_failed = True
                self.file_ingest.fail_run(ingest_run_id, operator, None, "Automation 成果未全部提交")
            else:
                self.file_ingest.complete_run(ingest_run_id, operator, None)
        except Exception as exc:
            submission_failed = True
            warnings.append(f"FileIngest 会话未能提交：{redact(exc)}")
        with self.transaction() as cursor:
            cursor.execute("""UPDATE ops.automation_step_run SET ingest_run_id=%s,
                error_message=CASE WHEN %s THEN 'ingest_failed' ELSE error_message END,
                updated_at=NOW() WHERE step_run_id=%s""", (ingest_run_id, submission_failed, step_id))
            cursor.execute("UPDATE ops.automation_run SET ingest_run_id=COALESCE(ingest_run_id,%s),updated_at=NOW() WHERE automation_run_id=%s", (ingest_run_id, run_id))
        return {"ingest_run_id": ingest_run_id, "recognized": len(recognized), "warnings": warnings}

    def trigger_etl_for_ingest(
        self,
        ingest_run_id: str,
        *,
        operator: str = "AutomationFlowRunner",
    ) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT status FROM ops.ingest_run WHERE run_id=%s",
                (ingest_run_id,),
            )
            run = cursor.fetchone()
            if not run:
                raise AutomationNotFoundError("FileIngest 会话不存在")
            if run["status"] not in {"success", "no_change"}:
                raise ValueError(f"FileIngest 尚未完成，当前状态：{run['status']}")
            cursor.execute(
                """SELECT DISTINCT report_type
                   FROM ops.ingest_file_task
                   WHERE run_id=%s AND report_type IS NOT NULL
                     AND status='success'""",
                (ingest_run_id,),
            )
            report_types = [row["report_type"] for row in cursor.fetchall()]
        keys: set[str] = set()
        for report_type in report_types:
            spec = REPORT_BY_TYPE.get(report_type)
            if spec:
                keys.update(spec.etl_keys)
        return self.file_ingest.create_etl_run(
            keys,
            trigger_type="ingest_complete",
            scope="affected",
            operator=operator,
            ingest_run_id=ingest_run_id,
        )

    def sync_downstream_links(self, run_id: str) -> None:
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_artifact a SET batch_id=ft.batch_id
                   FROM ops.ingest_file_task ft
                   WHERE a.automation_run_id=%s AND a.ingest_file_task_id=ft.file_task_id AND ft.batch_id IS NOT NULL""", (run_id,)
            )
            cursor.execute(
                """UPDATE ops.automation_step_run s SET
                       etl_run_id=(SELECT e.etl_run_id FROM ops.etl_run e
                                   WHERE e.ingest_run_id=s.ingest_run_id ORDER BY e.created_at DESC LIMIT 1),
                       updated_at=NOW()
                   WHERE s.automation_run_id=%s AND s.ingest_run_id IS NOT NULL
                     AND EXISTS(SELECT 1 FROM ops.etl_run e WHERE e.ingest_run_id=s.ingest_run_id)""", (run_id,)
            )

    def recover_stale(self, minimum_age_minutes: int = 15) -> dict[str, int]:
        age = max(1, int(minimum_age_minutes))
        with self.transaction() as cursor:
            cursor.execute(
                """UPDATE ops.automation_step_run SET status='failed',error_message='AutomationWorker异常退出，步骤已回收',
                          finished_at=NOW(),updated_at=NOW()
                   WHERE status='running' AND automation_run_id IN (
                       SELECT automation_run_id FROM ops.automation_run
                       WHERE status='running' AND COALESCE(heartbeat_at,attempt_started_at,started_at,queued_at)<NOW()-(%s*INTERVAL '1 minute')
                         AND COALESCE(input_context->>'execution_source','') <> 'external'
                   )""", (age,)
            )
            steps = cursor.rowcount
            cursor.execute(
                """UPDATE ops.automation_run SET status='failed',error_message='AutomationWorker异常退出，运行已回收',
                          finished_at=NOW(),waiting_since=NULL,updated_at=NOW()
                   WHERE status='running' AND COALESCE(heartbeat_at,attempt_started_at,started_at,queued_at)<NOW()-(%s*INTERVAL '1 minute')
                     AND COALESCE(input_context->>'execution_source','') <> 'external'
                   RETURNING *""", (age,)
            )
            stale_runs = [dict(row) for row in cursor.fetchall()]
            stale_run_ids = [str(row["automation_run_id"]) for row in stale_runs]
            for stale_run in stale_runs:
                self._enqueue_notification_cursor(cursor, stale_run)
            runs = len(stale_run_ids)
            if stale_run_ids:
                cursor.execute(
                    """UPDATE ops.automation_resource_lock l
                       SET lock_state='paused'
                       FROM ops.automation_run r
                       WHERE r.automation_run_id=l.automation_run_id
                         AND l.automation_run_id=ANY(%s::uuid[])
                         AND r.execution_lane IN ('interactive','overnight')""",
                    (stale_run_ids,),
                )
                cursor.execute(
                    """DELETE FROM ops.automation_resource_lock l
                       USING ops.automation_run r
                       WHERE l.automation_run_id=r.automation_run_id
                         AND l.automation_run_id=ANY(%s::uuid[])
                         AND r.execution_lane NOT IN ('interactive','overnight')""",
                    (stale_run_ids,),
                )
            cursor.execute(
                """DELETE FROM ops.automation_resource_lock l
                   WHERE NOT EXISTS (
                       SELECT 1 FROM ops.automation_run r
                       WHERE r.automation_run_id=l.automation_run_id
                         AND ((r.status='running' AND l.lock_state='running')
                           OR (r.status IN ('needs_human','failed','queued')
                               AND l.lock_state='paused'))
                   )"""
            )
        return {"runs": runs, "steps": steps}

    @staticmethod
    def file_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
