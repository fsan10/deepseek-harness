from __future__ import annotations

import os
import math
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

from .audit import write_audit
from .authorization import AuthContext, AuthenticationError, AuthorizationError, RateLimitError
from .password_cipher import UserPasswordCipher
from .security import normalize_username, password_hash, password_matches, random_token, token_hash, validate_password


SESSION_COOKIE = "mocc_session"


class LoginRateLimiter:
    """In-memory front line that rejects bursts before they reach PostgreSQL."""

    def __init__(self, *, window_seconds: int = 60, user_ip_limit: int = 5,
                 ip_limit: int = 20, cooldown_seconds: int = 60):
        self.window_seconds = max(10, int(window_seconds))
        self.user_ip_limit = max(3, int(user_ip_limit))
        self.ip_limit = max(self.user_ip_limit, int(ip_limit))
        self.cooldown_seconds = max(10, int(cooldown_seconds))
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, ip_address: str) -> tuple[str, str]:
        return f"user-ip:{username}:{ip_address}", f"ip:{ip_address}"

    def consume(self, username: str, ip_address: str) -> None:
        now = time.monotonic()
        keys = self._keys(username, ip_address)
        limits = (self.user_ip_limit, self.ip_limit)
        with self._lock:
            retry = max((self._blocked_until.get(key, 0) - now for key in keys), default=0)
            if retry > 0:
                raise RateLimitError(f"登录请求过于频繁，请{math.ceil(retry)}秒后重试", math.ceil(retry))
            for key, limit in zip(keys, limits):
                events = self._events[key]
                while events and events[0] <= now - self.window_seconds:
                    events.popleft()
                events.append(now)
                if len(events) > limit:
                    blocked_until = now + self.cooldown_seconds
                    self._blocked_until[key] = blocked_until
                    raise RateLimitError(f"登录请求过于频繁，请{self.cooldown_seconds}秒后重试", self.cooldown_seconds)

    def block(self, username: str, ip_address: str, seconds: int) -> None:
        until = time.monotonic() + max(1, int(seconds))
        with self._lock:
            key = self._keys(username, ip_address)[0]
            self._blocked_until[key] = max(self._blocked_until.get(key, 0), until)

    def reset(self, username: str, ip_address: str) -> None:
        with self._lock:
            for key in self._keys(username, ip_address):
                self._events.pop(key, None)
                self._blocked_until.pop(key, None)


class AuthService:
    def __init__(self, database, password_cipher: UserPasswordCipher | None = None):
        self.database = database
        self.password_cipher = password_cipher or UserPasswordCipher()
        self.idle_minutes = max(5, int(os.getenv("AUTH_IDLE_MINUTES", "30")))
        self.absolute_hours = max(1, int(os.getenv("AUTH_ABSOLUTE_HOURS", "8")))
        self.failure_limit = max(3, int(os.getenv("AUTH_FAILURE_LIMIT", "5")))
        self.lock_minutes = max(1, int(os.getenv("AUTH_LOCK_MINUTES", "15")))
        self.login_limiter = LoginRateLimiter(
            window_seconds=int(os.getenv("AUTH_LOGIN_RATE_WINDOW_SECONDS", "60")),
            user_ip_limit=int(os.getenv("AUTH_LOGIN_RATE_USER_IP_LIMIT", "5")),
            ip_limit=int(os.getenv("AUTH_LOGIN_RATE_IP_LIMIT", "20")),
            cooldown_seconds=int(os.getenv("AUTH_LOGIN_RATE_COOLDOWN_SECONDS", "60")),
        )
        self._dummy_password_hash = password_hash(random_token())

    @staticmethod
    def read_cookie(headers) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def cookie_header(self, token: str, *, clear: bool = False) -> str:
        secure = os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
        pieces = [f"{SESSION_COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Strict"]
        pieces.append("Max-Age=0" if clear else f"Max-Age={self.absolute_hours * 3600}")
        if secure:
            pieces.append("Secure")
        return "; ".join(pieces)

    def csrf_cookie_header(self, token: str, *, clear: bool = False) -> str:
        secure = os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
        pieces = [f"mocc_csrf={'' if clear else token}", "Path=/", "SameSite=Strict"]
        pieces.append("Max-Age=0" if clear else f"Max-Age={self.absolute_hours * 3600}")
        if secure:
            pieces.append("Secure")
        return "; ".join(pieces)

    def _effective_permissions(self, cursor, user_id: int, is_super_admin: bool) -> tuple[set[str], dict[str, str]]:
        cursor.execute("SELECT resource_code FROM iam.permission_resource WHERE is_active")
        all_codes = {row["resource_code"] for row in cursor.fetchall()}
        if is_super_admin:
            return all_codes, {code: "super_admin" for code in all_codes}

        cursor.execute(
            """
            WITH RECURSIVE user_department AS (
                SELECT d.department_id, d.parent_department_id, d.is_active
                FROM iam.user_account u
                JOIN iam.department d ON d.department_id = u.department_id
                WHERE u.user_id=%s AND d.deleted_at IS NULL
                UNION
                SELECT parent.department_id, parent.parent_department_id, parent.is_active
                FROM iam.department parent
                JOIN user_department child ON child.parent_department_id = parent.department_id
                WHERE parent.deleted_at IS NULL
            ), role_allows AS (
                SELECT DISTINCT rp.resource_id
                FROM iam.user_role ur
                JOIN iam.role r ON r.role_id=ur.role_id AND r.is_active AND r.deleted_at IS NULL
                JOIN iam.role_permission rp ON rp.role_id=r.role_id
                WHERE ur.user_id=%s
            ), department_allows AS (
                SELECT DISTINCT dp.resource_id
                FROM user_department ud
                JOIN iam.department_permission dp ON dp.department_id=ud.department_id
                WHERE ud.is_active
            )
            SELECT pr.resource_code,
                   up.permission_effect AS direct_effect,
                   (ra.resource_id IS NOT NULL) AS role_allow,
                   (da.resource_id IS NOT NULL) AS department_allow
            FROM iam.permission_resource pr
            LEFT JOIN iam.user_permission up ON up.resource_id=pr.resource_id AND up.user_id=%s
            LEFT JOIN role_allows ra ON ra.resource_id=pr.resource_id
            LEFT JOIN department_allows da ON da.resource_id=pr.resource_id
            WHERE pr.is_active
            """,
            (user_id, user_id, user_id),
        )
        allowed: set[str] = set()
        sources: dict[str, str] = {}
        for row in cursor.fetchall():
            code = row["resource_code"]
            if row["direct_effect"] == "deny":
                sources[code] = "user_deny"
            elif row["direct_effect"] == "allow":
                allowed.add(code); sources[code] = "user_allow"
            elif row["role_allow"]:
                allowed.add(code); sources[code] = "role"
            elif row["department_allow"]:
                allowed.add(code); sources[code] = "department"
        return allowed, sources

    def authenticate(self, headers) -> AuthContext:
        raw_token = self.read_cookie(headers)
        if not raw_token:
            raise AuthenticationError("请先登录")
        digest = token_hash(raw_token)
        now = datetime.now(timezone.utc)
        with self.database.transaction() as cursor:
            cursor.execute(
                """
                SELECT s.session_token_hash, s.csrf_token_hash, s.user_session_version,
                       s.idle_expires_at, s.absolute_expires_at, s.revoked_at,
                       u.user_id, u.username, u.display_name, u.department_id,
                       u.is_active, u.is_super_admin, u.session_version, u.deleted_at,
                       d.department_name
                FROM iam.user_session s
                JOIN iam.user_account u ON u.user_id=s.user_id
                LEFT JOIN iam.department d ON d.department_id=u.department_id AND d.deleted_at IS NULL
                WHERE s.session_token_hash=%s
                FOR UPDATE OF s
                """,
                (digest,),
            )
            row = cursor.fetchone()
            invalid = (
                not row or row["revoked_at"] is not None or row["deleted_at"] is not None
                or not row["is_active"] or row["user_session_version"] != row["session_version"]
                or row["idle_expires_at"] <= now or row["absolute_expires_at"] <= now
            )
            if invalid:
                if row and row["revoked_at"] is None:
                    cursor.execute("UPDATE iam.user_session SET revoked_at=NOW() WHERE session_token_hash=%s", (digest,))
                raise AuthenticationError("登录会话已失效，请重新登录")
            idle_expiry = min(row["absolute_expires_at"], now + timedelta(minutes=self.idle_minutes))
            cursor.execute(
                "UPDATE iam.user_session SET last_seen_at=NOW(), idle_expires_at=%s WHERE session_token_hash=%s",
                (idle_expiry, digest),
            )
            permissions, sources = self._effective_permissions(cursor, int(row["user_id"]), bool(row["is_super_admin"]))
            return AuthContext(
                user_id=int(row["user_id"]), username=row["username"], display_name=row["display_name"],
                department_id=int(row["department_id"]) if row["department_id"] is not None else None,
                department_name=row["department_name"], is_super_admin=bool(row["is_super_admin"]),
                session_token_hash=digest, csrf_token_hash=row["csrf_token_hash"],
                permissions=permissions, permission_sources=sources,
            )

    def verify_csrf(self, context: AuthContext, headers) -> None:
        supplied = headers.get("X-CSRF-Token", "")
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
        except Exception:
            cookie = SimpleCookie()
        cookie_token = cookie.get("mocc_csrf").value if cookie.get("mocc_csrf") else ""
        if not supplied or not cookie_token or supplied != cookie_token or token_hash(supplied) != context.csrf_token_hash:
            raise AuthorizationError("CSRF校验失败，请刷新页面后重试")

    def login(self, payload: dict, *, ip_address: str, user_agent: str) -> tuple[dict, str]:
        try:
            username = normalize_username(payload.get("username"))
        except ValueError:
            username = str(payload.get("username") or "").strip().lower()[:64]
        supplied_password = str(payload.get("password") or "")
        client_ip = str(ip_address or "unknown")[:45]
        limiter_username = username or "invalid"
        self.login_limiter.consume(limiter_username, client_ip)
        now = datetime.now(timezone.utc)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM iam.user_account WHERE username=%s AND deleted_at IS NULL FOR UPDATE", (username,))
            user = cursor.fetchone()
            if not user:
                password_matches(supplied_password, self._dummy_password_hash)
                reason, message = "user_not_found", "没有该用户，请检查用户名是否输入错误"
            elif not user["is_active"]:
                reason, message = "disabled", "账号已禁用，请联系管理员"
            elif user["locked_until"] and user["locked_until"] > now:
                retry_after = max(1, math.ceil((user["locked_until"] - now).total_seconds()))
                self.login_limiter.block(limiter_username, client_ip, retry_after)
                reason, message = "temporarily_locked", f"账号已临时锁定，请{math.ceil(retry_after / 60)}分钟后重试"
            elif not password_matches(supplied_password, user["password_hash"]):
                reason, message = "wrong_password", "密码错误，请重新输入密码"
            else:
                reason = ""
                message = ""

            if reason:
                cursor.execute(
                    "INSERT INTO iam.login_attempt(username,ip_address,is_success,failure_reason) VALUES (%s,%s,FALSE,%s)",
                    (limiter_username, client_ip, reason),
                )
                account_retry_after = 0
                if reason == "wrong_password":
                    failures = int(user["failed_login_count"]) + 1
                    lock_until = now + timedelta(minutes=self.lock_minutes) if failures >= self.failure_limit else None
                    cursor.execute(
                        "UPDATE iam.user_account SET failed_login_count=%s,locked_until=%s,updated_at=NOW() WHERE user_id=%s",
                        (failures, lock_until, user["user_id"]),
                    )
                    if lock_until:
                        account_retry_after = self.lock_minutes * 60
                        message = f"密码错误次数过多，账号已临时锁定，请{self.lock_minutes}分钟后重试"
                write_audit(cursor, action="auth.login.failed", target_type="user", target_id=username,
                            after={"reason": reason}, ip_address=client_ip, user_agent=user_agent)
                cursor.connection.commit()
                if reason == "temporarily_locked":
                    retry_after = max(1, math.ceil((user["locked_until"] - now).total_seconds()))
                    raise RateLimitError(message, retry_after)
                if account_retry_after:
                    self.login_limiter.block(limiter_username, client_ip, account_retry_after)
                    raise RateLimitError(message, account_retry_after)
                raise AuthenticationError(message)

            session_token, csrf_token = random_token(), random_token()
            absolute = now + timedelta(hours=self.absolute_hours)
            idle = min(absolute, now + timedelta(minutes=self.idle_minutes))
            cursor.execute(
                """
                INSERT INTO iam.user_session
                    (session_token_hash,csrf_token_hash,user_id,user_session_version,ip_address,user_agent,idle_expires_at,absolute_expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (token_hash(session_token), token_hash(csrf_token), user["user_id"], user["session_version"],
                 ip_address, user_agent[:500], idle, absolute),
            )
            cursor.execute(
                "UPDATE iam.user_account SET failed_login_count=0,locked_until=NULL,last_login_at=NOW(),updated_at=NOW() WHERE user_id=%s",
                (user["user_id"],),
            )
            cursor.execute("INSERT INTO iam.login_attempt(username,ip_address,is_success) VALUES (%s,%s,TRUE)", (username, ip_address))
            actor = type("Actor", (), {"user_id": int(user["user_id"]), "username": username})()
            write_audit(cursor, action="auth.login.success", target_type="session", target_id=token_hash(session_token)[:12],
                        actor=actor, ip_address=ip_address, user_agent=user_agent)
            self.login_limiter.reset(limiter_username, client_ip)
            return {"user": {"user_id": user["user_id"], "username": username, "display_name": user["display_name"]},
                    "csrf_token": csrf_token}, session_token

    def logout(self, context: AuthContext, *, ip_address: str, user_agent: str) -> None:
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE iam.user_session SET revoked_at=NOW() WHERE session_token_hash=%s", (context.session_token_hash,))
            write_audit(cursor, action="auth.logout", target_type="session", target_id=context.session_token_hash[:12],
                        actor=context, ip_address=ip_address, user_agent=user_agent)

    def change_password(self, context: AuthContext, payload: dict, *, ip_address: str, user_agent: str) -> None:
        new_password = validate_password(payload.get("new_password"))
        with self.database.transaction() as cursor:
            cursor.execute("SELECT password_hash,session_version FROM iam.user_account WHERE user_id=%s FOR UPDATE", (context.user_id,))
            user = cursor.fetchone()
            if not user or not password_matches(payload.get("current_password"), user["password_hash"]):
                raise ValueError("当前密码不正确")
            if password_matches(new_password, user["password_hash"]):
                raise ValueError("新密码不能与当前密码相同")
            ciphertext, nonce = self.password_cipher.encrypt(new_password, context.user_id)
            version = int(user["session_version"]) + 1
            cursor.execute(
                """UPDATE iam.user_account
                   SET password_hash=%s,password_ciphertext=%s,password_nonce=%s,
                       password_changed_at=NOW(),session_version=%s,updated_at=NOW()
                   WHERE user_id=%s""",
                (password_hash(new_password), ciphertext, nonce, version, context.user_id),
            )
            cursor.execute("UPDATE iam.user_session SET revoked_at=NOW() WHERE user_id=%s AND session_token_hash<>%s AND revoked_at IS NULL", (context.user_id, context.session_token_hash))
            cursor.execute("UPDATE iam.user_session SET user_session_version=%s WHERE session_token_hash=%s", (version, context.session_token_hash))
            write_audit(cursor, action="auth.password.change", target_type="user", target_id=context.user_id,
                        actor=context, ip_address=ip_address, user_agent=user_agent)

    def initialize_super_admin(self, username: str, password: str, display_name: str) -> dict:
        username = normalize_username(username)
        encoded = password_hash(password)
        display_name = str(display_name or "超级管理员").strip()[:100]
        if not display_name:
            raise ValueError("管理员显示名称不能为空")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT user_id FROM iam.user_account WHERE username=%s", (username,))
            if cursor.fetchone():
                raise ValueError("初始管理员已存在；初始化命令不会覆盖现有密码")
            cursor.execute(
                """
                INSERT INTO iam.user_account(username,display_name,password_hash,is_active,is_super_admin)
                VALUES (%s,%s,%s,TRUE,TRUE) RETURNING user_id
                """, (username, display_name, encoded),
            )
            user_id = int(cursor.fetchone()["user_id"])
            ciphertext, nonce = self.password_cipher.encrypt(password, user_id)
            cursor.execute(
                "UPDATE iam.user_account SET password_ciphertext=%s,password_nonce=%s WHERE user_id=%s",
                (ciphertext, nonce, user_id),
            )
            write_audit(cursor, action="system.super_admin.initialize", target_type="user", target_id=user_id,
                        after={"username": username, "display_name": display_name, "is_super_admin": True})
            return {"user_id": user_id, "username": username, "display_name": display_name}
