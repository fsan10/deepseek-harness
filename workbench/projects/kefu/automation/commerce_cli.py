"""同一平台核心的 CLI 入口。stdout 仅一个 JSON 信封；登录日志写 stderr。"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from .review_config import load_runtime_env
from .review_errors import AuthRequired, ContractError, ReviewError


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ContractError("命令参数无效，请运行 commerce schema 查看用法")


def parser():
    root = JsonArgumentParser(prog="commerce", description="客服商家 WebAPI CLI；真实浏览器仅用于显式登录")
    root.add_argument("--platform", default="douyin")
    root.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("platforms"); commands.add_parser("schema")
    profiles = commands.add_parser("profiles"); profiles.add_argument("--refresh", action="store_true")
    auth = commands.add_parser("auth").add_subparsers(dest="action", required=True)
    auth.add_parser("login").add_argument("--profile", required=True)
    status = auth.add_parser("status")
    scope = status.add_mutually_exclusive_group()
    scope.add_argument("--profile"); scope.add_argument("--all", action="store_true")
    auth.add_parser("logout").add_argument("--profile", required=True)
    reviews = commands.add_parser("reviews").add_subparsers(dest="action", required=True)
    fetch = reviews.add_parser("fetch"); fetch.add_argument("--profile", required=True)
    fetch.add_argument("--from", dest="start"); fetch.add_argument("--to", dest="end")
    collect = reviews.add_parser("collect"); collect.add_argument("--profile")
    collect.add_argument("--from", dest="start"); collect.add_argument("--to", dest="end"); collect.add_argument("--input-stdin", action="store_true")
    reviews.add_parser("status").add_argument("--run-id")
    reviews.add_parser("retry").add_argument("--run-id", required=True)
    from .metric_cli import add_parser
    add_parser(commands)
    return root


def cached_profiles(db):
    return [dict(row) for row in db.execute("SELECT * FROM review_profiles ORDER BY excluded,shop_name,profile_name")]


def choose_profile(db, name: str, *, discover=False):
    matches = [p for p in cached_profiles(db) if name in (p["profile_id"], p["profile_name"], p["shop_name"])]
    if not matches and discover:
        from .douyin_reviews import list_profiles
        from .review_worker import sync_profiles
        sync_profiles(db, list_profiles())
        matches = [p for p in cached_profiles(db) if name in (p["profile_id"], p["profile_name"], p["shop_name"])]
    if len(matches) != 1:
        raise ContractError("店铺不存在或名称不唯一，请先运行 commerce profiles --refresh 并提供完整 profile 名称")
    if matches[0]["excluded"]:
        raise ContractError("该店铺已关店，已排除")
    return matches[0]


def period(start, end, lookback=1):
    from .douyin_reviews import CN
    try:
        last = date.fromisoformat(end) if end else datetime.now(CN).date() - timedelta(days=1)
        first = date.fromisoformat(start) if start else last - timedelta(days=lookback - 1)
        if first > last or last >= datetime.now(CN).date() or (last - first).days > 365:
            raise ValueError()
        return first, last
    except (TypeError, ValueError):
        raise ContractError("请选择截至昨天、最多 366 天的有效日期范围") from None


def enqueue(db, body: dict):
    db.execute("BEGIN IMMEDIATE")
    try:
        if db.execute("SELECT id FROM review_runs WHERE status IN ('queued','running')").fetchone():
            raise ContractError("已有采集任务正在等待或运行，请等待完成")
        if body.get("retryId"):
            run_id = body["retryId"]
            if not isinstance(run_id, str) or len(run_id) > 100:
                raise ContractError("重试任务标识无效")
            row = db.execute("SELECT status FROM review_runs WHERE id=?", (run_id,)).fetchone()
            if not row or row[0] not in ("failed", "partial", "needs_human"):
                raise ContractError("这条任务无需重试")
            db.execute("UPDATE review_run_shops SET status='pending',message='',finished_at=NULL WHERE run_id=? AND status NOT IN ('success','no_data','skipped')", (run_id,))
            db.execute("UPDATE review_runs SET status='queued',message='等待重试未完成店铺',finished_at=NULL WHERE id=?", (run_id,))
        else:
            lookback = db.execute("SELECT lookback_days FROM review_settings WHERE id=1").fetchone()[0]
            start, end = period(body.get("from"), body.get("to"), lookback)
            ids = body.get("profileIds", [])
            if not isinstance(ids, list) or len(ids) > 100 or any(not isinstance(i, str) or len(i) > 100 for i in ids):
                raise ContractError("店铺参数无效")
            ids = list(dict.fromkeys(ids))
            known = {p["profile_id"] for p in cached_profiles(db) if not p["excluded"]}
            if not known or any(i not in known for i in ids):
                raise ContractError("请先同步店铺，或检查已选择店铺是否关店")
            run_id = str(uuid.uuid4())
            db.execute("INSERT INTO review_runs(id,trigger_type,start_date,end_date,profile_ids,created_at) VALUES(?,'manual',?,?,?,?)",
                       (run_id, start.isoformat(), end.isoformat(), json.dumps(ids), datetime.now(timezone.utc).isoformat()))
        db.commit()
        return {"id": run_id, "status": "queued"}
    except Exception:
        db.rollback(); raise


async def dispatch(args):
    from .review_platforms import PLATFORMS, platform_info
    if args.command == "platforms": return {"platforms": list(PLATFORMS.values())}
    if args.command == "schema":
        return {"version": 2, "platforms": PLATFORMS, "commands": ["profiles [--refresh]", "auth login --profile NAME", "auth status [--profile NAME|--all]", "auth logout --profile NAME", "reviews fetch --profile NAME [--from YYYY-MM-DD --to YYYY-MM-DD]", "reviews collect [--profile NAME] [--from YYYY-MM-DD --to YYYY-MM-DD]", "reviews status [--run-id ID]", "reviews retry --run-id ID", "metrics profiles", "metrics auth login --profile ID", "metrics auth status --profile ID", "--platform PLATFORM reception fetch --profile ID [--date YYYY-MM-DD]", "--platform PLATFORM reception collect [--profile ID] [--from YYYY-MM-DD --to YYYY-MM-DD]", "--platform PLATFORM score fetch --profile ID", "--platform PLATFORM score collect [--profile ID]", "reception status [--run-id ID]", "score status [--run-id ID]", "reception retry --run-id ID", "score retry --run-id ID"],
                "auth": {"storage": "Windows user DPAPI", "browser": "explicit_login_only", "check": "shop_info_api", "poll_interval_default_minutes": 5},
                "output": {"stdout": "one_json_envelope", "stderr": "logs", "error_fields": ["code", "recoverable", "recovery_action"]}}
    if args.command in ("metrics", "reception", "score"):
        from .metric_cli import dispatch as metric_dispatch
        return await metric_dispatch(args)
    platform_info(args.platform)
    if args.platform not in ("douyin", "抖音"):
        from .review_errors import NotSupported
        raise NotSupported("此入口仅用于抖音评论；多平台指标请使用 reception、score 或 metrics 命令")
    from .review_worker import connect, sync_profiles
    from .douyin_reviews import list_profiles, collect_shop
    db = connect()
    try:
        if args.command == "profiles":
            if args.refresh: sync_profiles(db, await asyncio.to_thread(list_profiles))
            return {"profiles": cached_profiles(db)}
        if args.command == "auth":
            from .review_auth import login_profile, check_profile, record_state
            if args.action == "login":
                return await asyncio.wait_for(login_profile(choose_profile(db, args.profile, discover=True), db=db), timeout=300)
            if args.action == "logout":
                from .review_session_store import SessionStore
                profile = choose_profile(db, args.profile)
                SessionStore().delete(profile["profile_id"])
                record_state(profile["profile_id"], "auth_required", "本地会话已注销", "AUTH_REQUIRED", db=db)
                return {"profile_id": profile["profile_id"], "state": "auth_required"}
            profiles = [choose_profile(db, args.profile)] if args.profile else [p for p in cached_profiles(db) if not p["excluded"]]
            result = []
            for profile in profiles:
                try:
                    result.append(await check_profile(profile, db=db))
                except ReviewError as exc:
                    result.append({"profile_id": profile["profile_id"], "shop_name": profile["shop_name"], "state": "auth_required" if isinstance(exc, AuthRequired) else "needs_human" if exc.code == "NEEDS_HUMAN" else "error", "code": exc.code, "message": str(exc), "recovery_action": exc.recovery_action})
            return {"profiles": result, "valid": bool(result) and all(p["state"] == "valid" for p in result)}
        if args.action == "fetch":
            profile = choose_profile(db, args.profile)
            start, end = period(args.start, args.end)
            from .metric_auth import with_login_recovery
            rows = await with_login_recovery(db, profile, lambda: collect_shop(profile, start, end, lambda message: print(message, file=sys.stderr)))
            return {"profile_id": profile["profile_id"], "from": start.isoformat(), "to": end.isoformat(), "transport": "direct_http", "total": len(rows), "rows": rows}
        if args.action == "collect":
            try:
                body = json.load(sys.stdin) if args.input_stdin else {"from": args.start, "to": args.end, "profileIds": [choose_profile(db, args.profile)["profile_id"]] if args.profile else []}
            except ValueError:
                raise ContractError("请求需要有效 JSON 对象") from None
            if not isinstance(body, dict): raise ContractError("请求需要 JSON 对象")
            return enqueue(db, body)
        if args.action == "retry": return enqueue(db, {"retryId": args.run_id})
        if args.run_id:
            row = db.execute("SELECT * FROM review_runs WHERE id=?", (args.run_id,)).fetchone()
            if not row: raise ContractError("找不到该采集任务")
            return {"run": {**dict(row), "shops": [dict(p) for p in db.execute("SELECT * FROM review_run_shops WHERE run_id=? ORDER BY shop_name", (args.run_id,))]}}
        return {"runs": [dict(r) for r in db.execute("SELECT * FROM review_runs ORDER BY created_at DESC LIMIT 10")]}
    finally:
        db.close()


async def run_command(args):
    watcher = None
    if args.parent_pid:
        from .review_worker import watch_parent
        watcher = asyncio.create_task(watch_parent(args.parent_pid, asyncio.current_task()))
    try:
        return await dispatch(args)
    finally:
        if watcher:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError): await watcher


def main(argv=None):
    load_runtime_env()
    try:
        args = parser().parse_args(argv)
        # 共享登录模块的普通日志不得污染 stdout JSON。
        with contextlib.redirect_stdout(sys.stderr):
            data = asyncio.run(run_command(args))
        ok = data.get("valid", True)
        failure = next((p for p in data.get("profiles", []) if p.get("state") != "valid"), {})
        error = None if ok else {"code": failure.get("code", "AUTH_REQUIRED"), "message": failure.get("message", "未找到可检查的店铺，请先同步店铺并登录"), "recoverable": True, "recovery_action": failure.get("recovery_action", "commerce profiles --refresh")}
        result = {"ok": ok, "data": data, "error": error, "hints": {"transport": "direct_http"}}
    except asyncio.CancelledError:
        result = {"ok": False, "data": None, "error": {"code": "CANCELLED", "message": "网页服务已退出，操作已取消", "recoverable": True, "recovery_action": "重新启动服务后重试"}, "hints": {}}
    except TimeoutError:
        result = {"ok": False, "data": None, "error": {"code": "LOGIN_TIMEOUT", "message": "登录处理超时，请检查对应浏览器后重新登录", "recoverable": True, "recovery_action": "commerce auth login --profile <店铺profile>"}, "hints": {}}
    except ReviewError as exc:
        result = {"ok": False, "data": None, "error": {"code": exc.code, "message": str(exc), "recoverable": exc.recoverable, "recovery_action": exc.recovery_action}, "hints": {}}
    except Exception as exc:
        result = {"ok": False, "data": None, "error": {"code": "INTERNAL_ERROR", "message": f"操作失败（{type(exc).__name__}），请检查运行环境", "recoverable": False, "recovery_action": "检查环境后重试"}, "hints": {}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
