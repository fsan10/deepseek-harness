from __future__ import annotations

import os

from .audit import write_audit
from .authorization import AuthorizationError
from .password_cipher import UserPasswordCipher
from .security import normalize_username, password_hash, validate_password
from .validation import boolean, optional_int, paging, text


class UserService:
    def __init__(self, database, password_cipher: UserPasswordCipher | None = None):
        self.database = database
        self.password_cipher = password_cipher or UserPasswordCipher()

    DEFAULT_PASSWORD_ENV = "DEFAULT_INITIAL_PASSWORD"

    @staticmethod
    def require(context) -> None:
        if not context.can("system.user.manage"):
            raise AuthorizationError("无权管理用户")

    @staticmethod
    def require_password_view(context) -> None:
        if not context.can("system.user.password.view"):
            raise AuthorizationError("无权查看用户密码")

    @classmethod
    def initial_password(cls, value: object) -> str:
        password = value
        if password is None or password == "":
            password = os.getenv(cls.DEFAULT_PASSWORD_ENV, "")
            if not password:
                raise RuntimeError(f"未配置{cls.DEFAULT_PASSWORD_ENV}，无法使用默认初始密码")
        return validate_password(password)

    @staticmethod
    def _assert_super_admin_survives(cursor, user_id: int, will_be_active: bool, will_be_super: bool) -> None:
        cursor.execute("SELECT is_active,is_super_admin FROM iam.user_account WHERE user_id=%s AND deleted_at IS NULL", (user_id,))
        current = cursor.fetchone()
        if not current:
            raise ValueError("用户不存在")
        removes = current["is_active"] and current["is_super_admin"] and (not will_be_active or not will_be_super)
        if removes:
            cursor.execute("SELECT COUNT(*) AS total FROM iam.user_account WHERE is_active AND is_super_admin AND deleted_at IS NULL")
            if int(cursor.fetchone()["total"]) <= 1:
                raise ValueError("系统必须至少保留一个有效超级管理员")

    def list(self, context, query: dict[str, str]) -> dict:
        self.require(context)
        page, size, offset = paging(query)
        keyword = f"%{query.get('keyword', '').strip()}%"
        status = query.get("is_active")
        conditions = ["u.deleted_at IS NULL", "(%s='' OR u.username ILIKE %s OR u.display_name ILIKE %s)"]
        params: list = [query.get("keyword", "").strip(), keyword, keyword]
        if status in {"true", "false"}:
            conditions.append("u.is_active=%s"); params.append(status == "true")
        where = " AND ".join(conditions)
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM iam.user_account u WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT u.user_id,u.username,u.display_name,u.department_id,d.department_name,
                           u.is_active,u.is_super_admin,u.last_login_at,u.created_at,
                           COALESCE(array_agg(r.role_id) FILTER (WHERE r.role_id IS NOT NULL),'{{}}') AS role_ids,
                           COALESCE(string_agg(r.role_name,'、' ORDER BY r.role_name),'') AS role_names
                    FROM iam.user_account u
                    LEFT JOIN iam.department d ON d.department_id=u.department_id
                    LEFT JOIN iam.user_role ur ON ur.user_id=u.user_id
                    LEFT JOIN iam.role r ON r.role_id=ur.role_id AND r.deleted_at IS NULL
                    WHERE {where}
                    GROUP BY u.user_id,d.department_name ORDER BY u.created_at DESC,u.user_id DESC LIMIT %s OFFSET %s""",
                params + [size, offset],
            )
            return {"items": [dict(row) for row in cursor.fetchall()], "total": total, "page": page, "page_size": size}

    def create(self, context, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require(context)
        username = normalize_username(payload.get("username"))
        display_name = text(payload.get("display_name"), "显示名称", maximum=100)
        department_id = optional_int(payload.get("department_id"), "部门ID")
        role_ids = sorted({int(value) for value in payload.get("role_ids", [])})
        is_super = boolean(payload.get("is_super_admin", False), "超级管理员标记")
        password = self.initial_password(payload.get("password"))
        encoded = password_hash(password)
        with self.database.transaction() as cursor:
            cursor.execute(
                """INSERT INTO iam.user_account(username,display_name,password_hash,department_id,is_active,is_super_admin)
                   VALUES (%s,%s,%s,%s,TRUE,%s) RETURNING user_id,username,display_name,department_id,is_active,is_super_admin""",
                (username, display_name, encoded, department_id, is_super),
            )
            row = dict(cursor.fetchone())
            ciphertext, nonce = self.password_cipher.encrypt(password, row["user_id"])
            cursor.execute(
                "UPDATE iam.user_account SET password_ciphertext=%s,password_nonce=%s WHERE user_id=%s",
                (ciphertext, nonce, row["user_id"]),
            )
            for role_id in role_ids:
                cursor.execute("INSERT INTO iam.user_role(user_id,role_id,granted_by) VALUES (%s,%s,%s)", (row["user_id"], role_id, context.user_id))
            row["role_ids"] = role_ids
            write_audit(cursor, action="user.create", target_type="user", target_id=row["user_id"], actor=context,
                        after=row, ip_address=ip_address, user_agent=user_agent)
            return row

    def update(self, context, user_id: int, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require(context)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT user_id,username,display_name,department_id,is_active,is_super_admin FROM iam.user_account WHERE user_id=%s AND deleted_at IS NULL FOR UPDATE", (user_id,))
            current = cursor.fetchone()
            if not current:
                raise ValueError("用户不存在")
            display_name = text(payload.get("display_name", current["display_name"]), "显示名称", maximum=100)
            department_id = optional_int(payload.get("department_id", current["department_id"]), "部门ID")
            active = boolean(payload.get("is_active", current["is_active"]), "启用状态")
            super_admin = boolean(payload.get("is_super_admin", current["is_super_admin"]), "超级管理员标记")
            self._assert_super_admin_survives(cursor, user_id, active, super_admin)
            cursor.execute(
                """UPDATE iam.user_account SET display_name=%s,department_id=%s,is_active=%s,is_super_admin=%s,
                           session_version=session_version + CASE WHEN is_active AND NOT %s THEN 1 ELSE 0 END,updated_at=NOW()
                   WHERE user_id=%s RETURNING user_id,username,display_name,department_id,is_active,is_super_admin""",
                (display_name, department_id, active, super_admin, active, user_id),
            )
            result = dict(cursor.fetchone())
            if "role_ids" in payload:
                role_ids = sorted({int(value) for value in payload.get("role_ids", [])})
                cursor.execute("DELETE FROM iam.user_role WHERE user_id=%s", (user_id,))
                for role_id in role_ids:
                    cursor.execute("INSERT INTO iam.user_role(user_id,role_id,granted_by) VALUES (%s,%s,%s)", (user_id, role_id, context.user_id))
                result["role_ids"] = role_ids
            if not active:
                cursor.execute("UPDATE iam.user_session SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            write_audit(cursor, action="user.update", target_type="user", target_id=user_id, actor=context,
                        before=dict(current), after=result, ip_address=ip_address, user_agent=user_agent)
            return result

    def reset_password(self, context, user_id: int, payload: dict, *, ip_address: str, user_agent: str) -> None:
        self.require(context)
        password = validate_password(payload.get("new_password"))
        encoded = password_hash(password)
        ciphertext, nonce = self.password_cipher.encrypt(password, user_id)
        with self.database.transaction() as cursor:
            cursor.execute("""UPDATE iam.user_account
                            SET password_hash=%s,password_ciphertext=%s,password_nonce=%s,
                                password_changed_at=NOW(),session_version=session_version+1,updated_at=NOW()
                            WHERE user_id=%s AND deleted_at IS NULL RETURNING username""",
                           (encoded, ciphertext, nonce, user_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("用户不存在")
            cursor.execute("UPDATE iam.user_session SET revoked_at=NOW() WHERE user_id=%s AND revoked_at IS NULL", (user_id,))
            write_audit(cursor, action="user.password.reset", target_type="user", target_id=user_id, actor=context,
                        after={"username": row["username"], "sessions_revoked": True}, ip_address=ip_address, user_agent=user_agent)

    def view_password(self, context, user_id: int, *, ip_address: str = "", user_agent: str = "") -> dict:
        self.require_password_view(context)
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT user_id,username,display_name,password_ciphertext,password_nonce
                   FROM iam.user_account WHERE user_id=%s AND deleted_at IS NULL""",
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("用户不存在")
            if not row["password_ciphertext"] or not row["password_nonce"]:
                raise ValueError("该用户尚未保存可查看的密码，请先重置密码")
            try:
                password = self.password_cipher.decrypt(
                    row["password_ciphertext"], row["password_nonce"], row["user_id"],
                )
            except Exception as exc:
                raise RuntimeError("用户密码密文无法解密，请检查服务端加密密钥") from exc
            write_audit(
                cursor, action="user.password.view", target_type="user", target_id=user_id,
                actor=context, after={"username": row["username"]},
                ip_address=ip_address, user_agent=user_agent,
            )
            return {
                "user_id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "password": password,
            }
