from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from apps.identity_access.module import ModuleResponse

from .proxy import DataEaseEmbedProxy
from .service import DashboardService


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
SQL_FILES = [
    PROJECT_ROOT / "sql/common/371_dashboard_config_postgres.sql",
    PROJECT_ROOT / "sql/common/372_seed_iam_permissions_and_dashboards_postgres.sql",
    PROJECT_ROOT / "sql/common/382_dashboard_origin_portability_postgres.sql",
    PROJECT_ROOT / "sql/common/420_platform_shop_company_admin_postgres.sql",
    PROJECT_ROOT / "sql/common/423_normalize_dashboard_codes_postgres.sql",
]


class DashboardModule:
    page_prefix = "/dashboards"

    def __init__(self, database, embed_proxy: DataEaseEmbedProxy | None = None):
        self.service = DashboardService(database)
        self.embed_proxy = embed_proxy
        self.static_dir = APP_DIR / "static"

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self.service.database.transaction() as cursor:
            for path in SQL_FILES:
                cursor.execute(path.read_text(encoding="utf-8"))
                applied.append(str(path.relative_to(PROJECT_ROOT)))
        return applied

    def static_file(self, request_path: str) -> Path | None:
        if request_path.startswith("/dashboard-assets/"):
            relative = request_path.removeprefix("/dashboard-assets/")
        elif request_path.startswith("/dashboards"):
            relative = request_path.removeprefix("/dashboards").lstrip("/") or "index.html"
        else:
            return None
        target = (self.static_dir / unquote(relative)).resolve()
        root = self.static_dir.resolve()
        if target != root and root not in target.parents:
            return None
        return target if target.is_file() else None

    def dispatch(self, method: str, path: str, query: dict[str, str], payload: dict | None, *, context,
                 ip_address: str = "", user_agent: str = "") -> ModuleResponse | None:
        payload = payload or {}
        if not path.startswith("/api/dashboards"):
            return None
        if path == "/api/dashboards" and method == "GET":
            return ModuleResponse(self.service.permitted(context))
        if path == "/api/dashboards/admin" and method == "GET":
            return ModuleResponse(self.service.list_admin(context, query))
        if path == "/api/dashboards/admin" and method == "POST":
            return ModuleResponse(self.service.save(context, payload, None, ip_address=ip_address, user_agent=user_agent), 201)
        match = re.fullmatch(r"/api/dashboards/admin/(\d+)", path)
        if match and method == "PUT":
            return ModuleResponse(self.service.save(context, payload, int(match.group(1)), ip_address=ip_address, user_agent=user_agent))
        if match and method == "DELETE":
            self.service.delete(context, int(match.group(1)), ip_address=ip_address, user_agent=user_agent)
            return ModuleResponse({"deleted": True})
        match = re.fullmatch(r"/api/dashboards/admin/(\d+)/access", path)
        if match and method == "GET":
            return ModuleResponse(self.service.access_holders(context, int(match.group(1))))
        if path == "/api/dashboards/admin/test" and method == "POST":
            return ModuleResponse({"valid": True, "share_url": self.service.validate_url(payload.get("share_url"))})
        match = re.fullmatch(r"/api/dashboards/([a-z][a-z0-9_]{1,63})", path)
        if match and method == "GET":
            dashboard = self.service.detail(context, match.group(1))
            if not self.embed_proxy:
                raise RuntimeError("DataEase嵌入代理未启动")
            dashboard["embed"] = self.embed_proxy.embed_location(dashboard["share_url"]).as_dict()
            return ModuleResponse(dashboard)
        return ModuleResponse(None, 404)
