"""Opt-in auth checks. Disabled policies return before any external access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core.contracts import now_iso
from ..core.errors import CommerceError, LockBusy, UsageError
from .auth import AuthManager, profile_binding
from .sessions import session_key
from .storage import Paths, atomic_json, file_lock, read_json


def policy(paths: Paths) -> dict:
    return read_json(paths.file("config", "health"), {"enabled": False, "interval_minutes": 1440, "profiles": {}})


def set_policy(paths, *, enabled=None, profile=None, platform=None, backend=None, interval=None):
    value = policy(paths)
    if interval is not None:
        if interval < 60:
            raise UsageError("后台认证检查间隔至少 60 分钟")
        value["interval_minutes"] = interval
    if profile:
        if not platform or not backend:
            raise UsageError("店铺级开关必须同时指定 platform 和 backend")
        identifier = f"{platform}:{backend}:{profile}"
        previous = value["profiles"].get(identifier, {})
        value["profiles"][identifier] = {"profile": profile, "platform": platform, "backend": backend,
            "enabled": bool(enabled) if enabled is not None else bool(previous.get("enabled", False))}
    elif enabled is not None:
        value["enabled"] = enabled
    atomic_json(paths.file("config", "health"), value)
    return value


async def check_due(paths, registry, *, auth=None):
    value = policy(paths)
    if not value["enabled"]:
        return {"enabled": False, "checked": [], "skipped": "disabled"}
    manager = auth or AuthManager(paths, registry)
    result = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=value["interval_minutes"])
    for item in value.get("profiles", {}).values():
        if not item.get("enabled"):
            continue
        profile = backend = None
        try:
            profile = profile_binding(paths, item["profile"], item["platform"])
            backend = registry.backend(item["platform"], item["backend"])
            key = session_key(profile.id, profile.platform, backend.id)
            previous = read_json(paths.file("health", key), {})
            if previous.get("state") in {"needs_human", "identity_mismatch", "context_required"}:
                continue
            checked = previous.get("checked_at")
            if checked and datetime.fromisoformat(checked) >= cutoff:
                continue
            from ..integrations.legacy.locking import legacy_browser_lock
            with file_lock(paths.file("locks", key, ".lock")), legacy_browser_lock():
                identity = await manager.check(profile, backend, already_locked=True)
            result.append({**item, "state": "valid", "identity": identity})
        except LockBusy:
            result.append({**item, "state": "skipped_busy"})
        except CommerceError as exc:
            if profile and backend:
                manager._status(profile, backend, exc.code.lower(), error=exc.public())
            result.append({**item, "state": exc.code.lower()})
        except (KeyError, ValueError):
            result.append({**item, "state": "invalid_configuration"})
    return {"enabled": True, "checked": result}


async def watch(paths, registry, *, tick_seconds=60):
    import asyncio
    import sys
    if tick_seconds < 60:
        raise UsageError("本地检查节拍至少 60 秒；平台请求仍受每天一次的到期间隔限制")
    cycles = 0
    while policy(paths).get("enabled", False):
        result = await check_due(paths, registry)
        cycles += 1
        print(f"[health] cycle={cycles} checked={len(result['checked'])}", file=sys.stderr, flush=True)
        await asyncio.sleep(tick_seconds)
    return {"enabled": False, "cycles": cycles, "skipped": "disabled"}
