from __future__ import annotations

from .audit import write_audit
from .authorization import AuthorizationError
from .security import validate_code
from .validation import boolean, paging, text


class RoleService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def require(context) -> None:
        if not context.can("system.role.manage"):
            raise AuthorizationError("无权管理角色")

    def list(self, context, query: dict[str, str]) -> dict:
        self.require(context)
        page, size, offset = paging(query)
        keyword = query.get("keyword", "").strip()
        status = query.get("is_active")
        conditions = ["r.deleted_at IS NULL", "(%s='' OR r.role_code ILIKE %s OR r.role_name ILIKE %s)"]
        params: list = [keyword, f"%{keyword}%", f"%{keyword}%"]
        if status in {"true", "false"}:
            conditions.append("r.is_active=%s"); params.append(status == "true")
        where = " AND ".join(conditions)
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM iam.role r WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT r.role_id,r.role_code,r.role_name,r.role_description,r.is_active,r.created_at,
                           COUNT(ur.user_id) AS user_count
                    FROM iam.role r LEFT JOIN iam.user_role ur ON ur.role_id=r.role_id
                    WHERE {where} GROUP BY r.role_id ORDER BY r.created_at DESC LIMIT %s OFFSET %s""",
                params + [size, offset],
            )
            return {"items": [dict(row) for row in cursor.fetchall()], "total": total, "page": page, "page_size": size}

    def save(self, context, payload: dict, role_id: int | None, *, ip_address: str, user_agent: str) -> dict:
        self.require(context)
        name = text(payload.get("role_name"), "角色名称", maximum=100)
        description = str(payload.get("role_description") or "").strip()[:500]
        active = boolean(payload.get("is_active", True), "启用状态")
        with self.database.transaction() as cursor:
            if role_id is None:
                code = validate_code(payload.get("role_code"), "角色编码")
                cursor.execute("INSERT INTO iam.role(role_code,role_name,role_description,is_active) VALUES (%s,%s,%s,%s) RETURNING *", (code, name, description, active))
                before = None; action = "role.create"
            else:
                cursor.execute("SELECT * FROM iam.role WHERE role_id=%s AND deleted_at IS NULL FOR UPDATE", (role_id,))
                before_row = cursor.fetchone()
                if not before_row:
                    raise ValueError("角色不存在")
                before = dict(before_row); action = "role.update"
                cursor.execute("UPDATE iam.role SET role_name=%s,role_description=%s,is_active=%s,updated_at=NOW() WHERE role_id=%s RETURNING *", (name, description, active, role_id))
            row = dict(cursor.fetchone())
            write_audit(cursor, action=action, target_type="role", target_id=row["role_id"], actor=context,
                        before=before, after=row, ip_address=ip_address, user_agent=user_agent)
            return row

    def delete(self, context, role_id: int, *, ip_address: str, user_agent: str) -> None:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT role_code,role_name FROM iam.role WHERE role_id=%s AND deleted_at IS NULL FOR UPDATE", (role_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("角色不存在")
            cursor.execute("SELECT COUNT(*) AS total FROM iam.user_role WHERE role_id=%s", (role_id,))
            if int(cursor.fetchone()["total"]):
                raise ValueError("角色仍有关联用户，不能删除")
            cursor.execute("UPDATE iam.role SET deleted_at=NOW(),is_active=FALSE,updated_at=NOW() WHERE role_id=%s", (role_id,))
            write_audit(cursor, action="role.delete", target_type="role", target_id=role_id, actor=context,
                        before=dict(row), after={"deleted": True}, ip_address=ip_address, user_agent=user_agent)

    def users(self, context, role_id: int) -> dict:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT u.user_id,u.username,u.display_name,u.is_active FROM iam.user_role ur
                              JOIN iam.user_account u ON u.user_id=ur.user_id AND u.deleted_at IS NULL
                              WHERE ur.role_id=%s ORDER BY u.display_name""", (role_id,))
            return {"items": [dict(row) for row in cursor.fetchall()]}

