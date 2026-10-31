from __future__ import annotations

import os
import uuid
from urllib.parse import urlparse

from apps.identity_access.audit import write_audit
from apps.identity_access.authorization import AuthorizationError
from apps.identity_access.security import validate_code
from apps.identity_access.validation import boolean, paging, text


class DashboardService:
    ICONS = {"dashboard", "chart", "trend", "report"}
    GENERATED_CODE_PREFIX = "dashboard_"

    def __init__(self, database):
        self.database = database
        allowed = os.getenv("DATAEASE_PUBLIC_ORIGINS", "http://192.168.77.111:8100")
        self.allowed_origins = {origin.strip().rstrip("/") for origin in allowed.split(",") if origin.strip()}

    def validate_url(self, value: object) -> str:
        url = str(value or "").strip()
        if len(url) > 500:
            raise ValueError("看板分享链接不能超过500字符")
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if parsed.scheme not in {"http", "https"} or origin not in self.allowed_origins:
            raise ValueError("仅允许配置指定DataEase服务地址下的公共分享链接")
        if parsed.path not in {"", "/"} or not parsed.fragment.startswith("/de-link/") or len(parsed.fragment.removeprefix("/de-link/")) < 4:
            raise ValueError("DataEase公共链接格式必须为/#/de-link/分享编码")
        return url

    def permitted(self, context) -> dict:
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT d.dashboard_id,d.dashboard_code,d.dashboard_name,d.dashboard_description,d.share_url,
                          d.icon_name,d.display_order,d.allow_fullscreen
                   FROM config.dashboard d JOIN iam.permission_resource pr ON pr.resource_id=d.permission_resource_id
                   WHERE d.deleted_at IS NULL AND d.is_active AND pr.is_active
                   ORDER BY d.display_order,d.dashboard_id"""
            )
            items = [dict(row) for row in cursor.fetchall() if context.can(f"dashboard.view.{row['dashboard_code']}")]
            return {"items": items}

    def detail(self, context, code: str) -> dict:
        code = validate_code(code, "看板编码")
        if not context.can(f"dashboard.view.{code}"):
            raise AuthorizationError("无权查看该看板")
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT dashboard_id,dashboard_code,dashboard_name,dashboard_description,share_url,
                          icon_name,display_order,allow_fullscreen
                   FROM config.dashboard WHERE dashboard_code=%s AND is_active AND deleted_at IS NULL""", (code,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("看板不存在或已停用")
            return dict(row)

    @staticmethod
    def require_manage(context) -> None:
        if not context.can("system.dashboard.manage"):
            raise AuthorizationError("无权管理看板")

    @staticmethod
    def _dashboard_has_slug_column(cursor) -> bool:
        """Detect the optional multi-dashboard schema extension.

        The legacy service can run against databases upgraded by the React
        dashboard experiment.  That schema adds a NOT-EMPTY ``dashboard_slug``
        check, while the legacy table has no such column.  The slug is not a
        separate input for a DataEase dashboard, so new legacy rows use their
        validated dashboard code as the stable slug when the extension exists.
        """

        cursor.execute(
            """SELECT EXISTS(
                       SELECT 1
                       FROM information_schema.columns
                       WHERE table_schema='config'
                         AND table_name='dashboard'
                         AND column_name='dashboard_slug'
                   ) AS has_dashboard_slug"""
        )
        row = cursor.fetchone()
        return bool(row and row["has_dashboard_slug"])

    @classmethod
    def _generated_dashboard_code(cls, cursor) -> str:
        """Generate a unique opaque code for a newly created dashboard."""

        for _ in range(5):
            code = f"{cls.GENERATED_CODE_PREFIX}{uuid.uuid4().hex}"
            permission_code = f"dashboard.view.{code}"
            cursor.execute(
                """
                SELECT 1 FROM config.dashboard WHERE dashboard_code=%s
                UNION ALL
                SELECT 1 FROM iam.permission_resource WHERE resource_code=%s
                LIMIT 1
                """,
                (code, permission_code),
            )
            if not cursor.fetchone():
                return code
        raise RuntimeError("系统无法生成唯一的看板编码，请稍后重试")

    def list_admin(self, context, query: dict[str, str]) -> dict:
        self.require_manage(context)
        page, size, offset = paging(query)
        keyword = query.get("keyword", "").strip()
        status = query.get("is_active")
        conditions = ["d.deleted_at IS NULL", "(%s='' OR d.dashboard_code ILIKE %s OR d.dashboard_name ILIKE %s)"]
        params: list = [keyword, f"%{keyword}%", f"%{keyword}%"]
        if status in {"true", "false"}:
            conditions.append("d.is_active=%s"); params.append(status == "true")
        where = " AND ".join(conditions)
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM config.dashboard d WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT d.dashboard_id,d.dashboard_code,d.dashboard_name,d.dashboard_description,d.share_url,
                           d.icon_name,d.display_order,d.allow_fullscreen,d.is_active,d.created_at,d.updated_at
                    FROM config.dashboard d WHERE {where}
                    ORDER BY d.display_order,d.dashboard_id LIMIT %s OFFSET %s""", params + [size, offset])
            return {"items": [dict(row) for row in cursor.fetchall()], "total": total, "page": page, "page_size": size}

    def save(self, context, payload: dict, dashboard_id: int | None, *, ip_address: str, user_agent: str) -> dict:
        self.require_manage(context)
        name = text(payload.get("dashboard_name"), "看板名称", maximum=100)
        description = str(payload.get("dashboard_description") or "").strip()[:500]
        share_url = self.validate_url(payload.get("share_url"))
        icon = str(payload.get("icon_name") or "dashboard").strip()
        if icon not in self.ICONS:
            raise ValueError("看板图标不在允许集合中")
        order = max(0, int(payload.get("display_order", 0)))
        fullscreen = boolean(payload.get("allow_fullscreen", True), "全屏开关")
        active = boolean(payload.get("is_active", True), "启用状态")
        with self.database.transaction() as cursor:
            has_dashboard_slug = self._dashboard_has_slug_column(cursor) if dashboard_id is None else False
            if dashboard_id is None:
                code = self._generated_dashboard_code(cursor)
                permission_code = f"dashboard.view.{code}"
                cursor.execute("SELECT resource_id FROM iam.permission_resource WHERE resource_code='module.dashboard'")
                module = cursor.fetchone()
                cursor.execute(
                    """INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order)
                       VALUES (%s,%s,'dashboard','dashboard',%s,%s,%s) RETURNING resource_id""",
                    (permission_code, f"查看{name}", module["resource_id"], f"/dashboards/?code={code}", order),
                )
                resource_id = cursor.fetchone()["resource_id"]
                if has_dashboard_slug:
                    cursor.execute(
                        """INSERT INTO config.dashboard(
                                  dashboard_code,dashboard_name,dashboard_description,share_url,icon_name,dashboard_slug,
                                  display_order,allow_fullscreen,is_active,permission_resource_id,created_by,updated_by)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (code, name, description, share_url, icon, code, order, fullscreen, active,
                         resource_id, context.user_id, context.user_id),
                    )
                else:
                    cursor.execute(
                        """INSERT INTO config.dashboard(dashboard_code,dashboard_name,dashboard_description,share_url,icon_name,
                                                          display_order,allow_fullscreen,is_active,permission_resource_id,created_by,updated_by)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (code, name, description, share_url, icon, order, fullscreen, active, resource_id, context.user_id, context.user_id),
                    )
                before = None; action = "dashboard.create"
            else:
                cursor.execute("SELECT * FROM config.dashboard WHERE dashboard_id=%s AND deleted_at IS NULL FOR UPDATE", (dashboard_id,))
                old = cursor.fetchone()
                if not old:
                    raise ValueError("看板不存在")
                before = dict(old); action = "dashboard.update"
                cursor.execute(
                    """UPDATE config.dashboard SET dashboard_name=%s,dashboard_description=%s,
                              share_url=%s,icon_name=%s,display_order=%s,allow_fullscreen=%s,is_active=%s,
                              updated_by=%s,updated_at=NOW() WHERE dashboard_id=%s RETURNING *""",
                    (name, description, share_url, icon, order, fullscreen, active, context.user_id, dashboard_id),
                )
                row = dict(cursor.fetchone())
                cursor.execute(
                    """UPDATE iam.permission_resource SET resource_name=%s,display_order=%s,
                              is_active=%s,updated_at=NOW() WHERE resource_id=%s""",
                    (f"查看{name}", order, active, old["permission_resource_id"]),
                )
            if dashboard_id is None:
                row = dict(cursor.fetchone())
            write_audit(cursor, action=action, target_type="dashboard", target_id=row["dashboard_id"], actor=context,
                        before=before, after=row, ip_address=ip_address, user_agent=user_agent)
            return row

    def delete(self, context, dashboard_id: int, *, ip_address: str, user_agent: str) -> None:
        self.require_manage(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM config.dashboard WHERE dashboard_id=%s AND deleted_at IS NULL FOR UPDATE", (dashboard_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("看板不存在")
            cursor.execute("UPDATE config.dashboard SET deleted_at=NOW(),is_active=FALSE,updated_by=%s,updated_at=NOW() WHERE dashboard_id=%s", (context.user_id, dashboard_id))
            cursor.execute("UPDATE iam.permission_resource SET is_active=FALSE,updated_at=NOW() WHERE resource_id=%s", (row["permission_resource_id"],))
            write_audit(cursor, action="dashboard.delete", target_type="dashboard", target_id=dashboard_id, actor=context,
                        before=dict(row), after={"deleted": True}, ip_address=ip_address, user_agent=user_agent)

    def access_holders(self, context, dashboard_id: int) -> dict:
        self.require_manage(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT permission_resource_id FROM config.dashboard WHERE dashboard_id=%s AND deleted_at IS NULL", (dashboard_id,))
            dashboard = cursor.fetchone()
            if not dashboard:
                raise ValueError("看板不存在")
            resource_id = dashboard["permission_resource_id"]
            cursor.execute("SELECT r.role_id,r.role_name FROM iam.role_permission p JOIN iam.role r ON r.role_id=p.role_id WHERE p.resource_id=%s AND r.deleted_at IS NULL", (resource_id,))
            roles = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT d.department_id,d.department_name FROM iam.department_permission p JOIN iam.department d ON d.department_id=p.department_id WHERE p.resource_id=%s AND d.deleted_at IS NULL", (resource_id,))
            departments = [dict(row) for row in cursor.fetchall()]
            cursor.execute("SELECT u.user_id,u.display_name,p.permission_effect FROM iam.user_permission p JOIN iam.user_account u ON u.user_id=p.user_id WHERE p.resource_id=%s AND u.deleted_at IS NULL", (resource_id,))
            users = [dict(row) for row in cursor.fetchall()]
            return {"roles": roles, "departments": departments, "users": users}
