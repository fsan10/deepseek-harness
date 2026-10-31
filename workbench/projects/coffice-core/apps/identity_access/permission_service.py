from __future__ import annotations

from .audit import write_audit
from .authorization import AuthorizationError


class PermissionService:
    def __init__(self, database, auth_service):
        self.database = database
        self.auth_service = auth_service

    @staticmethod
    def require(context, permission: str) -> None:
        if not context.can(permission):
            raise AuthorizationError("无权执行该操作")

    def resources(self, context) -> dict:
        self.require(context, "system.permission.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                """
                SELECT resource_id,resource_code,resource_name,resource_type,module_code,
                       parent_resource_id,route_path,display_order,is_active
                FROM iam.permission_resource
                WHERE is_active
                  AND (parent_resource_id IS NULL OR EXISTS (
                      SELECT 1
                      FROM iam.permission_resource parent
                      WHERE parent.resource_id=iam.permission_resource.parent_resource_id
                        AND parent.is_active
                  ))
                ORDER BY module_code,display_order,resource_id
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
        by_parent: dict[int | None, list[dict]] = {}
        for row in rows:
            row["children"] = []
            by_parent.setdefault(row["parent_resource_id"], []).append(row)
        for row in rows:
            row["children"] = by_parent.get(row["resource_id"], [])
        return {"items": by_parent.get(None, []), "flat_items": rows}

    def effective_for_user(self, context, user_id: int) -> dict:
        if context.user_id != user_id:
            self.require(context, "system.user.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                "SELECT user_id,username,display_name,is_super_admin FROM iam.user_account WHERE user_id=%s AND deleted_at IS NULL",
                (user_id,),
            )
            user = cursor.fetchone()
            if not user:
                raise ValueError("用户不存在")
            allowed, sources = self.auth_service._effective_permissions(cursor, user_id, bool(user["is_super_admin"]))
            cursor.execute("SELECT resource_code,resource_name,resource_type,module_code FROM iam.permission_resource WHERE is_active ORDER BY module_code,display_order")
            items = []
            for resource in cursor.fetchall():
                code = resource["resource_code"]
                items.append({**dict(resource), "is_allowed": code in allowed, "source": sources.get(code, "default_deny")})
            return {"user": dict(user), "items": items}

    def assignments(self, context, target_type: str, target_id: int) -> dict:
        self.require(context, "system.permission.manage")
        if target_type not in {"role", "department", "user"}:
            raise ValueError("授权对象类型无效")
        table = {"role": "role_permission", "department": "department_permission", "user": "user_permission"}[target_type]
        id_column = f"{target_type}_id"
        effect_column = ", permission_effect" if target_type == "user" else ""
        with self.database.transaction() as cursor:
            cursor.execute(
                f"""SELECT assignment.resource_id{effect_column}
                    FROM iam.{table} assignment
                    JOIN iam.permission_resource resource
                      ON resource.resource_id=assignment.resource_id
                     AND resource.is_active
                   WHERE assignment.{id_column}=%s""",
                (target_id,),
            )
            return {"items": [dict(row) for row in cursor.fetchall()]}

    def replace_assignments(self, context, target_type: str, target_id: int, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require(context, "system.permission.manage")
        if target_type not in {"role", "department", "user"}:
            raise ValueError("授权对象类型无效")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) > 1000:
            raise ValueError("权限项必须是最多1000条的数组")
        normalized: dict[int, str] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError("权限项格式错误")
            resource_id = int(item.get("resource_id", 0))
            if resource_id <= 0:
                raise ValueError("权限资源ID无效")
            effect = str(item.get("effect") or "allow")
            if effect not in ({"allow", "deny"} if target_type == "user" else {"allow"}):
                raise ValueError("权限效果无效")
            normalized[resource_id] = effect
        table = {"role": "role_permission", "department": "department_permission", "user": "user_permission"}[target_type]
        id_column = f"{target_type}_id"
        with self.database.transaction() as cursor:
            cursor.execute("SELECT resource_id FROM iam.permission_resource WHERE resource_id=ANY(%s) AND is_active", (list(normalized),))
            existing = {int(row["resource_id"]) for row in cursor.fetchall()}
            if existing != set(normalized):
                raise ValueError("包含不存在或已停用的权限资源")
            cursor.execute(f"SELECT resource_id{',permission_effect' if target_type == 'user' else ''} FROM iam.{table} WHERE {id_column}=%s", (target_id,))
            before = [dict(row) for row in cursor.fetchall()]
            cursor.execute(f"DELETE FROM iam.{table} WHERE {id_column}=%s", (target_id,))
            for resource_id, effect in normalized.items():
                if target_type == "user":
                    cursor.execute("INSERT INTO iam.user_permission(user_id,resource_id,permission_effect,granted_by) VALUES (%s,%s,%s,%s)",
                                   (target_id, resource_id, effect, context.user_id))
                else:
                    cursor.execute(f"INSERT INTO iam.{table}({id_column},resource_id,granted_by) VALUES (%s,%s,%s)",
                                   (target_id, resource_id, context.user_id))
            after = [{"resource_id": rid, "permission_effect": effect} for rid, effect in normalized.items()]
            write_audit(cursor, action=f"permission.{target_type}.replace", target_type=target_type, target_id=target_id,
                        actor=context, before={"items": before}, after={"items": after}, ip_address=ip_address, user_agent=user_agent)
        return {"items": after}
