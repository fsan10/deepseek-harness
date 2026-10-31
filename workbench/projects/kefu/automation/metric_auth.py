"""唯一允许连接 Cloak 浏览器的指标认证入口。只处理登录和提取会话。"""
from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs

from .collection_alerts import flush_alerts, queue_alert, shared_relay_environment
from .douyin_reviews import shared_modules
from .metric_collect import SHOP_IDENTITY_ALIASES, check_identity, client_for_profile, session_store
from .metric_http import MetricHttpSession
from .metric_profiles import PLATFORMS
from .review_errors import AuthRequired, ContractError, HumanRequired, LoginFailed, ReviewError


def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_auth(db, profile, state, message, code="", identity=None, captured_at=None):
    identity = identity or {}
    previous = db.execute("SELECT state,error_code FROM metric_auth_status WHERE profile_id=?", (profile["profile_id"],)).fetchone()
    with db:
        db.execute("""INSERT INTO metric_auth_status(profile_id,state,message,error_code,actual_shop_name,actual_shop_id,checked_at,captured_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET state=excluded.state,message=excluded.message,
            error_code=excluded.error_code,actual_shop_name=CASE WHEN excluded.actual_shop_name='' THEN metric_auth_status.actual_shop_name ELSE excluded.actual_shop_name END,
            actual_shop_id=CASE WHEN excluded.actual_shop_id='' THEN metric_auth_status.actual_shop_id ELSE excluded.actual_shop_id END,
            checked_at=excluded.checked_at,captured_at=COALESCE(excluded.captured_at,metric_auth_status.captured_at)""",
            (profile["profile_id"], state, message, code, identity.get("shop_name", ""), identity.get("shop_id", ""), now(), captured_at))
    # 服务日志与异常记录共用同一份事件：失效写一条待处理，恢复后标记已恢复，
    # 再次失效才产生新事件，避免同类异常反复刷屏。
    from .collection_events import record, recover_auth
    event_id = None
    if state in ("auth_required", "needs_human", "error"):
        event_id = record(db, dedupe_key="auth:" + profile["profile_id"], source="service",
               category={"auth_required": "auth_required", "needs_human": "needs_human", "error": "check_error"}[state],
               severity="danger" if state == "auth_required" else "warning",
               message=message, profile_id=profile["profile_id"])
    elif state == "valid":
        recover_auth(db, profile["profile_id"])
    # 普通会话失效先自动恢复；只有确需人工或登录最终失败才发群通知。
    if (state == "needs_human" or code in ("LOGIN_FAILED", "LOGIN_TIMEOUT")) and (not previous or (previous["state"], previous["error_code"]) != (state, code)):
        queue_alert(db, "auth:" + profile["profile_id"] + ":" + code + ":" + now(), profile["profile_id"], code,
                    f"客服数据采集 · {PLATFORMS[profile['platform']]['name']} · {profile['expected_shop_name']}\n{message}",
                    event_id=event_id)


async def with_login_recovery(db, profile, operation, *, store=None):
    """只恢复明确失效的会话，换新会话后重试同一 HTTP 操作一次。"""
    from .collection_accounts import require_available
    require_available(db, profile["profile_id"])
    try:
        return await operation()
    except AuthRequired:
        canonical = dict(db.execute("SELECT * FROM metric_profiles WHERE profile_id=?", (profile["profile_id"],)).fetchone())
        record_auth(db, canonical, "logging_in", "HTTP 会话失效，正在自动登录并更新会话")
        await login_profile(db, canonical, store=store, automatic=True)
        require_available(db, profile["profile_id"])
        try:
            return await operation()
        except AuthRequired:
            failure = LoginFailed("重新登录后 HTTP 会话仍无效，成功检查点已保留")
            record_auth(db, canonical, "error", str(failure), failure.code)
            raise failure from None


async def check_profile(db, profile, *, store=None):
    from .collection_accounts import require_available
    require_available(db, profile["profile_id"])
    try:
        async def inspect():
            async with client_for_profile(profile, store=store) as client:
                return await check_identity(client)
        identity = await with_login_recovery(db, profile, inspect, store=store)
        record_auth(db, profile, "valid", "HTTP 登录有效", identity=identity)
        return identity
    except ReviewError as exc:
        state = "auth_required" if isinstance(exc, AuthRequired) else "needs_human" if isinstance(exc, HumanRequired) else "error"
        record_auth(db, profile, state, str(exc), exc.code)
        raise


async def login_challenge_visible(page):
    # 只检查登录页面可见的验证控件，不读取或输出验证码及页面内容。
    selectors = '[id*="captcha" i]:visible, [class*="captcha" i]:visible, [id*="verify-slider" i]:visible, [id$="_n1z"]:visible, input[placeholder*="验证码"]:visible, input[placeholder*="校验码"]:visible, input[autocomplete="one-time-code"]:visible, iframe[src*="captcha" i]:visible, iframe[src*="punish" i]:visible'
    for surface in [page, *page.frames]:
        try:
            if await surface.locator(selectors).first.is_visible():
                return True
        except Exception:
            continue
    return False


async def login_credentials(context, page, profile, captured):
    credentials = {"version": 1, "session_id": uuid.uuid4().hex, "profile_id": profile["profile_id"], "platform": profile["platform"],
                   "captured_at": now(), "user_agent": await page.evaluate("navigator.userAgent"),
                   "cookies": await context.cookies(), **captured}
    async with MetricHttpSession(profile, credentials) as client:
        identity = await check_identity(client)
        return {**client.snapshot(), "identity": identity}


async def await_login(db, profile, page, context, captured, operation, *, timeout=300):
    """登录时监听验证；通知后持续提取新会话，人工完成后自动续采。"""
    task = None
    manual = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while loop.time() < deadline:
            from .collection_accounts import require_available
            require_available(db, profile["profile_id"])
            if not manual and await login_challenge_visible(page):
                manual = True
                deadline = loop.time() + timeout
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                record_auth(db, profile, "needs_human", "登录遇到验证码或滑块，请在对应 profile 完成验证；完成后自动继续，等待上限 5 分钟", "LOGIN_VERIFICATION_REQUIRED")
                await flush_alerts(db)
            if task is None and not manual:
                task = asyncio.create_task(operation())
            if task and task.done() and not task.cancelled():
                error = task.exception()
                if error and not manual:
                    if isinstance(error, HumanRequired) and not isinstance(error, AuthRequired):
                        manual = True
                        deadline = loop.time() + timeout
                        record_auth(db, profile, "needs_human", "登录需要人工验证，请处理对应 profile；完成后自动继续，等待上限 5 分钟", "LOGIN_VERIFICATION_REQUIRED")
                        await flush_alerts(db)
                    else:
                        if isinstance(error, ContractError): raise error
                        raise LoginFailed("自动登录未完成，请检查账号保存状态与平台登录页面") from None
            if manual or task and task.done():
                try:
                    credentials = await login_credentials(context, page, profile, captured)
                    return credentials
                except AuthRequired:
                    if not manual:
                        raise LoginFailed("自动登录后尚未取得有效的 HTTP 会话") from None
            # Event.wait 不会因平台登录模块内部的 sleep 被 mock 而忙循环。
            remaining = min(1, max(0, deadline - loop.time()))
            if task and not task.done():
                await asyncio.wait({task}, timeout=remaining)
            else:
                await asyncio.sleep(remaining)
        failure = LoginFailed("人工验证等待超过 5 分钟，登录失败；已保留对应 profile 和成功检查点" if manual else "自动登录超过 5 分钟，登录失败；成功检查点已保留")
        failure.code = "LOGIN_TIMEOUT"
        failure.preserve_profile = manual
        raise failure
    except Exception as exc:
        if manual:
            exc.preserve_profile = True
        raise
    finally:
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@contextlib.asynccontextmanager
async def login_browser_scope(db, profile):
    from .review_worker import BrowserLockBusy, browser_lock_scope, create_browser_lock
    while True:
        scope = browser_lock_scope(create_browser_lock("metric-auth-" + profile["profile_id"], logging.getLogger("kefu.metrics.auth")))
        try:
            scope.__enter__()
            break
        except BrowserLockBusy:
            record_auth(db, profile, "logging_in", "等待报表或其他登录任务释放浏览器互斥锁")
            from .collection_accounts import require_available
            require_available(db, profile["profile_id"])
            await asyncio.sleep(2)
    try:
        yield
    finally:
        scope.__exit__(None, None, None)


async def login_profile(db, profile, *, store=None, automatic=False):
    from .collection_accounts import require_available
    require_available(db, profile["profile_id"])
    if profile["excluded"] or not profile.get("expected_shop_name"):
        raise ContractError("该账号已排除或备注中缺少店铺名称，禁止启动 profile")
    from playwright.async_api import async_playwright
    Client, resolve, dy_goto, _ = shared_modules()
    connection = None; preserve = False
    captured = {}
    if automatic:
        # 自动恢复不能借重新提取 Cookie 接受同名但不同店铺的稳定 ID。
        previous = db.execute("SELECT actual_shop_id FROM metric_auth_status WHERE profile_id=?", (profile["profile_id"],)).fetchone()
        if previous and previous[0]: captured["identity"] = {"shop_id": previous[0]}
        if "identity" not in captured:
            try:
                identity = (store or session_store()).load(profile["profile_id"]).get("identity")
                if identity and identity.get("shop_id"): captured["identity"] = identity
            except AuthRequired:
                pass
    try:
        async with login_browser_scope(db, profile):
            record_auth(db, profile, "logging_in", "正在首页检查登录状态")
            connection = await asyncio.to_thread(resolve, profile_name=profile["profile_name"])
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(connection.endpoint)
                if not browser.contexts: raise ContractError("profile 没有可用上下文")
                context = browser.contexts[0]
                before = set(context.pages)
                page = await context.new_page()
                def capture_auth_request(request):
                    parsed = urlsplit(request.url)
                    # 仅保存 MTop 客户端标识；动态签名从不复用，由 HTTP 请求重新生成。
                    if parsed.hostname == "h5api.m.taobao.com" and parsed.path.startswith("/h5/"):
                        key = parse_qs(parsed.query).get("appKey", [None])[0]
                        if key: captured["mtop_app_key"] = key
                page.on("request", capture_auth_request)
                try:
                    home = PLATFORMS[profile["platform"]]["home"]
                    await page.goto(home, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(2)
                    async def perform_login():
                        # 共享模块可能输出诊断；截留在内存中，避免日志带出敏感链接。
                        with shared_relay_environment(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            if profile["platform"] == "douyin":
                                await dy_goto(page, home, profile["expected_shop_name"], company=profile["company"], timeout=15)
                            elif profile["platform"] == "pinduoduo":
                                from scripts.auto_download.playwright.pinduoduo_login import ensure_pinduoduo_login
                                await ensure_pinduoduo_login(context, platform="拼多多", company=profile["company"], shop=profile["expected_shop_name"])
                            elif profile["platform"] == "tmall":
                                from scripts.auto_download.playwright.login_extensions.tmall_finance_login import ensure_tmall_login
                                await ensure_tmall_login(page)
                            elif profile["platform"] == "xiaohongshu":
                                from scripts.auto_download.playwright.xiaohongshu_download_common import ensure_logged_in
                                await ensure_logged_in(page)
                            elif profile["platform"] == "kuaishou":
                                from scripts.auto_download.playwright.kuaishou_order_download import ensure_kuaishou_login
                                shop = SHOP_IDENTITY_ALIASES.get(("kuaishou", profile["expected_shop_name"]), profile["expected_shop_name"])
                                await ensure_kuaishou_login(page, shop)
                            elif profile["platform"] == "jd":
                                from scripts.auto_download.playwright.jd_order_download import ensure_login
                                await ensure_login(page)
                    if automatic:
                        credentials = await await_login(db, profile, page, context, captured, perform_login)
                    else:
                        await perform_login()
                        await asyncio.sleep(3)
                        credentials = await login_credentials(context, page, profile, captured)
                    identity = credentials["identity"]
                    require_available(db, profile["profile_id"])
                    (store or session_store()).save(profile["profile_id"], credentials)
                    record_auth(db, profile, "valid", "登录完成，独立 HTTP 已核对店铺身份", identity=identity, captured_at=credentials["captured_at"])
                    return identity
                except asyncio.CancelledError:
                    preserve = await login_challenge_visible(page)
                    record_auth(db, profile, "error", "登录操作已中断，成功检查点已保留", "AUTH_INTERRUPTED")
                    raise
                except Exception as exc:
                    preserve = (isinstance(exc, HumanRequired) and not isinstance(exc, AuthRequired)) or getattr(exc, "preserve_profile", False)
                    if isinstance(exc, ReviewError): raise
                    if automatic: raise LoginFailed("自动登录运行异常，请检查平台登录状态与运行环境") from None
                    raise HumanRequired("首页登录尚未完成，请在对应 profile 完成验证后重新点击登录") from None
                finally:
                    if not preserve:
                        for owned in list(context.pages):
                            if owned not in before and not owned.is_closed():
                                with contextlib.suppress(Exception): await owned.close()
    except ReviewError as exc:
        record_auth(db, profile, "auth_required" if isinstance(exc, AuthRequired) else "needs_human" if isinstance(exc, HumanRequired) else "error", str(exc), exc.code)
        if isinstance(exc, LoginFailed): await flush_alerts(db)
        raise
    except Exception:
        if not automatic: raise
        failure = LoginFailed("无法完成自动登录，请检查 profile 连接和平台登录环境")
        record_auth(db, profile, "error", str(failure), failure.code)
        await flush_alerts(db)
        raise failure from None
    finally:
        if connection and connection.started_by_this_run and not preserve:
            with contextlib.suppress(Exception):
                client = Client(os.environ.get("CLOAK_MCP_URL", "http://127.0.0.1:19610/mcp"), 15)
                await asyncio.to_thread(client.initialize)
                await asyncio.to_thread(client.call, "stop_profile", {"id": connection.profile_id})


async def poll_auth_status(db):
    """唯一的后台认证轮询，由指标 worker 持有的互斥锁保证不重复检查。"""
    minutes = db.execute("SELECT auth_poll_minutes FROM metric_service_settings WHERE id=1").fetchone()[0]
    before = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    profile = db.execute("""SELECT p.* FROM metric_profiles p LEFT JOIN metric_auth_status a ON a.profile_id=p.profile_id
        WHERE p.excluded=0 AND p.disabled=0 AND p.auth_check_enabled=1
        AND (a.profile_id IS NULL OR (a.state IN('valid','error','auth_required')
            AND a.error_code NOT IN('LOGIN_FAILED','LOGIN_TIMEOUT') AND a.checked_at<?))
        ORDER BY COALESCE(a.checked_at,'') LIMIT 1""", (before,)).fetchone()
    if profile:
        try:
            await check_profile(db, dict(profile))
        except ReviewError:
            pass
        except Exception:
            record_auth(db, dict(profile), "error", "登录状态检查失败，请检查运行环境", "AUTH_CHECK_ERROR")
