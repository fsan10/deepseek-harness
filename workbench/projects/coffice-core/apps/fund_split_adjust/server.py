#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import re
import socket
import sys
import tempfile
import threading
from datetime import date, datetime, time
from decimal import Decimal
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from uuid import UUID

from openpyxl import Workbook

if __package__ in (None, ""):
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(PROJECT_ROOT))
    from apps.fund_split_adjust.database import ConflictError, Database, NotFoundError
    from apps.fund_split_adjust.influencer_module import InfluencerModule
    from apps.file_ingest.module import FileIngestModule
    from apps.file_ingest.service import FileIngestWorker
    from apps.automation_center.module import AutomationCenterModule
    from apps.identity_access.authorization import (
        FINANCE_PAGE_PERMISSION_CODES,
        AuthenticationError,
        AuthorizationError,
        required_permission,
    )
    from apps.identity_access.module import IdentityAccessModule, ModuleResponse
    from apps.identity_access.navigation import build_navigation
    from apps.dashboard_center.module import DashboardModule
    from apps.dashboard_center.proxy import DataEaseEmbedProxy
    from apps.common.health import HealthAggregator
    from apps.ai_admin.module import AiManagementModule
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
    from .database import ConflictError, Database, NotFoundError
    from .influencer_module import InfluencerModule
    from apps.file_ingest.module import FileIngestModule
    from apps.file_ingest.service import FileIngestWorker
    from apps.automation_center.module import AutomationCenterModule
    from apps.identity_access.authorization import (
        FINANCE_PAGE_PERMISSION_CODES,
        AuthenticationError,
        AuthorizationError,
        required_permission,
    )
    from apps.identity_access.module import IdentityAccessModule, ModuleResponse
    from apps.identity_access.navigation import build_navigation
    from apps.dashboard_center.module import DashboardModule
    from apps.dashboard_center.proxy import DataEaseEmbedProxy
    from apps.common.health import HealthAggregator
    from apps.ai_admin.module import AiManagementModule


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = APP_DIR / "uploads"
APP_VERSION = "2026.09.21-r24"
APP_FEATURES = ["add_split_row", "split_add_row_alias", "paged_management", "preserve_adjustment_on_split", "parent_and_child_adjustment", "fixed_parent_child_allocation", "multi_field_statement_search", "expense_type_filter", "complete_log_filters", "multi_field_log_search", "withdraw_submit", "hierarchical_assignment", "amount_restore", "frontend_amount_calculator", "transient_upload_selection", "visible_batch_selector", "modular_influencer_console", "server_sessions", "csrf_protection", "dynamic_rbac_navigation", "dataease_dashboard_center", "dataease_embed_proxy", "unified_health", "no_permission_welcome", "login_rate_limit", "system_action_feedback", "async_influencer_refresh", "ai_management_center", "readonly_ai_analysis", "shared_web_feishu_ai", "ai_catalog_and_policy", "automation_workbench"]


def load_project_env() -> None:
    """Load missing development settings from the project .env file.

    Explicit process environment variables remain authoritative so production
    launchers and container environments are not overridden.  The server does
    not depend on python-dotenv, but supports the simple KEY=value entries used
    by this project, including quoted values and comments.
    """

    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key or key in os.environ:
            continue
        # Windows CRT does not understand IANA names such as Asia/Shanghai in
        # TZ. Keep the Windows system timezone instead of injecting dotenv TZ
        # into this process and its download subprocesses.
        if os.name == "nt" and key.upper() == "TZ":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """禁止 Windows 地址复用，避免旧、新后端同时监听同一端口。"""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def json_default(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"无法序列化：{type(value)!r}")


def query_values(parsed) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(parsed.query).items()}


def query_int(query: dict, key: str, default=None, *, minimum: int = 1):
    """安全解析查询串里的整数参数。

    浏览器把 ``NaN``、``undefined`` 或空串拼进查询串时，裸 ``int()`` 会抛
    ``ValueError: invalid literal for int() with base 10: 'NaN'`` 并落成 500。
    这里统一转成「字段名 + 必须是整数」的 400 提示，数值越界按边界收敛。
    """

    value = query.get(key)
    text = "" if value is None else str(value).strip()
    if not text:
        return default
    try:
        number = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是整数") from exc
    return max(minimum, number)


class ApplicationHandler(BaseHTTPRequestHandler):
    server_version = f"FundSplitAdjust/{APP_VERSION}"
    database: Database

    @property
    def db(self) -> Database:
        return self.server.database  # type: ignore[attr-defined]

    @property
    def influencer_module(self) -> InfluencerModule:
        return self.server.influencer_module  # type: ignore[attr-defined]

    @property
    def file_ingest_module(self) -> FileIngestModule:
        return self.server.file_ingest_module  # type: ignore[attr-defined]

    @property
    def identity_module(self) -> IdentityAccessModule:
        return self.server.identity_module  # type: ignore[attr-defined]

    @property
    def dashboard_module(self) -> DashboardModule:
        return self.server.dashboard_module  # type: ignore[attr-defined]

    @property
    def health_service(self) -> HealthAggregator:
        return self.server.health_service  # type: ignore[attr-defined]

    @property
    def ai_module(self) -> AiManagementModule:
        return self.server.ai_module  # type: ignore[attr-defined]

    @property
    def automation_module(self) -> AutomationCenterModule:
        return self.server.automation_module  # type: ignore[attr-defined]

    @property
    def operator(self) -> str:
        context = getattr(self, "auth_context", None)
        return (context.display_name if context else "自动化机器人")[:100]

    @property
    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For")
        return (forwarded.split(",")[0].strip() if forwarded else self.client_address[0])[:45]

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, data=None, *, status: int = 200, message: str = "success", code: int = 0, headers: dict | None = None) -> None:
        body = json.dumps({"code": code, "data": data, "message": message}, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            for item in value if isinstance(value, list) else [value]:
                self.send_header(name, item)
        self.end_headers()
        self.wfile.write(body)

    def handle_error(self, exc: Exception) -> None:
        response_headers = {}
        if getattr(exc, "retry_after", None):
            response_headers["Retry-After"] = str(int(exc.retry_after))
        explicit_status = getattr(exc, "http_status", None)
        if explicit_status:
            status = HTTPStatus(explicit_status)
        elif getattr(exc, "pgcode", None) in {"23505", "23503"}:
            status = HTTPStatus.CONFLICT
            exc = ConflictError("数据违反唯一约束或仍被其他记录引用")
        elif getattr(exc, "pgcode", None) == "23514":
            status = HTTPStatus.BAD_REQUEST
            exc = ValueError("数据不符合字段约束")
        elif isinstance(exc, NotFoundError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, ConflictError):
            status = HTTPStatus.CONFLICT
        elif isinstance(exc, PermissionError):
            status = HTTPStatus.FORBIDDEN
        elif isinstance(exc, (ValueError, KeyError, TypeError)):
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            print(f"请求失败：{exc!r}", file=sys.stderr)
        details = getattr(exc, "details", None)
        error_data = {"details": details} if details is not None else None
        self.send_json(error_data, status=status, code=int(status), message=str(exc) or status.phrase, headers=response_headers)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2 * 1024 * 1024:
            raise ValueError("JSON请求体过大")
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("JSON格式错误") from exc

    def is_robot_request(self, method: str, path: str) -> bool:
        authorization = self.headers.get("Authorization", "")
        if path.startswith('/api/ingest/') and authorization.lower().startswith('bearer '):
            expected = os.getenv('INGEST_ROBOT_TOKEN') or ''
            supplied = authorization[7:].strip()
            allowed = (method == 'POST' and (path == '/api/ingest/runs' or bool(re.fullmatch(
                r'/api/ingest/runs/[^/]+/(files|complete|fail|coverage-preflight)',path)))) or (
                method == 'GET' and bool(re.fullmatch(r'/api/ingest/(runs(/[^/]+)?|health|report-types|shops)',path)))
            return bool(allowed and expected and supplied and hmac.compare_digest(expected,supplied))
        if method in {"GET", "POST"} and path.startswith("/api/automation/verification/"):
            expected = os.getenv("AUTOMATION_ROBOT_TOKEN") or os.getenv("INGEST_ROBOT_TOKEN")
            supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
            return bool(expected and supplied and hmac.compare_digest(supplied, expected))
        return False

    def prepare_request(self, method: str, path: str):
        if path == "/api/auth/login":
            self.auth_context = None
            return None
        if self.is_robot_request(method, path):
            self.auth_context = None
            return None
        context = self.identity_module.auth.authenticate(self.headers)
        self.auth_context = context
        permission = required_permission(method, path)
        allowed = any(context.can(code) for code in permission) if isinstance(permission, tuple) else context.can(permission)
        if permission and not allowed:
            label = " / ".join(permission) if isinstance(permission, tuple) else permission
            raise AuthorizationError(f"缺少权限：{label}")
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            self.identity_module.auth.verify_csrf(context, self.headers)
        return context

    def send_module_response(self, response: ModuleResponse) -> None:
        if response.status == 404:
            self.send_json(None, status=404, code=404, message="接口不存在")
        else:
            self.send_json(response.data, status=response.status, headers=response.headers)

    def serve_path(self, target: Path, *, status: int = HTTPStatus.OK) -> None:
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        self.send_response(status)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def require_page_access(self, path: str) -> None:
        context = self.auth_context
        groups = {
            "/influencer": ("influencer.assignments.view", "influencer.targets.view", "influencer.products.view"),
            "/ingest": ("ingest.upload.view", "ingest.runs.view", "ingest.etl.view", "ingest.logs.view",
                        "platform_fee.categories.view", "platform_fee.mappings.view", "platform_fee.raw.view",
                        *FINANCE_PAGE_PERMISSION_CODES),
            "/system": ("system.dashboard.manage", "system.user.manage", "system.department.manage",
                        "system.role.manage", "system.permission.manage", "system.audit.view"),
            "/ai": ("ai.analysis.view",),
            "/ai-admin": ("ai.model.manage", "ai.datasource.manage",
                          "ai.prompt.manage", "ai.feishu_app.manage", "ai.audit.view"),
            "/automation": ("automation.workbench.view", "automation.jobs.view",
                            "automation.flows.view", "automation.runs.view", "automation.results.view"),
        }
        prefix = next((key for key in groups if path == key or path.startswith(key + "/")), None)
        if prefix and not any(context.can(code) for code in groups[prefix]):
            raise AuthorizationError("无权进入该模块")
        if path == "/dashboards" or path.startswith("/dashboards/"):
            if not self.dashboard_module.service.permitted(context)["items"]:
                raise AuthorizationError("没有可查看的经营看板")

    def read_upload(self) -> tuple[Path, str]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("导入接口必须使用multipart/form-data")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_SIZE:
            raise ValueError("上传文件为空或超过50MB")
        body = self.rfile.read(length)
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        for part in message.iter_parts():
            if part.get_param("name", header="content-disposition") == "file":
                filename = Path(part.get_filename() or "bank_statement.xlsx").name
                if Path(filename).suffix.lower() != ".xlsx":
                    raise ValueError("仅支持.xlsx格式文件")
                payload = part.get_payload(decode=True) or b""
                if not payload:
                    raise ValueError("上传文件为空")
                temp = tempfile.NamedTemporaryFile(prefix="fund_upload_", suffix=".xlsx", delete=False)
                temp.write(payload)
                temp.close()
                return Path(temp.name), filename
        raise ValueError("未找到上传字段file")

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else unquote(request_path).lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_influencer_static(self, request_path: str) -> None:
        target = self.influencer_module.static_file(request_path)
        if target is None:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_ingest_static(self, request_path: str) -> None:
        target = self.file_ingest_module.static_file(request_path)
        if target is None:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(target.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, download_name: str, content_type: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") -> None:
        body = path.read_bytes()
        quoted = unquote(download_name).replace('"', "")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{__import__('urllib.parse').parse.quote(quoted)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_log_export(self, query: dict[str, str]) -> None:
        rows = self.db.operation_logs(query, export_all=True)["items"]
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "操作日志"
        headers = ["日志编号", "操作时间", "操作类型", "操作人", "对象类型", "对象描述", "变更详情", "变更金额", "IP"]
        sheet.append(headers)
        for row in rows:
            sheet.append([
                row["log_no"], row["created_at"], row["operation_type"], row["operator"], row["target_type"],
                row["target_description"], json.dumps(row.get("change_detail"), ensure_ascii=False, default=json_default),
                row.get("change_amount"), row.get("ip_address"),
            ])
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = __import__("openpyxl.styles").styles.Font(bold=True, color="FFFFFF")
            cell.fill = __import__("openpyxl.styles").styles.PatternFill("solid", fgColor="1677FF")
        output = BytesIO()
        workbook.save(output)
        body = output.getvalue()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", "attachment; filename=operation_logs.xlsx")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = query_values(parsed)
        try:
            if parsed.path.startswith(("/login", "/identity-assets/")):
                target = self.identity_module.static_file(parsed.path)
                if target:
                    self.serve_path(target)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                context = self.prepare_request("GET", parsed.path)
            except AuthenticationError:
                if not parsed.path.startswith("/api/"):
                    self.serve_path(self.identity_module.static_dir / "login.html", status=HTTPStatus.UNAUTHORIZED)
                    return
                raise
            if parsed.path == "/api/navigation":
                self.send_json(build_navigation(context, self.dashboard_module.service))
                return
            if parsed.path == "/api/health":
                self.send_json(self.health_service.snapshot())
                return
            if parsed.path == "/api/ingest/health":
                self.send_json(self.health_service.legacy_ingest(), headers={
                    "Deprecation": "true",
                    "Link": '</api/health>; rel="successor-version"',
                    "Warning": '299 - "Deprecated health endpoint; use /api/health"',
                })
                return
            if parsed.path == "/api/influencer/health":
                self.send_json(self.health_service.legacy_influencer(), headers={
                    "Deprecation": "true",
                    "Link": '</api/health>; rel="successor-version"',
                    "Warning": '299 - "Deprecated health endpoint; use /api/health"',
                })
                return
            identity_result = self.identity_module.dispatch(
                "GET", parsed.path, query, None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if identity_result is not None:
                self.send_module_response(identity_result)
                return
            dashboard_result = self.dashboard_module.dispatch(
                "GET", parsed.path, query, None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if dashboard_result is not None:
                self.send_module_response(dashboard_result)
                return
            ai_result = self.ai_module.dispatch(
                "GET", parsed.path, query, None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if ai_result is not None:
                self.send_module_response(ai_result)
                return
            automation_result = self.automation_module.dispatch(
                "GET", parsed.path, parsed.query, context=context, operator=self.operator,
                ip_address=self.client_ip,
            )
            if automation_result is not None:
                data, status = automation_result
                self.send_json(data, status=status)
                return
            if parsed.path.startswith(("/ai/", "/ai-assets/", "/ai-admin", "/ai-admin-assets/")):
                self.require_page_access(parsed.path)
                target = self.ai_module.static_file(parsed.path)
                if target:
                    self.serve_path(target)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            if parsed.path.startswith(("/welcome", "/system", "/dashboards", "/dashboard-assets/")):
                self.require_page_access(parsed.path)
                target = self.identity_module.static_file(parsed.path) or self.dashboard_module.static_file(parsed.path)
                if target:
                    self.serve_path(target)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            if parsed.path == "/automation":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/automation/")
                self.end_headers()
                return
            if parsed.path.startswith("/automation/"):
                self.require_page_access(parsed.path)
                target = self.automation_module.static_file(parsed.path)
                if target:
                    self.serve_path(target)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.require_page_access(parsed.path)
            if parsed.path == "/" and not any(context.can(code) for code in (
                "bank.statement.view", "bank.types.view", "bank.accounts.view", "bank.imports.view", "bank.logs.view",
            )):
                navigation = build_navigation(context, self.dashboard_module.service)
                first_item = next((item for group in navigation["groups"] for item in group["items"]), None)
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", first_item["href"] if first_item else "/welcome/")
                self.end_headers()
                return
            if parsed.path == "/influencer":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/influencer/")
                self.end_headers()
                return
            if parsed.path.startswith("/influencer/"):
                self.serve_influencer_static(parsed.path)
                return
            if parsed.path == "/ingest":
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/ingest/")
                self.end_headers()
                return
            if parsed.path.startswith("/ingest/"):
                self.serve_ingest_static(parsed.path)
                return
            ingest_result = self.file_ingest_module.dispatch(
                "GET", parsed.path, parsed.query, context=context, operator=self.operator,
                ip_address=self.client_ip, headers=self.headers,
            )
            if ingest_result is not None:
                data, status = ingest_result
                self.send_json(data, status=status)
                return
            if any(parsed.path.startswith(prefix + "/") for prefix in self.file_ingest_module.api_prefixes):
                self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="数据导入接口不存在")
                return
            if parsed.path.startswith("/api/automation/"):
                self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="自动化工作台接口不存在")
                return
            influencer_result = self.influencer_module.dispatch("GET", parsed.path, parsed.query)
            if influencer_result is not None:
                data, status = influencer_result
                self.send_json(data, status=status)
                return
            if parsed.path.startswith(f"{self.influencer_module.api_prefix}/"):
                self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="达播运营接口不存在")
                return
            if parsed.path == "/api/import/records":
                self.send_json(self.db.list_imports(page=query_int(query, "page", 1), page_size=query_int(query, "page_size", 20), date_from=query.get("date_from"), date_to=query.get("date_to"), keyword=query.get("keyword"), status=query.get("status")))
                return
            match = re.fullmatch(r"/api/import/records/([^/]+)/download", parsed.path)
            if match:
                path, name = self.db.import_file_path(match.group(1))
                self.send_file(path, name)
                return
            match = re.fullmatch(r"/api/statement/([^/]+)", parsed.path)
            if match:
                self.send_json(self.db.statement(match.group(1), query))
                return
            if parsed.path in {"/api/expense-types", "/api/expense-types/search"}:
                page = query_int(query, "page", None)
                self.send_json(self.db.expense_types(keyword=query.get("keyword"), active=query.get("is_active"), page=page, page_size=query_int(query, "page_size", 20)))
                return
            if parsed.path in {"/api/account-entries", "/api/account-entries/search"}:
                expense_id = query_int(query, "expense_type_id", None)
                page = query_int(query, "page", None)
                self.send_json(self.db.account_entries(keyword=query.get("keyword"), expense_type_id=expense_id, active=query.get("is_active"), page=page, page_size=query_int(query, "page_size", 20)))
                return
            if parsed.path == "/api/operation-logs":
                self.send_json(self.db.operation_logs(query))
                return
            if parsed.path == "/api/operation-logs/export":
                self.send_log_export(query)
                return
            self.serve_static(parsed.path)
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        temp_path: Path | None = None
        try:
            feishu_match = re.fullmatch(r"/api/ai/feishu/events/([a-z][a-z0-9_]{1,63})", parsed.path)
            if feishu_match:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 2 * 1024 * 1024:
                    raise ValueError("飞书事件请求体大小无效")
                self.send_json(self.ai_module.feishu.receive(self.headers, self.rfile.read(length), feishu_match.group(1)))
                return
            if parsed.path == "/api/auth/login":
                response = self.identity_module.dispatch(
                    "POST", parsed.path, query_values(parsed), self.read_json(), context=None,
                    ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
                )
                self.send_module_response(response)
                return
            context = self.prepare_request("POST", parsed.path)
            if parsed.path == "/api/import":
                temp_path, filename = self.read_upload()
                self.send_json(self.db.import_workbook(temp_path, original_name=filename, operator=self.operator, ip_address=self.client_ip), status=HTTPStatus.CREATED)
                return
            if re.fullmatch(r"/api/ingest/runs/[^/]+/files", parsed.path):
                data, status = self.file_ingest_module.upload(
                    parsed.path, self.headers, self.rfile,
                    operator=self.operator, ip_address=self.client_ip,
                )
                self.send_json(data, status=status)
                return
            payload = self.read_json()
            if parsed.path == "/api/ai/chat/stream":
                self.ai_module.stream_response(self, context, payload)
                return
            identity_result = self.identity_module.dispatch(
                "POST", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if identity_result is not None:
                self.send_module_response(identity_result)
                return
            dashboard_result = self.dashboard_module.dispatch(
                "POST", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if dashboard_result is not None:
                self.send_module_response(dashboard_result)
                return
            ai_result = self.ai_module.dispatch(
                "POST", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if ai_result is not None:
                self.send_module_response(ai_result)
                return
            automation_result = self.automation_module.dispatch(
                "POST", parsed.path, parsed.query, payload, context=context, operator=self.operator,
                ip_address=self.client_ip,
            )
            if automation_result is not None:
                data, status = automation_result
                self.send_json(data, status=status)
                return
            ingest_result = self.file_ingest_module.dispatch(
                "POST", parsed.path, parsed.query, payload, context=context, operator=self.operator,
                ip_address=self.client_ip, headers=self.headers,
            )
            if ingest_result is not None:
                data, status = ingest_result
                self.send_json(data, status=status)
                return
            influencer_result = self.influencer_module.dispatch("POST", parsed.path, parsed.query, payload)
            if influencer_result is not None:
                data, status = influencer_result
                self.send_json(data, status=status)
                return
            retry_match = re.fullmatch(r"/api/import/records/([^/]+)/retry", parsed.path)
            if retry_match:
                self.send_json(self.db.retry_import(retry_match.group(1), operator=self.operator, ip_address=self.client_ip))
                return
            if parsed.path == "/api/expense-types":
                self.send_json(self.db.create_expense(payload, self.operator, self.client_ip), status=HTTPStatus.CREATED)
                return
            if parsed.path == "/api/account-entries":
                self.send_json(self.db.create_account(payload, self.operator, self.client_ip), status=HTTPStatus.CREATED)
                return
            routes = [
                (r"/api/statement/([^/]+)/split", lambda batch: self.db.split(batch, payload, self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/split/cancel", lambda batch: self.db.cancel_split(batch, int(payload["ods_id"]), self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/split/expand-all", lambda batch: self.db.statement(batch, {"page_size": "200"})),
                (r"/api/statement/([^/]+)/add-split-row", lambda batch: self.db.add_split_row(batch, int(payload["ods_id"]), self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/split/add-row", lambda batch: self.db.add_split_row(batch, int(payload["ods_id"]), self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/adjust-parent", lambda batch: self.db.adjust_parent(batch, int(payload["ods_id"]), payload["new_amount"], self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/adjust-child", lambda batch: self.db.adjust_child(batch, int(payload["split_id"]), payload["new_amount"], self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/adjust", lambda batch: self.db.adjust(batch, int(payload["split_id"]), payload["new_amount"], self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/restore", lambda batch: self.db.restore_amount(batch, payload, self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/allocate-one-click", lambda batch: self.db.allocate_one_click(batch, int(payload["target_split_id"]), self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/batch-assign", lambda batch: self.db.batch_assign(batch, payload, self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/submit", lambda batch: self.db.submit(batch, self.operator, self.client_ip)),
                (r"/api/statement/([^/]+)/withdraw-submit", lambda batch: self.db.withdraw_submit(batch, str(payload.get("reason") or ""), self.operator, self.client_ip)),
            ]
            for pattern, action in routes:
                match = re.fullmatch(pattern, parsed.path)
                if match:
                    self.send_json(action(match.group(1)))
                    return
            self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="接口不存在")
        except Exception as exc:
            self.handle_error(exc)
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            context = self.prepare_request("PUT", parsed.path)
            payload = self.read_json()
            identity_result = self.identity_module.dispatch(
                "PUT", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if identity_result is not None:
                self.send_module_response(identity_result)
                return
            dashboard_result = self.dashboard_module.dispatch(
                "PUT", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if dashboard_result is not None:
                self.send_module_response(dashboard_result)
                return
            ai_result = self.ai_module.dispatch(
                "PUT", parsed.path, query_values(parsed), payload, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if ai_result is not None:
                self.send_module_response(ai_result)
                return
            automation_result = self.automation_module.dispatch(
                "PUT", parsed.path, parsed.query, payload, context=context, operator=self.operator,
                ip_address=self.client_ip,
            )
            if automation_result is not None:
                data, status = automation_result
                self.send_json(data, status=status)
                return
            ingest_result = self.file_ingest_module.dispatch(
                "PUT", parsed.path, parsed.query, payload, context=context, operator=self.operator,
                ip_address=self.client_ip, headers=self.headers,
            )
            if ingest_result is not None:
                data, status = ingest_result
                self.send_json(data, status=status)
                return
            influencer_result = self.influencer_module.dispatch("PUT", parsed.path, parsed.query, payload)
            if influencer_result is not None:
                data, status = influencer_result
                self.send_json(data, status=status)
                return
            match = re.fullmatch(r"/api/statement/([^/]+)/remark", parsed.path)
            if match:
                self.send_json(self.db.update_remark(match.group(1), int(payload["split_id"]), str(payload.get("remark") or ""), self.operator, self.client_ip))
                return
            match = re.fullmatch(r"/api/statement/([^/]+)/summary", parsed.path)
            if match:
                self.send_json(self.db.update_summary(match.group(1), int(payload["split_id"]), str(payload.get("summary") or ""), self.operator, self.client_ip))
                return
            match = re.fullmatch(r"/api/expense-types/(\d+)(/toggle-status)?", parsed.path)
            if match:
                result = self.db.toggle_expense(int(match.group(1)), self.operator, self.client_ip) if match.group(2) else self.db.update_expense(int(match.group(1)), payload, self.operator, self.client_ip)
                self.send_json(result)
                return
            match = re.fullmatch(r"/api/account-entries/(\d+)(/toggle-status)?", parsed.path)
            if match:
                result = self.db.toggle_account(int(match.group(1)), self.operator, self.client_ip) if match.group(2) else self.db.update_account(int(match.group(1)), payload, self.operator, self.client_ip)
                self.send_json(result)
                return
            self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="接口不存在")
        except Exception as exc:
            self.handle_error(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            context = self.prepare_request("DELETE", parsed.path)
            identity_result = self.identity_module.dispatch(
                "DELETE", parsed.path, query_values(parsed), None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if identity_result is not None:
                self.send_module_response(identity_result)
                return
            dashboard_result = self.dashboard_module.dispatch(
                "DELETE", parsed.path, query_values(parsed), None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if dashboard_result is not None:
                self.send_module_response(dashboard_result)
                return
            ai_result = self.ai_module.dispatch(
                "DELETE", parsed.path, query_values(parsed), None, context=context,
                ip_address=self.client_ip, user_agent=self.headers.get("User-Agent", ""),
            )
            if ai_result is not None:
                self.send_module_response(ai_result)
                return
            ingest_result = self.file_ingest_module.dispatch(
                "DELETE", parsed.path, parsed.query, None, context=context, operator=self.operator,
                ip_address=self.client_ip, headers=self.headers,
            )
            if ingest_result is not None:
                data, status = ingest_result
                self.send_json(data, status=status)
                return
            influencer_result = self.influencer_module.dispatch("DELETE", parsed.path, parsed.query)
            if influencer_result is not None:
                data, status = influencer_result
                self.send_json(data, status=status)
                return
            match = re.fullmatch(r"/api/expense-types/(\d+)", parsed.path)
            if match:
                self.send_json(self.db.delete_expense(int(match.group(1)), self.operator, self.client_ip))
                return
            match = re.fullmatch(r"/api/account-entries/(\d+)", parsed.path)
            if match:
                self.send_json(self.db.delete_account(int(match.group(1)), self.operator, self.client_ip))
                return
            self.send_json(None, status=HTTPStatus.NOT_FOUND, code=404, message="接口不存在")
        except Exception as exc:
            self.handle_error(exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="资金流水拆分调账系统")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--pg-port", dest="pg_port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument("--migrate", action="store_true", help="启动前执行本应用SQL迁移")
    parser.add_argument("--import-file", help="启动前导入指定银行xlsx")
    parser.add_argument("--operator", default="系统初始化")
    parser.add_argument("--no-serve", action="store_true", help="完成迁移/导入后退出")
    parser.add_argument("--no-ingest-worker", action="store_true", help="不在Web进程内启动数据导入Worker")
    parser.add_argument("--dataease-proxy-bind", default=os.getenv("DATAEASE_PROXY_BIND"), help="DataEase嵌入代理监听地址，默认与Web服务一致")
    parser.add_argument("--dataease-proxy-port", type=int, default=int(os.getenv("DATAEASE_PROXY_PORT", "8101")))
    parser.add_argument("--no-dataease-proxy", action="store_true", help="不启动DataEase嵌入代理（看板将不可嵌入）")
    parser.add_argument("--init-super-admin", action="store_true", help="通过环境变量安全创建初始超级管理员后退出")
    return parser


def main() -> int:
    load_project_env()
    args = build_parser().parse_args()
    database = Database(host=args.host, port=args.pg_port, dbname=args.dbname, user=args.user, password=args.password, upload_dir=UPLOAD_DIR)
    influencer_args = argparse.Namespace(
        host=args.host,
        port=args.pg_port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    influencer_module = InfluencerModule(influencer_args)
    file_ingest_module = FileIngestModule(influencer_args)
    automation_module = AutomationCenterModule(influencer_args, file_ingest_service=file_ingest_module.service)
    identity_module = IdentityAccessModule(database)
    ai_module = AiManagementModule(database, identity_module.auth)
    dataease_proxy = None if args.no_dataease_proxy else DataEaseEmbedProxy(
        os.getenv("DATAEASE_BASE_URL", "http://192.168.77.111:8100"),
        bind=args.dataease_proxy_bind or args.bind,
        port=args.dataease_proxy_port,
        public_url=os.getenv("DATAEASE_PROXY_PUBLIC_URL"),
        public_origins=os.getenv("DATAEASE_PUBLIC_ORIGINS", ""),
    )
    dashboard_module = DashboardModule(database, dataease_proxy)
    database.bank_refresh_enqueuer = file_ingest_module.service.enqueue_bank_refresh
    if args.migrate:
        print("已执行SQL：", *database.migrate(), *identity_module.migrate(), *dashboard_module.migrate(),
              *ai_module.migrate(), influencer_module.migrate(), *file_ingest_module.migrate(),
              *automation_module.migrate(), sep="\n- ")
    if args.init_super_admin:
        username = os.getenv("INITIAL_ADMIN_USERNAME", "")
        password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
        display_name = os.getenv("INITIAL_ADMIN_DISPLAY_NAME", "超级管理员")
        if not username or not password:
            raise SystemExit("必须设置INITIAL_ADMIN_USERNAME和INITIAL_ADMIN_PASSWORD环境变量")
        result = identity_module.auth.initialize_super_admin(username, password, display_name)
        print(json.dumps(result, ensure_ascii=False, default=json_default, indent=2))
        influencer_module.close(drain=False)
        ai_module.close()
        return 0
    if args.import_file:
        result = database.import_workbook(args.import_file, original_name=Path(args.import_file).name, operator=args.operator, ip_address="127.0.0.1")
        print(json.dumps(result, ensure_ascii=False, default=json_default, indent=2))
    if args.no_serve:
        influencer_module.close(drain=False)
        ai_module.close()
        return 0
    try:
        server = ExclusiveThreadingHTTPServer((args.bind, args.port), ApplicationHandler)
    except OSError as exc:
        influencer_module.close(drain=False)
        ai_module.close()
        print(
            f"启动失败：http://{args.bind}:{args.port} 已被其他后端进程占用。"
            "请先停止旧进程，确认端口只剩一个监听实例后再启动。",
            file=sys.stderr,
        )
        return 2
    server.database = database  # type: ignore[attr-defined]
    server.influencer_module = influencer_module  # type: ignore[attr-defined]
    server.file_ingest_module = file_ingest_module  # type: ignore[attr-defined]
    server.identity_module = identity_module  # type: ignore[attr-defined]
    server.dashboard_module = dashboard_module  # type: ignore[attr-defined]
    server.ai_module = ai_module  # type: ignore[attr-defined]
    server.automation_module = automation_module  # type: ignore[attr-defined]
    server.health_service = HealthAggregator(  # type: ignore[attr-defined]
        database, influencer_module, file_ingest_module, dataease_proxy,
        application_version=APP_VERSION, features=APP_FEATURES,
        automation_module=automation_module,
    )
    worker_stop = threading.Event()
    ingest_worker = None
    worker_thread = None
    if dataease_proxy:
        try:
            dataease_proxy.start()
        except OSError as exc:
            influencer_module.close(drain=False)
            ai_module.close()
            server.server_close()
            print(
                f"启动失败：DataEase嵌入代理端口 {dataease_proxy.bind}:{dataease_proxy.port} 不可用：{exc}",
                file=sys.stderr,
            )
            return 2
    if not args.no_ingest_worker:
        ingest_worker = FileIngestWorker(file_ingest_module.service, worker_name="embedded-web")

        def run_ingest_worker() -> None:
            ingest_worker.recover_stale()
            while not worker_stop.is_set():
                try:
                    worked = ingest_worker.run_once()
                except Exception as exc:
                    print(f"数据导入Worker异常：{exc!r}", file=sys.stderr)
                    worker_stop.wait(5)
                    continue
                if not worked:
                    worker_stop.wait(2)

        worker_thread = threading.Thread(target=run_ingest_worker, name="file-ingest-worker", daemon=True)
        worker_thread.start()
    print(f"经营配置中心：http://{args.bind}:{args.port}")
    print(f"达播运营配置台：http://{args.bind}:{args.port}/influencer/")
    print(f"数据导入中心：http://{args.bind}:{args.port}/ingest/")
    print(f"自动化工作台：http://{args.bind}:{args.port}/automation/")
    print(f"AI 数据分析：http://{args.bind}:{args.port}/ai/")
    print(f"数据导入Worker：{'已内置启动' if worker_thread else '未启动'}")
    print("ETL定时配置：由 Automation Workbench 管理")
    print(f"DataEase嵌入代理：{f'http://{dataease_proxy.bind}:{dataease_proxy.port}' if dataease_proxy else '未启动'}")
    print(f"数据库：{args.dbname}@{args.host}:{args.pg_port}")
    print("安全提示：默认仅监听本机；对外提供服务时请启用HTTPS并设置AUTH_COOKIE_SECURE=true。")
    ai_module.feishu.start_daily_report_scheduler()
    if os.getenv("FEISHU_AI_LONG_CONNECTION_ENABLED", "true").lower() != "false":
        ai_module.feishu.start_long_connections()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker_stop.set()
        if ingest_worker:
            ingest_worker.stop()
        if worker_thread:
            worker_thread.join(timeout=5)
        if dataease_proxy:
            dataease_proxy.stop()
        influencer_module.close(drain=True, timeout=30)
        ai_module.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
