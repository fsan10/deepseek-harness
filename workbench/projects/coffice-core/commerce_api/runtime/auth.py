"""Cached profile binding and one-time recovery of confirmed authentication loss."""
from __future__ import annotations

from dataclasses import asdict
import asyncio

from ..core.contracts import Profile, now_iso
from ..core.errors import AuthRequired, CommerceError, IdentityMismatch, NeedsHuman, UsageError
from ..core.registry import load_symbol
from .sessions import SessionStore, session_key
from .storage import Paths, atomic_json, read_json


def profile_binding(paths: Paths, name: str, platform: str) -> Profile:
    cached = read_json(paths.file("config", "profiles"), {})
    if name in cached:
        profile = Profile(**cached[name])
        if profile.platform != platform or not profile.enabled:
            raise UsageError("本地 Profile 平台不匹配或已停用")
        # A legacy disabled-shop override remains a read-only minimum restriction.
        from ..integrations.legacy.environment import legacy_root
        policy_path = legacy_root() / "scripts/auto_download/all_platform_downloads.json"
        if policy_path.is_file():
            policy = read_json(policy_path, {}).get("profile_status", {}).get(name, {})
            if policy.get("enabled", True) is False or str(policy.get("status", "active")).casefold() not in {"active", "enabled", "正常", "启用", "运行"}:
                raise UsageError("原项目已停用此 Profile，禁止在新 CLI 中自动启用")
        return profile
    from ..integrations.legacy.profiles import select_profile
    profile = select_profile(name, platform)
    atomic_json(paths.file("config", "profiles"), {**cached, name: asdict(profile)})
    return profile


class AuthManager:
    def __init__(self, paths: Paths, registry, *, store=None, transport=None, login_timeout=300):
        self.paths, self.registry = paths, registry
        self.store = store or SessionStore(paths)
        self.transport = transport
        self.login_timeout = login_timeout

    def client(self, profile, backend, credential=None):
        credential = credential or self.store.load(session_key(profile.id, profile.platform, backend.id))
        if credential.get("profile", {}).get("id") != profile.id:
            raise IdentityMismatch("加密会话中的 Profile 标识不一致", stage="auth")
        return load_symbol(backend.client)(backend, credential, profile, store=self.store, transport=self.transport)

    async def login(self, profile, backend, *, account_id=None, already_locked=False):
        from ..integrations.legacy.login import authenticate
        key = session_key(profile.id, profile.platform, backend.id)
        try:
            previous = self.store.load(key)
        except AuthRequired:
            previous = {}
        try:
            credential = await asyncio.wait_for(authenticate(profile, backend, account_id=account_id,
                already_locked=already_locked, previous=previous), timeout=self.login_timeout)
        except TimeoutError:
            error = NeedsHuman("登录等待已到五分钟保护上限，原 Profile 现场保留，处理后可续跑", stage="auth")
            self._status(profile, backend, "needs_human", error=error.public())
            raise error from None
        credential["identity"] = previous.get("identity", {})
        credential["contexts"] = {**previous.get("contexts", {}), **credential.get("contexts", {})}
        client = self.client(profile, backend, {**credential, "key": key})
        try:
            identity = await client.identity()
            credential.update(client.http.snapshot())
            credential["identity"] = identity
            self.store.save(key, credential)
            self._status(profile, backend, "valid", identity=identity)
            return identity
        finally:
            await client.close()

    def _status(self, profile, backend, state, *, identity=None, error=None):
        atomic_json(self.paths.file("health", session_key(profile.id, profile.platform, backend.id)),
            {"profile": profile.name, "backend": backend.id, "platform": profile.platform,
             "state": state, "checked_at": now_iso(), "identity": identity or {}, "error": error})

    async def check(self, profile, backend, *, recover=True, account_id=None, already_locked=False):
        try:
            client = self.client(profile, backend)
            try:
                identity = await client.identity()
                self._status(profile, backend, "valid", identity=identity)
                return identity
            finally:
                await client.close()
        except AuthRequired as exc:
            self._status(profile, backend, "auth_required", error=exc.public())
            if recover:
                return await self.login(profile, backend, account_id=account_id, already_locked=already_locked)
            raise
        except CommerceError as exc:
            self._status(profile, backend, exc.code.lower(), error=exc.public())
            raise
