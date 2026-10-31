from __future__ import annotations

import hmac
import os
import re
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from urllib.parse import parse_qs, unquote

from apps.identity_access.authorization import (
    FINANCE_ACTION_PERMISSIONS,
    FINANCE_ACTION_PAGE_PERMISSIONS,
    FINANCE_PAGE_PERMISSIONS,
    FINANCE_READ_PERMISSIONS,
    FINANCE_RESOURCE_ACTIONS,
    AuthorizationError,
)
from .service import MAX_UPLOAD_BYTES, FileIngestService


APP_DIR = Path(__file__).resolve().parent


def query_values(query_string: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(query_string).items()}


class FileIngestModule:
    page_prefix = "/ingest"
    api_prefixes = ("/api/ingest", "/api/etl")

    def __init__(self, args):
        self.service = FileIngestService(args)
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
    def _is_api(path: str) -> bool:
        return any(path == prefix or path.startswith(prefix + "/") for prefix in FileIngestModule.api_prefixes)

    def require_robot_token(self, headers, *, source: str) -> None:
        if source == 'manual' and headers.get('Authorization','').lower().startswith('bearer '):
            raise PermissionError('人工会话需要用户登录与权限，不能通过自动化Bearer访问')
        if source not in {"api", "robot"}:
            return
        expected = os.getenv("INGEST_ROBOT_TOKEN", "")
        if not expected:
            raise PermissionError("服务端未配置INGEST_ROBOT_TOKEN")
        authorization = headers.get("Authorization", "")
        supplied = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise PermissionError("API Bearer Token无效")

    @staticmethod
    def _require_finance_read(context, resource: str) -> None:
        permissions = FINANCE_READ_PERMISSIONS.get(resource)
        if permissions is None:
            raise ValueError("经营配置类型不存在")
        if context is None or not any(context.can(permission) for permission in permissions):
            raise AuthorizationError("缺少经营配置页面权限")

    @staticmethod
    def _require_finance_write(context, resource: str, action: str | None) -> None:
        if action not in FINANCE_RESOURCE_ACTIONS.get(resource, ()):
            raise ValueError("经营配置操作无效")
        page_key = FINANCE_ACTION_PAGE_PERMISSIONS[action]
        page_permission = FINANCE_PAGE_PERMISSIONS[page_key]
        if context is None or not context.can(page_permission):
            raise AuthorizationError(f"缺少经营配置页面权限：{page_permission}")
        permission = FINANCE_ACTION_PERMISSIONS[action]
        if context is None or not context.can(permission):
            raise AuthorizationError(f"缺少权限：{permission}")

    @staticmethod
    def read_multipart(headers, stream) -> tuple[str, bytes, dict]:
        content_type = headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("文件上传必须使用multipart/form-data")
        length = int(headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_UPLOAD_BYTES + 2 * 1024 * 1024:
            raise ValueError("上传请求为空或超过大小限制")
        message = BytesParser(policy=default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + stream.read(length)
        )
        fields: dict[str, str] = {}
        filename = ""
        content = b""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                filename = Path(part.get_filename() or "").name
                content = part.get_payload(decode=True) or b""
            elif name:
                fields[name] = (part.get_payload(decode=True) or b"").decode("utf-8").strip()
        if not filename or not content:
            raise ValueError("未找到有效上传字段file")
        return filename, content, fields

    def upload(self, path: str, headers, stream, *, operator: str, ip_address: str | None) -> tuple[dict, int]:
        match = re.fullmatch(r"/api/ingest/runs/([^/]+)/files", path)
        if not match:
            raise ValueError("文件上传接口不存在")
        filename, content, fields = self.read_multipart(headers, stream)
        source = self.service.run_source(match.group(1))
        self.require_robot_token(headers, source=source)
        request_key = (headers.get("Idempotency-Key") or "").strip()
        if source in {"api", "robot"} and not request_key:
            raise ValueError("API上传必须携带Idempotency-Key")
        if request_key and fields.get("client_file_id") and request_key != fields["client_file_id"]:
            raise ValueError("Idempotency-Key必须与client_file_id一致")
        if request_key:
            fields["client_file_id"] = request_key
        return self.service.save_upload(
            match.group(1), filename=filename, content=content, metadata=fields,
            operator=operator, ip_address=ip_address,
        ), 201

    def dispatch(
        self,
        method: str,
        path: str,
        query_string: str = "",
        payload: dict | None = None,
        *,
        context=None,
        operator: str = "财务用户",
        ip_address: str | None = None,
        headers=None,
    ) -> tuple[dict, int] | None:
        if not self._is_api(path):
            return None
        query = query_values(query_string)
        payload = payload or {}
        headers = headers or {}

        if method == "GET":
            if path == "/api/ingest/health":
                return self.service.health(), 200
            if path == "/api/ingest/report-types":
                return self.service.list_reports(), 200
            if path == "/api/ingest/shops":
                return {"items": self.service.list_shops(query.get("platform_code"))}, 200
            if path == "/api/ingest/guess":
                return self.service.guess(query.get("filename", "")), 200
            if path == "/api/ingest/runs":
                return self.service.list_runs(
                    int(query.get("page", 1)),
                    int(query.get("page_size", query.get("limit", 10))),
                    operator,
                    query,
                ), 200
            match = re.fullmatch(r"/api/ingest/runs/([^/]+)", path)
            if match:
                return self.service.run_detail(match.group(1)), 200
            match = re.fullmatch(r'/api/ingest/file-tasks/([^/]+)/review-context', path)
            if match:
                return self.service.file_review_context(match.group(1)),200
            if path == "/api/ingest/fee-categories":
                return self.service.list_fee_categories(query), 200
            if path == "/api/ingest/fee-mappings":
                return self.service.list_fee_mappings(query), 200
            if path == '/api/ingest/fee-mappings/scene-rules':
                return self.service.list_scene_rules(),200
            if path == "/api/ingest/operating-details":
                if context is None or not context.can("platform_fee.raw.view"):
                    raise AuthorizationError("缺少全部收支明细查看权限")
                return self.service.list_operating_details(query), 200
            match=re.fullmatch(r'/api/ingest/fee-mappings/(\d+)/source',path)
            if match:
                return self.service.fee_mapping_source(int(match.group(1))),200
            if path == "/api/ingest/finance-config/summary":
                self._require_finance_read(context, "summary")
                return self.service.finance_configuration_summary(query), 200
            match = re.fullmatch(
                r"/api/ingest/finance-config/(budgets|shop-plans|gsv-targets|shop-budgets|recharges|adjustments|promotion-spend|marketing-expenses|marketing-budget-history|expense-types)",
                path,
            )
            if match:
                self._require_finance_read(context, match.group(1))
                return self.service.list_finance_configuration(match.group(1), query), 200
            if path == "/api/ingest/operation-logs":
                return self.service.list_operation_logs(
                    int(query.get("page", 1)),
                    int(query.get("page_size", query.get("limit", 10))),
                    query,
                ), 200
            if path == "/api/etl/runs":
                return self.service.list_etl_runs(int(query.get("page", 1)), int(query.get("page_size", query.get("limit", 10))), query), 200
            match = re.fullmatch(r"/api/etl/runs/([^/]+)", path)
            if match:
                return self.service.etl_detail(match.group(1)), 200

        if method == "POST":
            if path == '/api/ingest/fee-mappings/scene-rules/preview':
                return self.service.preview_scene_rule(payload),200
            if path == '/api/ingest/fee-mappings/scene-rules':
                return self.service.save_scene_rule(payload,operator,ip_address),200
            if path == "/api/ingest/runs":
                source = str(payload.get("source") or "manual").strip().lower()
                if context is None and headers.get('Authorization','').lower().startswith('bearer ') and source=='manual':
                    raise PermissionError('终端人工上传请使用用户登录会话；自动化Bearer仅能创建api或robot会话')
                self.require_robot_token(headers, source=source)
                idempotency = headers.get("Idempotency-Key") or payload.get("idempotency_key")
                return self.service.create_run({**payload, "idempotency_key": idempotency}, operator, source), 201
            match = re.fullmatch(r"/api/ingest/runs/([^/]+)/complete", path)
            if match:
                source = self.service.run_source(match.group(1))
                self.require_robot_token(headers, source=source)
                return self.service.complete_run(match.group(1), operator, ip_address, payload=payload), 200
            match = re.fullmatch(r'/api/ingest/runs/([^/]+)/coverage-preflight', path)
            if match:
                self.require_robot_token(headers, source=self.service.run_source(match.group(1)))
                if context is None and payload.get('import_mode') == 'replace_range':
                    raise PermissionError('范围替换需要已登录用户的人工操作权限')
                return self.service.coverage_preflight(match.group(1),payload,operator), 200
            match = re.fullmatch(r'/api/ingest/runs/([^/]+)/reuse', path)
            if match:
                if context is None:
                    raise PermissionError('复用文件需要人工用户登录和上传权限')
                return self.service.reuse_run_files(match.group(1),payload,operator,ip_address),201
            match = re.fullmatch(r'/api/ingest/runs/([^/]+)/(resume|draft)', path)
            if match:
                if context is None:
                    raise PermissionError('继续或保存草稿需要已登录用户的上传权限')
                if match.group(2)=='resume':
                    return self.service.resume_run(match.group(1),operator,ip_address),200
                return self.service.save_run_draft(match.group(1),payload,operator,ip_address),200
            match = re.fullmatch(r"/api/ingest/runs/([^/]+)/fail", path)
            if match:
                source = self.service.run_source(match.group(1))
                self.require_robot_token(headers, source=source)
                return self.service.fail_run(
                    match.group(1), operator, ip_address,
                    str(payload.get("message") or "文件上传未完成"),
                ), 200
            match = re.fullmatch(r"/api/ingest/file-tasks/([^/]+)/retry", path)
            if match:
                return self.service.retry_file(match.group(1), operator, ip_address), 200
            if path == "/api/etl/runs":
                return self.service.create_manual_etl(payload, operator), 201
            match = re.fullmatch(r"/api/etl/tasks/([^/]+)/retry", path)
            if match:
                return self.service.retry_etl_task(match.group(1), operator, ip_address,
                    snapshot_policy=str(payload.get('snapshot_policy') or 'latest'),
                    confirm_replay_publish=payload.get('confirm_replay_publish') is True), 200
            if path == "/api/ingest/fee-mappings/assign":
                return self.service.assign_fee_mappings(payload, operator, ip_address), 200
            if path == "/api/ingest/fee-mappings/preview":
                return self.service.preview_fee_mappings(payload),200
            if path == "/api/ingest/fee-categories":
                return self.service.create_fee_category(payload, operator, ip_address), 201
            match = re.fullmatch(
                r"/api/ingest/finance-config/(budgets|shop-plans|gsv-targets|shop-budgets|recharges|marketing-expenses|expense-types)",
                path,
            )
            if match:
                resource = match.group(1)
                action = "expense_type" if resource == "expense-types" else str(payload.get("permission_action") or "")
                self._require_finance_write(context, resource, action)
                return self.service.save_finance_configuration(resource, payload, operator, ip_address), 201

        if method == "PUT":
            match = re.fullmatch(r"/api/ingest/fee-categories/([A-Za-z][A-Za-z0-9_]{1,63})", path)
            if match:
                return self.service.update_fee_category(
                    match.group(1), payload, operator, ip_address,
                ), 200
            match = re.fullmatch(r"/api/ingest/fee-mappings/(\d+)/status", path)
            if match:
                return self.service.set_fee_mapping_status(
                    int(match.group(1)), bool(payload.get("is_active")), payload.get("updated_at"),
                    operator, ip_address,
                ), 200
            match = re.fullmatch(
                r"/api/ingest/finance-config/(budgets|shop-plans|gsv-targets|shop-budgets|recharges|marketing-expenses|expense-types)/([^/]+)",
                path,
            )
            if match:
                resource = match.group(1)
                action = "expense_type" if resource == "expense-types" else str(payload.get("permission_action") or "")
                self._require_finance_write(context, resource, action)
                return self.service.save_finance_configuration(resource, payload, operator, ip_address, match.group(2)), 200

        if method == "DELETE":
            match = re.fullmatch(r"/api/ingest/runs/([^/]+)", path)
            if match:
                source = self.service.run_source(match.group(1))
                self.require_robot_token(headers, source=source)
                return self.service.delete_run(match.group(1), operator, ip_address), 200
            match = re.fullmatch(r"/api/ingest/fee-categories/([A-Za-z][A-Za-z0-9_]{1,63})", path)
            if match:
                return self.service.delete_fee_category(match.group(1), operator, ip_address), 200
            match = re.fullmatch(r"/api/ingest/fee-mappings/(\d+)", path)
            if match:
                return self.service.delete_fee_mapping(int(match.group(1)), operator, ip_address), 200
            match = re.fullmatch(r"/api/ingest/finance-config/(shop-plans|recharges|marketing-expenses|expense-types)/(\d+)", path)
            if match:
                resource = match.group(1)
                action = "expense_type" if resource == "expense-types" else query.get("permission_action")
                self._require_finance_write(context, resource, action)
                return self.service.delete_finance_configuration(match.group(1), match.group(2), operator, ip_address), 200

        return None
