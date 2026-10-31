from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, unquote

from apps.identity_access.authorization import AuthorizationError

from .service import AutomationService


APP_DIR = Path(__file__).resolve().parent


def query_values(query_string: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(query_string).items()}


class AutomationCenterModule:
    page_prefix = "/automation"
    api_prefix = "/api/automation"

    def __init__(self, args, *, file_ingest_service=None):
        self.service = AutomationService(args, file_ingest_service=file_ingest_service)
        self.static_dir = APP_DIR / "static"

    def migrate(self) -> list[str]:
        return self.service.migrate()

    def static_file(self, request_path: str) -> Path | None:
        relative = request_path.removeprefix(self.page_prefix).lstrip("/") or "index.html"
        target = (self.static_dir / unquote(relative)).resolve()
        root = self.static_dir.resolve()
        if target != root and root not in target.parents:
            return None
        return target if target.is_file() else self.static_dir / "index.html"

    @staticmethod
    def _require(context, permission: str) -> None:
        if context is None or not context.can(permission):
            raise AuthorizationError(f"缺少权限：{permission}")

    def dispatch(self, method: str, path: str, query_string: str = "", payload: dict | None = None,
                 *, context=None, operator: str = "系统", ip_address: str | None = None):
        if path.startswith("/api/automation/verification/"):
            return None
        if not (path == self.api_prefix or path.startswith(self.api_prefix + "/")):
            return None
        query = query_values(query_string)
        payload = payload or {}
        if method == "GET":
            if path == "/api/automation/report-targets":
                self._require(context, "automation.results.view")
                return self.service.report_targets(), 200
            if path == "/api/automation/report-calendar":
                self._require(context, "automation.results.view")
                return self.service.report_calendar(query), 200
            if path == "/api/automation/report-day":
                self._require(context, "automation.results.view")
                return self.service.report_day(query), 200
            if path == "/api/automation/report-settings":
                self._require(context, "automation.results.view")
                return self.service.report_targets(), 200
            match = re.fullmatch(r"/api/automation/report-batches/([0-9a-fA-F-]{36})", path)
            if match:
                self._require(context, "automation.results.view")
                return self.service.report_batch(match.group(1)), 200
            if path == "/api/automation/workbench":
                self._require(context, "automation.workbench.view")
                return self.service.dashboard(query.get("date")), 200
            if path == "/api/automation/jobs":
                self._require(context, "automation.jobs.view")
                return self.service.list_jobs(), 200
            if path == "/api/automation/components":
                self._require(context, "automation.flows.view")
                return self.service.list_components(), 200
            match = re.fullmatch(r"/api/automation/components/runs/([0-9a-fA-F-]{36})/repair-context", path)
            if match:
                self._require(context, "automation.runs.view")
                return self.service.component_repair_context(match.group(1)), 200
            if path == "/api/automation/flows":
                self._require(context, "automation.flows.view")
                return self.service.list_flows(), 200
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/versions", path)
            if match:
                self._require(context, "automation.flows.view")
                return self.service.list_flow_versions(match.group(1)), 200
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})", path)
            if match:
                self._require(context, "automation.flows.view")
                return self.service.get_flow(match.group(1)), 200
            match = re.fullmatch(r"/api/automation/jobs/(\d+)", path)
            if match:
                self._require(context, "automation.jobs.view")
                return self.service.get_job(int(match.group(1))), 200
            if path == "/api/automation/runs":
                self._require(context, "automation.runs.view")
                return self.service.list_runs(query), 200
            match = re.fullmatch(r"/api/automation/runs/([0-9a-fA-F-]{36})", path)
            if match:
                self._require(context, "automation.runs.view")
                return self.service.get_run(match.group(1)), 200
            if path == "/api/automation/daily-results":
                self._require(context, "automation.results.view")
                return self.service.daily_results(query), 200
            if path == "/api/automation/faults":
                self._require(context, "automation.runs.view")
                return self.service.fault_center(query), 200
            if path == "/api/automation/runtime-resources":
                self._require(context, "automation.workbench.view")
                return self.service.runtime_resources(), 200
            if path == "/api/automation/notification-policy":
                self._require(context, "automation.jobs.view")
                return self.service.notification_policy(), 200
            if path == "/api/automation/health":
                self._require(context, "automation.workbench.view")
                return self.service.health(), 200
        if method == "POST":
            if path == "/api/automation/report-batches/preview":
                self._require(context, "automation.runs.execute")
                return self.service.preview_report_batch(payload), 200
            if path == "/api/automation/report-batches":
                self._require(context, "automation.runs.execute")
                return self.service.create_report_batch(payload, operator, ip_address), 202
            if path == "/api/automation/flows":
                self._require(context, "automation.flows.manage")
                return self.service.create_flow(payload, operator, ip_address), 201
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/publish", path)
            if match:
                self._require(context, "automation.flows.manage")
                return self.service.publish_flow(match.group(1), operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/versions/(\d+)/rollback", path)
            if match:
                self._require(context, "automation.flows.manage")
                return self.service.rollback_flow_version(match.group(1), int(match.group(2)), operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/run", path)
            if match:
                self._require(context, "automation.flows.execute")
                return self.service.create_flow_run(match.group(1), payload, operator, ip_address), 202
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/test-run", path)
            if match:
                self._require(context, "automation.flows.execute")
                return self.service.create_flow_test_run(match.group(1), payload, operator, ip_address), 202
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})/enabled", path)
            if match:
                self._require(context, "automation.flows.manage")
                return self.service.set_flow_enabled(match.group(1), bool(payload.get("enabled")), operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/jobs/(\d+)/run", path)
            if match:
                self._require(context, "automation.runs.execute")
                return self.service.create_run(int(match.group(1)), trigger_type="manual", operator=operator,
                                               business_date=payload.get("business_date"), ip_address=ip_address), 202
            match = re.fullmatch(r"/api/automation/jobs/(\d+)/enabled", path)
            if match:
                self._require(context, "automation.jobs.manage")
                return self.service.set_job_enabled(int(match.group(1)), bool(payload.get("enabled")), operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/runs/([0-9a-fA-F-]{36})/retry", path)
            if match:
                self._require(context, "automation.runs.retry")
                return self.service.retry_run(match.group(1), operator, ip_address), 202
            match = re.fullmatch(r"/api/automation/runs/([0-9a-fA-F-]{36})/resume", path)
            if match:
                self._require(context, "automation.runs.retry")
                return self.service.resume_run(
                    match.group(1), operator, ip_address, str(payload.get("reason") or "manual")
                ), 202
            match = re.fullmatch(r"/api/automation/runs/([0-9a-fA-F-]{36})/acknowledge", path)
            if match:
                self._require(context, "automation.runs.retry")
                return self.service.acknowledge_run(
                    match.group(1), operator, str(payload.get("reason") or ""), ip_address
                ), 200
            match = re.fullmatch(r"/api/automation/runs/([0-9a-fA-F-]{36})/cancel", path)
            if match:
                self._require(context, "automation.runs.execute")
                return self.service.cancel_run(match.group(1), operator, ip_address), 200
        if method == "PUT":
            if path == "/api/automation/report-settings":
                self._require(context, "automation.jobs.manage")
                return self.service.update_report_settings(payload, operator, ip_address), 200
            if path == "/api/automation/notification-policy":
                self._require(context, "automation.jobs.manage")
                return self.service.update_notification_policy(payload, operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})", path)
            if match:
                self._require(context, "automation.flows.manage")
                return self.service.update_flow(match.group(1), payload, operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/jobs/(\d+)", path)
            if match:
                self._require(context, "automation.jobs.manage")
                return self.service.update_job(int(match.group(1)), payload, operator, ip_address), 200
        if method == "DELETE":
            match = re.fullmatch(r"/api/automation/flows/([0-9a-fA-F-]{36})", path)
            if match:
                self._require(context, "automation.flows.manage")
                return self.service.delete_flow(match.group(1), operator, ip_address), 200
            match = re.fullmatch(r"/api/automation/jobs/(\d+)", path)
            if match:
                self._require(context, "automation.jobs.manage")
                return self.service.delete_job(int(match.group(1)), operator, ip_address), 200
        return None
