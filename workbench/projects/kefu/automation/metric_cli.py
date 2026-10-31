"""指标 CLI 适配，业务逻辑由采集核心和队列共用。"""
from __future__ import annotations

import asyncio
import json
import re
import sys

from .metric_profiles import PLATFORMS, choose_profile, list_profiles, platform_key, sync_profiles
from .metric_worker import connect, enqueue, now, selected_profiles
from .review_errors import ContractError


def add_parser(commands):
    root = commands.add_parser("metrics").add_subparsers(dest="metric_command", required=True)
    profiles = root.add_parser("profiles")
    profiles.add_argument("--refresh", action="store_true"); profiles.add_argument("--input-stdin", action="store_true")
    for name in ("collect", "mapping", "configure", "batch-configure", "settings", "availability", "service", "plan-order"):
        root.add_parser(name).add_argument("--input-stdin", action="store_true")
    auth = root.add_parser("auth").add_subparsers(dest="metric_action", required=True)
    for name in ("login", "status"):
        auth.add_parser(name).add_argument("--profile", required=True)
    notifications = root.add_parser("notifications").add_subparsers(dest="metric_action", required=True)
    notifications.add_parser("get")
    notifications.add_parser("save").add_argument("--input-stdin", action="store_true")
    for kind in ("reception", "score"):
        sub = commands.add_parser(kind).add_subparsers(dest="action", required=True)
        fetch = sub.add_parser("fetch"); fetch.add_argument("--profile", required=True); fetch.add_argument("--date")
        collect = sub.add_parser("collect"); collect.add_argument("--profile"); collect.add_argument("--from", dest="start"); collect.add_argument("--to", dest="end")
        sub.add_parser("status").add_argument("--run-id")
        sub.add_parser("retry").add_argument("--run-id", required=True)


def input_body(args):
    try: body = json.load(sys.stdin) if getattr(args, "input_stdin", False) else {}
    except ValueError: raise ContractError("请求需要有效 JSON") from None
    if not isinstance(body, dict): raise ContractError("请求需要 JSON 对象")
    return body


def active_runs(db):
    return db.execute("SELECT 1 FROM metric_runs WHERE status IN('queued','running') UNION ALL SELECT 1 FROM review_runs WHERE status IN('queued','running') LIMIT 1").fetchone()


def save_settings(db, body):
    kind = body.get("kind")
    if kind not in ("reception", "score"): raise ContractError("采集类型无效")
    for key, maximum in (("frequency_days", 365), ("lookback_days", 31)):
        value = body.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ContractError(f"{key} 必须是 1 至 {maximum} 的整数")
    poll = body.get("auth_poll_minutes")
    if poll is not None and (isinstance(poll, bool) or not isinstance(poll, int) or not 1 <= poll <= 1440):
        raise ContractError("auth_poll_minutes 必须是 1 至 1440 的整数")
    if not isinstance(body.get("enabled"), bool) or not isinstance(body.get("run_at"), str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", body["run_at"]):
        raise ContractError("定时启用状态或执行时间无效")
    if body["enabled"]: selected_profiles(db, kind, [])
    previous = db.execute("SELECT * FROM metric_collection_settings WHERE kind=?", (kind,)).fetchone()
    keep = previous["enabled"] == int(body["enabled"]) and previous["frequency_days"] == body["frequency_days"] and previous["run_at"] == body["run_at"]
    with db:
        db.execute("UPDATE metric_collection_settings SET enabled=?,frequency_days=?,lookback_days=?,run_at=?,next_run_at=?,updated_at=? WHERE kind=?",
            (int(body["enabled"]), body["frequency_days"], body["lookback_days"], body["run_at"], previous["next_run_at"] if keep and body["enabled"] else None, now(), kind))
        if poll is not None:
            db.execute("UPDATE metric_service_settings SET auth_poll_minutes=? WHERE id=1", (poll,))
    return {"settings": dict(db.execute("SELECT * FROM metric_collection_settings WHERE kind=?", (kind,)).fetchone())}


async def dispatch(args):
    db = connect()
    try:
        if args.command in ("reception", "score"):
            platform = platform_key(args.platform)
            if args.action in ("fetch", "collect"):
                profile = choose_profile(db, args.profile) if args.profile else None
                if profile and profile["platform"] != platform: raise ContractError("profile 与 --platform 不一致")
                if args.action == "fetch":
                    from .collection_accounts import require_available
                    require_available(db, profile["profile_id"], args.command)
                    from .metric_collect import fetch_metrics
                    from .metric_worker import period
                    day = period(args.date, args.date)[0] if args.command == "reception" else None
                    from .metric_auth import with_login_recovery
                    return await with_login_recovery(db, profile, lambda: fetch_metrics(profile, args.command, day))
                ids = [profile["profile_id"]] if profile else [r[0] for r in db.execute("SELECT profile_id FROM metric_profiles WHERE platform=? AND excluded=0 AND disabled=0 AND shop_name<>'' AND collect_" + args.command + "=1 AND " + args.command + "_enabled=1", (platform,))]
                if not ids: raise ContractError("该平台没有可采集店铺")
                return enqueue(db, {"kind": args.command, "profileIds": ids, "from": args.start, "to": args.end})
            if args.action == "retry": return enqueue(db, {"kind": args.command, "action": "retry", "runId": args.run_id})
            query = "SELECT * FROM metric_runs WHERE kind=?" + (" AND id=?" if args.run_id else "") + " ORDER BY created_at DESC LIMIT 20"
            return {"runs": [dict(r) for r in db.execute(query, (args.command, args.run_id) if args.run_id else (args.command,))]}
        body = input_body(args)
        command = args.metric_command
        if command == "plan-order":
            from .collection_queue import save_order
            return save_order(db, body.get("plan_order"))
        if command == "availability":
            from .collection_accounts import set_availability
            return set_availability(db, body.get("profileId"), body.get("disabled"))
        if command == "batch-configure":
            from .collection_accounts import batch_configure
            return batch_configure(db, body, body.get("shops", []))
        if command == "service":
            value = body.get("auth_poll_minutes")
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440:
                raise ContractError("登录检查间隔必须为 1 至 1440 分钟的整数")
            with db: db.execute("UPDATE metric_service_settings SET auth_poll_minutes=? WHERE id=1", (value,))
            return {"auth_poll_minutes": value}
        if command == "notifications":
            from .collection_alerts import public_config, save_config
            return {"config": public_config() if args.metric_action == "get" else save_config(body)}
        if command == "settings": return save_settings(db, body)
        if command == "profiles":
            if args.refresh:
                if active_runs(db): raise ContractError("请等待当前采集任务结束后再同步店铺")
                shops = body.get("shops")
                if not isinstance(shops, list): raise ContractError("同步店铺需要数据台的有效店铺范围，请从后台同步")
                sync_profiles(db, await asyncio.to_thread(list_profiles), shops)
            return {"profiles": [dict(p) for p in db.execute("SELECT * FROM metric_profiles ORDER BY excluded,platform,profile_name")]}
        if command in ("mapping", "configure"):
            from .collection_accounts import configure_profile
            return configure_profile(db, body, body.get("shops", []))
        if command == "collect": return enqueue(db, body)
        if command == "auth":
            from .metric_auth import login_profile, check_profile
            profile = choose_profile(db, args.profile)
            if args.metric_action == "login":
                try:
                    return await asyncio.wait_for(login_profile(db, profile), timeout=300)
                except TimeoutError:
                    from .metric_auth import record_auth
                    from .review_errors import HumanRequired
                    message = "登录处理超时，请在对应 profile 完成验证后重新点击登录"
                    record_auth(db, profile, "needs_human", message, "LOGIN_TIMEOUT")
                    raise HumanRequired(message) from None
            return await check_profile(db, profile)
        raise ContractError("不支持的指标命令")
    finally:
        db.close()
