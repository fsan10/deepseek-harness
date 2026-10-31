from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from .auth_service import AuthService
from .authorization import AuthorizationError
from .organization_service import OrganizationService
from .password_cipher import UserPasswordCipher
from .platform_shop_company_service import PlatformShopCompanyService
from .permission_service import PermissionService
from .role_service import RoleService
from .user_service import UserService
from .validation import paging


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
SQL_FILES = [
    PROJECT_ROOT / "sql/common/370_iam_core_postgres.sql",
    PROJECT_ROOT / "sql/common/424_iam_user_password_view_postgres.sql",
]


@dataclass(slots=True)
class ModuleResponse:
    data: object = None
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class IdentityAccessModule:
    page_prefixes = ("/login", "/system")
    api_prefix = "/api"

    def __init__(self, database):
        self.database = database
        password_cipher = UserPasswordCipher()
        self.auth = AuthService(database, password_cipher)
        self.users = UserService(database, password_cipher)
        self.departments = OrganizationService(database)
        self.platform_shop_companies = PlatformShopCompanyService(database)
        self.roles = RoleService(database)
        self.permissions = PermissionService(database, self.auth)
        self.static_dir = APP_DIR / "static"

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self.database.transaction() as cursor:
            for path in SQL_FILES:
                cursor.execute(path.read_text(encoding="utf-8"))
                applied.append(str(path.relative_to(PROJECT_ROOT)))
        return applied

    def static_file(self, request_path: str) -> Path | None:
        if request_path.startswith("/login"):
            relative = request_path.removeprefix("/login").lstrip("/") or "login.html"
        elif request_path.startswith("/welcome"):
            relative = request_path.removeprefix("/welcome").lstrip("/") or "welcome.html"
        elif request_path.startswith("/system"):
            relative = request_path.removeprefix("/system").lstrip("/") or "system.html"
        elif request_path.startswith("/identity-assets/"):
            relative = request_path.removeprefix("/identity-assets/")
        else:
            return None
        target = (self.static_dir / unquote(relative)).resolve()
        root = self.static_dir.resolve()
        if target != root and root not in target.parents:
            return None
        return target if target.is_file() else None

    @staticmethod
    def _require(context):
        if context is None:
            raise AuthorizationError("缺少登录上下文")
        return context

    def _audit_list(self, context, query: dict[str, str]) -> dict:
        if not context.can("system.audit.view"):
            raise AuthorizationError("无权查看审计日志")
        page, size, offset = paging(query)
        keyword = query.get("keyword", "").strip()
        date_from = query.get("date_from", "").strip()
        date_to = query.get("date_to", "").strip()
        for value, label in ((date_from, "开始日期"), (date_to, "结束日期")):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
        date_filters = "".join([
            " AND (a.created_at AT TIME ZONE 'Asia/Shanghai')::date >= %s" if date_from else "",
            " AND (a.created_at AT TIME ZONE 'Asia/Shanghai')::date <= %s" if date_to else "",
        ])
        with self.database.transaction() as cursor:
            params = [keyword, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", date_from, date_to]
            params = params[:4] + [value for value in (date_from, date_to) if value]
            where = f"(%s='' OR COALESCE(NULLIF(BTRIM(u.display_name),''),NULLIF(BTRIM(a.username),''),'') ILIKE %s OR a.action_code ILIKE %s OR a.target_id ILIKE %s){date_filters}"
            join = "LEFT JOIN iam.user_account u ON u.user_id=a.user_id"
            cursor.execute(f"SELECT COUNT(*) AS total FROM iam.audit_log a {join} WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT a.audit_log_id,a.user_id,a.username,a.action_code,a.target_type,a.target_id,
                           COALESCE(NULLIF(BTRIM(u.display_name),''),NULLIF(BTRIM(a.username),''),'匿名') AS display_name,
                           a.change_before,a.change_after,a.ip_address,a.created_at
                    FROM iam.audit_log a {join} WHERE {where} ORDER BY a.created_at DESC LIMIT %s OFFSET %s""",
                params + [size, offset],
            )
            return {"items": [dict(row) for row in cursor.fetchall()], "total": total, "page": page, "page_size": size}

    def dispatch(self, method: str, path: str, query: dict[str, str], payload: dict | None, *,
                 context=None, ip_address: str = "", user_agent: str = "") -> ModuleResponse | None:
        payload = payload or {}
        if path == "/api/auth/login" and method == "POST":
            data, session_token = self.auth.login(payload, ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse(data, 200, {"Set-Cookie": [
                self.auth.cookie_header(session_token), self.auth.csrf_cookie_header(data["csrf_token"]),
            ]})
        if not (path.startswith("/api/auth/") or path.startswith("/api/system/")):
            return None
        context = self._require(context)
        if path == "/api/auth/me" and method == "GET":
            return ModuleResponse({"user": context.public_user(), "permissions": sorted(context.permissions),
                                   "permission_sources": context.permission_sources})
        if path == "/api/auth/logout" and method == "POST":
            self.auth.logout(context, ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"logged_out": True}, headers={"Set-Cookie": [
                self.auth.cookie_header("", clear=True), self.auth.csrf_cookie_header("", clear=True),
            ]})
        if path == "/api/auth/change-password" and method == "POST":
            self.auth.change_password(context, payload, ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"changed": True})

        if path == "/api/system/platform-shop-companies" and method == "GET":
            return ModuleResponse(self.platform_shop_companies.list(context, query))
        if path == "/api/system/platform-shop-companies" and method == "POST":
            return ModuleResponse(self.platform_shop_companies.create(
                context, payload, ip_address=ip_address, user_agent=user_agent,
            ), 201)
        match = re.fullmatch(r"/api/system/platform-shop-companies/(\d+)", path)
        if match and method == "PUT":
            return ModuleResponse(self.platform_shop_companies.update(
                context, int(match.group(1)), payload,
                ip_address=ip_address, user_agent=user_agent,
            ))
        if match and method == "DELETE":
            return ModuleResponse(self.platform_shop_companies.expire(
                context, int(match.group(1)), ip_address=ip_address, user_agent=user_agent,
            ))

        if path == "/api/system/users" and method == "GET":
            return ModuleResponse(self.users.list(context, query))
        if path == "/api/system/users" and method == "POST":
            return ModuleResponse(self.users.create(context, payload, ip_address=ip_address, user_agent=user_agent), 201)
        match = re.fullmatch(r"/api/system/users/(\d+)", path)
        if match and method == "PUT":
            return ModuleResponse(self.users.update(context, int(match.group(1)), payload, ip_address=ip_address, user_agent=user_agent))
        match = re.fullmatch(r"/api/system/users/(\d+)/reset-password", path)
        if match and method == "POST":
            self.users.reset_password(context, int(match.group(1)), payload, ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"reset": True})
        match = re.fullmatch(r"/api/system/users/(\d+)/password", path)
        if match and method == "GET":
            return ModuleResponse(self.users.view_password(
                context, int(match.group(1)), ip_address=ip_address, user_agent=user_agent,
            ))
        match = re.fullmatch(r"/api/system/users/(\d+)/effective-permissions", path)
        if match and method == "GET":
            return ModuleResponse(self.permissions.effective_for_user(context, int(match.group(1))))

        if path == "/api/system/departments" and method == "GET":
            return ModuleResponse(self.departments.tree(context))
        if path == "/api/system/departments" and method == "POST":
            return ModuleResponse(self.departments.create(context, payload, ip_address=ip_address, user_agent=user_agent), 201)
        match = re.fullmatch(r"/api/system/departments/(\d+)", path)
        if match and method == "PUT":
            return ModuleResponse(self.departments.update(context, int(match.group(1)), payload, ip_address=ip_address, user_agent=user_agent))
        if match and method == "DELETE":
            self.departments.delete(context, int(match.group(1)), ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"deleted": True})

        if path == "/api/system/roles" and method == "GET":
            return ModuleResponse(self.roles.list(context, query))
        if path == "/api/system/roles" and method == "POST":
            return ModuleResponse(self.roles.save(context, payload, None, ip_address=ip_address, user_agent=user_agent), 201)
        match = re.fullmatch(r"/api/system/roles/(\d+)", path)
        if match and method == "PUT":
            return ModuleResponse(self.roles.save(context, payload, int(match.group(1)), ip_address=ip_address, user_agent=user_agent))
        if match and method == "DELETE":
            self.roles.delete(context, int(match.group(1)), ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"deleted": True})
        match = re.fullmatch(r"/api/system/roles/(\d+)/users", path)
        if match and method == "GET":
            return ModuleResponse(self.roles.users(context, int(match.group(1))))

        if path == "/api/system/permissions/resources" and method == "GET":
            return ModuleResponse(self.permissions.resources(context))
        match = re.fullmatch(r"/api/system/permissions/(role|department|user)/(\d+)", path)
        if match and method == "GET":
            return ModuleResponse(self.permissions.assignments(context, match.group(1), int(match.group(2))))
        if match and method == "PUT":
            return ModuleResponse(self.permissions.replace_assignments(
                context, match.group(1), int(match.group(2)), payload,
                ip_address=ip_address, user_agent=user_agent,
            ))
        if path == "/api/system/audit" and method == "GET":
            return ModuleResponse(self._audit_list(context, query))
        return ModuleResponse(None, 404)
