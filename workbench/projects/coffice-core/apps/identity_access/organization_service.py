from __future__ import annotations

from .audit import write_audit
from .authorization import AuthorizationError
from .security import validate_code
from .validation import boolean, optional_int, text


class OrganizationService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def require(context) -> None:
        if not context.can("system.department.manage"):
            raise AuthorizationError("无权管理部门")

    def tree(self, context) -> dict:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute(
                """
                SELECT d.department_id,d.department_code,d.department_name,d.parent_department_id,
                       d.display_order,d.is_active,d.created_at,
                       COUNT(u.user_id) FILTER (WHERE u.is_active AND u.deleted_at IS NULL) AS active_user_count
                FROM iam.department d
                LEFT JOIN iam.user_account u ON u.department_id=d.department_id
                WHERE d.deleted_at IS NULL
                GROUP BY d.department_id ORDER BY d.display_order,d.department_name
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
        children: dict[int | None, list[dict]] = {}
        for row in rows:
            row["children"] = []
            children.setdefault(row["parent_department_id"], []).append(row)
        for row in rows:
            row["children"] = children.get(row["department_id"], [])
        return {"items": children.get(None, []), "flat_items": rows}

    def create(self, context, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require(context)
        code = validate_code(payload.get("department_code"), "部门编码")
        name = text(payload.get("department_name"), "部门名称", maximum=100)
        parent_id = optional_int(payload.get("parent_department_id"), "上级部门ID")
        order = max(0, int(payload.get("display_order", 0)))
        with self.database.transaction() as cursor:
            cursor.execute(
                """INSERT INTO iam.department(department_code,department_name,parent_department_id,display_order,is_active)
                   VALUES (%s,%s,%s,%s,TRUE) RETURNING department_id,department_code,department_name,parent_department_id,display_order,is_active""",
                (code, name, parent_id, order),
            )
            row = dict(cursor.fetchone())
            write_audit(cursor, action="department.create", target_type="department", target_id=row["department_id"],
                        actor=context, after=row, ip_address=ip_address, user_agent=user_agent)
            return row

    @staticmethod
    def _validate_parent(cursor, department_id: int, parent_id: int | None) -> None:
        if parent_id is None:
            return
        if parent_id == department_id:
            raise ValueError("部门不能设置自身为上级")
        cursor.execute(
            """
            WITH RECURSIVE descendants AS (
                SELECT department_id FROM iam.department WHERE parent_department_id=%s AND deleted_at IS NULL
                UNION
                SELECT d.department_id FROM iam.department d JOIN descendants p ON d.parent_department_id=p.department_id
                WHERE d.deleted_at IS NULL
            ) SELECT 1 FROM descendants WHERE department_id=%s LIMIT 1
            """, (department_id, parent_id),
        )
        if cursor.fetchone():
            raise ValueError("上级部门不能选择当前部门的子孙部门")

    def update(self, context, department_id: int, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM iam.department WHERE department_id=%s AND deleted_at IS NULL FOR UPDATE", (department_id,))
            current = cursor.fetchone()
            if not current:
                raise ValueError("部门不存在")
            name = text(payload.get("department_name", current["department_name"]), "部门名称", maximum=100)
            parent_id = optional_int(payload.get("parent_department_id", current["parent_department_id"]), "上级部门ID")
            active = boolean(payload.get("is_active", current["is_active"]), "启用状态")
            order = max(0, int(payload.get("display_order", current["display_order"])))
            self._validate_parent(cursor, department_id, parent_id)
            cursor.execute(
                """UPDATE iam.department SET department_name=%s,parent_department_id=%s,display_order=%s,is_active=%s,updated_at=NOW()
                   WHERE department_id=%s RETURNING department_id,department_code,department_name,parent_department_id,display_order,is_active""",
                (name, parent_id, order, active, department_id),
            )
            row = dict(cursor.fetchone())
            write_audit(cursor, action="department.update", target_type="department", target_id=department_id,
                        actor=context, before=dict(current), after=row, ip_address=ip_address, user_agent=user_agent)
            return row

    def delete(self, context, department_id: int, *, ip_address: str, user_agent: str) -> None:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT department_code,department_name FROM iam.department WHERE department_id=%s AND deleted_at IS NULL FOR UPDATE", (department_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("部门不存在")
            cursor.execute("SELECT EXISTS(SELECT 1 FROM iam.department WHERE parent_department_id=%s AND deleted_at IS NULL) AS has_children", (department_id,))
            if cursor.fetchone()["has_children"]:
                raise ValueError("部门存在子部门，不能删除")
            cursor.execute("SELECT EXISTS(SELECT 1 FROM iam.user_account WHERE department_id=%s AND is_active AND deleted_at IS NULL) AS has_users", (department_id,))
            if cursor.fetchone()["has_users"]:
                raise ValueError("部门存在有效用户，不能删除")
            cursor.execute("UPDATE iam.department SET deleted_at=NOW(),is_active=FALSE,updated_at=NOW() WHERE department_id=%s", (department_id,))
            write_audit(cursor, action="department.delete", target_type="department", target_id=department_id,
                        actor=context, before=dict(row), after={"deleted": True}, ip_address=ip_address, user_agent=user_agent)
