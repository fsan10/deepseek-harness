"""Thin entry adapter; business workflows are registered platform services."""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import asdict
from pathlib import Path

from .. import __version__
from ..core.contracts import Period, ReportRequest
from ..core.errors import UsageError
from ..core.registry import load_symbol
from ..runtime.auth import AuthManager, profile_binding
from ..runtime.engine import Engine
from ..runtime.runs import Run, public_state
from ..runtime.sessions import session_key
from ..runtime.storage import Paths, atomic_json, file_lock, read_json


async def dispatch(args, registry):
    if args.env_file:
        os.environ["COMMERCE_ENV_FILE"] = str(Path(args.env_file).resolve())
    if args.legacy_root:
        os.environ["COMMERCE_LEGACY_ROOT"] = str(Path(args.legacy_root).resolve())
    paths = Paths(args.runtime_dir)
    if args.version:
        return {"version": __version__}
    if args.command == "platforms":
        return registry.public(args.platform)
    if args.command == "schema":
        return registry.schema(args.platform)
    if args.command == "doctor":
        dependencies = {name: importlib.util.find_spec(name) is not None for name in
            ("httpx", "playwright", "requests", "websocket", "cryptography", "psycopg2", "openpyxl", "msoffcrypto", "xlrd", "olefile")}
        handlers = []
        for platform in registry.platforms.values():
            for report in platform.reports:
                try:
                    load_symbol(report.handler)
                    handlers.append({"platform": report.platform, "kind": report.kind, "backend": report.backend, "available": True})
                except (ImportError, AttributeError):
                    handlers.append({"platform": report.platform, "kind": report.kind, "backend": report.backend, "available": False})
        return {"version": __version__, "windows_dpapi": os.name == "nt", "dependencies": dependencies,
                "runtime_dir": str(paths.root), "health_default": False, "reports": handlers,
                "legacy_downloads_modified": False, "ingest_on_download": False}
    if args.command == "profiles":
        if args.action == "sync":
            from ..integrations.legacy.profiles import list_profiles
            value = {p.name: asdict(p) for p in list_profiles()}
            atomic_json(paths.file("config", "profiles"), value)
        return list(read_json(paths.file("config", "profiles"), {}).values())
    if args.command == "health":
        from ..runtime.health import check_due, policy, set_policy, watch
        if args.action == "policy":
            return policy(paths)
        if args.action == "configure":
            if args.profile:
                registry.backend(args.platform or "", args.backend or "")
            return set_policy(paths, enabled=args.enabled == "true" if args.enabled is not None else None,
                profile=args.profile, platform=args.platform, backend=args.backend, interval=args.interval_minutes)
        return await watch(paths, registry, tick_seconds=args.tick_seconds) if args.action == "watch" else await check_due(paths, registry)
    engine = Engine(paths, registry)
    if args.command == "batch":
        from ..runtime.batch import run_batch
        if args.action == "run" and not args.plan or args.action == "resume" and not args.id:
            raise UsageError("批量执行需要 --plan，续跑需要 --id")
        return await run_batch(engine, Path(args.plan) if args.plan else None,
            resume=args.id if args.action == "resume" else None, recover=not args.no_login_recovery)
    if args.command == "run":
        run = Run.load(paths, args.id)
        if args.action == "status":
            return public_state(run.state)
        return await engine.execute(ReportRequest.restore(run.state["request"]), resume=run.id, recover=not args.no_login_recovery,
            human_timeout=args.human_timeout)
    if not getattr(args, "platform_id", None) or not args.resource or not args.action:
        raise UsageError("命令不完整，请使用 --help")
    platform = registry.platform(args.platform_id)
    if args.resource == "report":
        if args.action == "list":
            return [s.public() for s in platform.reports if args.command != "qianchuan" or s.backend == "qianchuan"]
        spec = registry.report(platform.id, args.kind, args.backend)
        period = Period.parse(day=args.date, month=args.month, start=args.start, end=args.end, default=spec.default_period)
        request = ReportRequest(platform.id, spec.kind, spec.backend, args.profile, period,
            timeout=args.timeout, poll_interval=args.poll_interval, account_id=args.account_id)
        return await engine.execute(request, recover=not args.no_login_recovery, human_timeout=args.human_timeout)
    manager = AuthManager(paths, registry)
    profile = profile_binding(paths, args.profile, platform.id)
    backend = registry.backend(platform.id, args.backend)
    from ..integrations.legacy.locking import legacy_browser_lock
    key = session_key(profile.id, profile.platform, backend.id)
    with file_lock(paths.file("locks", key, ".lock")), legacy_browser_lock():
        if args.action == "login":
            return await manager.login(profile, backend, account_id=args.account_id, already_locked=True)
        if args.action == "status":
            return await manager.check(profile, backend, recover=False, already_locked=True)
        manager.store.delete(key)
        manager._status(profile, backend, "logged_out")
        return {"profile": profile.name, "backend": backend.id, "local_session_removed": True}
