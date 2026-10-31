"""The only production module allowed to use a browser: authentication only."""
from __future__ import annotations

import asyncio
import contextlib
import io
import hashlib
from urllib.parse import parse_qs, urlsplit

from ...core.contracts import now_iso
from ...core.errors import AuthRequired, CommerceError, ContextRequired, ContractError, NeedsHuman
from ...runtime.contexts import context_key
from .environment import prepare
from .locking import legacy_browser_lock
from .profiles import resolve_connection


async def _finish_mobile_tmall_login(page):
    """Adapt the normal mobile SSO form using the unchanged credential helpers.

    There is one credential submission. A failed check remains on the same page;
    it never falls through to a business DOM downloader.
    """
    if urlsplit(page.url).hostname != "login.m.taobao.com":
        return False
    from scripts.auto_download.playwright.login_extensions import tmall_finance_login as legacy
    toggle = page.get_by_text("账号密码登录", exact=True).filter(visible=True)
    if await toggle.count():
        await toggle.first.click()
    surface, submit, username, password = await legacy._fill_login_form(page,
        legacy.DEFAULT_USERNAME, legacy.DEFAULT_PASSWORD_ENV)
    agreements = page.get_by_role("checkbox").filter(visible=True)
    if await agreements.count() == 1 and not await agreements.first.is_checked():
        await agreements.first.check()
    await submit.click()
    deadline = asyncio.get_running_loop().time() + 30
    slider_attempts = 0
    while asyncio.get_running_loop().time() < deadline:
        host = urlsplit(page.url).hostname or ""
        if host in {"ad.alimama.com", "one.alimama.com", "b.alipay.com", "myseller.taobao.com"}:
            return True
        if host == "passport.taobao.com" and "alipay_management" in page.url:
            return True
        if await legacy._slider_challenge_present(page, surface):
            if slider_attempts >= 2:
                raise NeedsHuman("子后台登录仍要求验证，请保留当前 Profile 处理", stage="auth")
            slider_attempts += 1
            await legacy._smooth_drag_slider(page, surface)
            surface = await legacy._resubmit_after_slider(page, username, password)
        errors = surface.locator(".login-error-msg").filter(visible=True)
        if await errors.count() and (await errors.first.inner_text()).strip():
            raise NeedsHuman("子后台登录校验未通过，请在当前 Profile 检查已保存账号或验证要求", stage="auth")
        await asyncio.sleep(.5)
    raise NeedsHuman("子后台 SSO 登录尚未完成，保留原 Profile 供验证", stage="auth")


async def _open_tmall_marketing(browser, page, context, profile, backend, account_id, previous, contexts):
    """Adapt changed menu markup, retaining the original SSO/login policies."""
    from scripts.auto_download.playwright import tmall_promotion_download_common as legacy
    from scripts.auto_download.playwright.login_extensions.tmall_finance_login import DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV
    from ...core.registry import Registry
    from ...core.contracts import CN
    from datetime import datetime, timedelta
    parent = Registry().backend("tmall", "alimama")
    original_entry, original_authenticated = legacy._open_alimama_from_qianniu, legacy._alimama_authenticated
    checked_auth_states = set()

    async def entry(current_context):
        seller = next((p for p in reversed(current_context.pages) if urlsplit(p.url).hostname == "myseller.taobao.com"), None)
        menu = seller.get_by_role("link", name="推广", exact=True).filter(visible=True) if seller else None
        if menu is None or not await menu.count():
            return await original_entry(current_context)
        await menu.first.hover()
        link = seller.get_by_role("link", name="淘宝联盟", exact=True).filter(visible=True).first
        await link.wait_for(state="visible", timeout=10000)
        if urlsplit(await link.get_attribute("href") or "").hostname != "ad.alimama.com":
            raise ContextRequired("当前千牛菜单没有可确认的淘宝联盟授权入口", stage="auth")
        before_click = set(current_context.pages)
        await link.click(no_wait_after=True)
        deadline = asyncio.get_running_loop().time() + 20
        while asyncio.get_running_loop().time() < deadline:
            for candidate in reversed(current_context.pages):
                if (candidate not in before_click or candidate is seller) and urlsplit(candidate.url).hostname in {
                        "ad.alimama.com", "login.taobao.com", "login.m.taobao.com"}:
                    return candidate
            await asyncio.sleep(.2)
        raise NeedsHuman("千牛授权入口尚未打开对应页面，保留当前 Profile", stage="auth")

    async def authenticated(candidate):
        if await original_authenticated(candidate):
            return True
        if urlsplit(candidate.url).hostname not in {"ad.alimama.com", "one.alimama.com"}:
            return False
        auth_cookies = sorted((item["name"], item["domain"], item["value"]) for item in await context.cookies()
            if item["name"] in {"_m_h5_tk", "cookie2", "_tb_token_"})
        state = (candidate.url, hashlib.sha256(repr(auth_cookies).encode()).digest())
        if state in checked_auth_states:
            return False
        checked_auth_states.add(state)
        try:
            await _probe_current_session(context, candidate, profile, parent, account_id, previous, contexts)
            return True
        except (AuthRequired, ContextRequired, ContractError):
            return False

    day = datetime.now(CN).date() - timedelta(days=1)
    target = "https://ad.alimama.com/portal/v2/report/promotionDataPage.htm" if backend.id == "alimama" else legacy.wanxiangtai_url(day, day)
    legacy._open_alimama_from_qianniu, legacy._alimama_authenticated = entry, authenticated
    try:
        try:
            return await legacy.open_alimama_page(browser, target, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV)
        except Exception:
            mobile = next((p for p in reversed(context.pages) if urlsplit(p.url).hostname == "login.m.taobao.com"), None)
            if mobile is None:
                raise
            await _finish_mobile_tmall_login(mobile)
            return await legacy.open_alimama_page(browser, target, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV)
    finally:
        legacy._open_alimama_from_qianniu, legacy._alimama_authenticated = original_entry, original_authenticated


async def _authenticate(browser, page, context, profile, backend, account_id, previous=None, contexts=None):
    platform = profile.platform
    if platform == "douyin" and backend.id == "qianchuan":
        from scripts.auto_download.playwright.qianchuan_login import (open_workbench_page,
            open_qianchuan_account, resolve_account, existing_qianchuan_aavids)
        workbench = await open_workbench_page(browser, platform="抖音", company=profile.company, shop=profile.shop)
        account = resolve_account(account_id or "auto", profile.company, profile.shop,
                                  existing_aavids=existing_qianchuan_aavids(browser))
        page = await open_qianchuan_account(workbench, account)
        return page, account.aavid
    if platform == "douyin":
        from scripts.auto_download.playwright.douyin_login import goto_with_douyin_login
        await goto_with_douyin_login(page, backend.home, profile.shop, platform="抖音", company=profile.company)
    elif platform == "pinduoduo":
        from scripts.auto_download.playwright.pinduoduo_login import ensure_pinduoduo_login
        await ensure_pinduoduo_login(context, platform="拼多多", company=profile.company, shop=profile.shop)
        if backend.id == "cashier":
            from scripts.auto_download.playwright.pinduoduo_settlement_download import open_reconciliation_center
            page, _ = await open_reconciliation_center(context)
        elif backend.id == "promotion":
            from scripts.auto_download.playwright.pinduoduo_promotion_fee_download import open_promotion_page
            page, _ = await open_promotion_page(context, platform="拼多多", company=profile.company, shop=profile.shop)
            await page.reload(wait_until="domcontentloaded", timeout=60000)
    elif platform == "jd":
        from scripts.auto_download.playwright.jd_order_download import ensure_login
        await ensure_login(page)
        if backend.id == "promotion":
            await page.goto(backend.home, wait_until="domcontentloaded", timeout=60000)
    elif platform == "kuaishou":
        from scripts.auto_download.playwright.kuaishou_order_download import ensure_kuaishou_login
        await ensure_kuaishou_login(page, profile.shop)
    elif platform == "xiaohongshu":
        from scripts.auto_download.playwright.xiaohongshu_download_common import ensure_logged_in
        await ensure_logged_in(page)
    elif platform == "tmall":
        from scripts.auto_download.playwright.login_extensions.tmall_finance_login import ensure_tmall_login
        if backend.id in {"qianniu", "aggregate"}:
            from scripts.auto_download.playwright.tmall_order_download import DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV
            await ensure_tmall_login(page, DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV)
        else:
            await ensure_tmall_login(page)
        if backend.id in {"alimama", "wanxiangtai"}:
            page = await _open_tmall_marketing(browser, page, context, profile, backend, account_id, previous, contexts or {})
        elif backend.id == "alipay":
            from scripts.auto_download.playwright.tmall_alipay_fund_download import (open_account_info, open_alipay_page,
                open_bill_download, ALIPAY_BIND_URL)
            existing = next((p for p in reversed(context.pages) if urlsplit(p.url).hostname == "b.alipay.com"), None)
            if existing is not None:
                await open_bill_download(existing)
                await existing.reload(wait_until="domcontentloaded", timeout=60000)
                return existing, account_id
            await open_account_info(page, profile.shop)
            try:
                page, _ = await open_alipay_page(page)
            except Exception:
                # The existing helper already uses this same binding/SSO route
                # after its detail button. Some profiles lack that button.
                await page.goto(ALIPAY_BIND_URL, wait_until="domcontentloaded", timeout=60000)
                if urlsplit(page.url).hostname == "login.m.taobao.com":
                    await _finish_mobile_tmall_login(page)
                    await page.goto(ALIPAY_BIND_URL, wait_until="domcontentloaded", timeout=60000)
                if urlsplit(page.url).hostname != "b.alipay.com":
                    await page.get_by_text("进入支付宝", exact=True).click(timeout=30000, no_wait_after=True)
                deadline = asyncio.get_running_loop().time() + 60
                while asyncio.get_running_loop().time() < deadline:
                    found = next((p for p in reversed(context.pages) if urlsplit(p.url).hostname == "b.alipay.com"), None)
                    if found:
                        page = found
                        break
                    await asyncio.sleep(.5)
                else:
                    raise NeedsHuman("支付宝 SSO 尚未完成，保留当前 Profile 供确认", stage="auth")
            await open_bill_download(page)
        elif backend.id == "aggregate":
            await page.goto("https://myseller.taobao.com/home.htm/whale-accountant/pay/capital/home?active=fund_day",
                            wait_until="domcontentloaded", timeout=60000)
    return page, account_id


async def _probe_current_session(context, page, profile, backend, account_id, previous, contexts):
    """Cookie extraction is an auth action; its postcondition is HTTP identity."""
    from ...core.registry import load_symbol
    candidate = {"profile": profile.__dict__, "platform": profile.platform, "backend": backend.id,
        "cookies": await context.cookies(), "user_agent": await page.evaluate("navigator.userAgent"),
        "contexts": {**(previous or {}).get("contexts", {}), **contexts},
        "identity": (previous or {}).get("identity", {}),
        "account_id": account_id or (previous or {}).get("account_id")}
    for name in ("mtop_signer_domains", "proxy"):
        if name in (previous or {}):
            candidate[name] = previous[name]
    probe = load_symbol(backend.client)(backend, candidate, profile)
    try:
        await probe.identity()
        return probe.http.snapshot()
    finally:
        await probe.close()


async def authenticate(profile, backend, *, account_id=None, already_locked=False, previous=None) -> dict:
    prepare()
    from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout
    contexts = {}
    pending = set()

    async def capture(request):
        try:
            if urlsplit(request.url).hostname not in backend.domains or (request.resource_type not in {"xhr", "fetch"}
                and not (request.resource_type == "script" and "/h5/" in request.url)):
                return
            headers = await request.all_headers()
            headers = {k: v for k, v in headers.items() if not k.startswith(":") and k.lower() not in {"cookie", "host", "content-length"}}
            contexts[context_key(request.url)] = {"url": request.url, "method": request.method,
                "headers": headers, "post_data": request.post_data, "captured_at": now_iso()}
        except Exception:
            pass

    def observe(request):
        task = asyncio.create_task(capture(request))
        pending.add(task)
        task.add_done_callback(pending.discard)

    scope = contextlib.nullcontext() if already_locked else legacy_browser_lock()
    with scope:
        connection = await asyncio.to_thread(resolve_connection, profile)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(connection.endpoint)
            if not browser.contexts:
                raise NeedsHuman("目标 Profile 没有可用浏览器上下文", stage="auth")
            context = browser.contexts[0]
            before = set(context.pages)
            context.on("request", observe)
            page = await context.new_page()
            succeeded = False
            try:
                home = "https://myseller.taobao.com/home.htm" if profile.platform == "tmall" else backend.home
                await page.goto(home, wait_until="domcontentloaded", timeout=60000)
                # A restored browser may already hold fresher cookies than the
                # encrypted HTTP snapshot. Verify them before submitting login
                # credentials or waiting for a page-specific logout selector.
                await asyncio.sleep(1)
                if pending:
                    await asyncio.gather(*list(pending), return_exceptions=True)
                try:
                    credentials = await _probe_current_session(context, page, profile, backend, account_id, previous, contexts)
                except (AuthRequired, ContextRequired) as exc:
                    if isinstance(exc, ContextRequired) and profile.platform == "tmall" and backend.id == "wanxiangtai":
                        from scripts.auto_download.playwright.tmall_promotion_download_common import wanxiangtai_url
                        from datetime import datetime, timedelta
                        from ...core.contracts import CN
                        target_day = datetime.now(CN).date() - timedelta(days=1)
                        try:
                            async with page.expect_request(lambda r: "stlacct.alimama.com/settleAccount/account/listAccountJournalWithTrans.json" in r.url,
                                    timeout=30000):
                                await page.goto(wanxiangtai_url(target_day, target_day), wait_until="domcontentloaded", timeout=60000)
                            await asyncio.sleep(1)
                            if pending:
                                await asyncio.gather(*list(pending), return_exceptions=True)
                            credentials = await _probe_current_session(context, page, profile, backend, account_id, previous, contexts)
                            succeeded = True
                            return credentials
                        except AuthRequired:
                            pass
                        except (TimeoutError, BrowserTimeout):
                            raise ContextRequired("万相台财务页未提供授权后的接口上下文，请保留 Profile 确认账号权限", stage="auth") from None
                else:
                    succeeded = True
                    return credentials
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    page, selected_account = await _authenticate(browser, page, context, profile, backend, account_id, previous, contexts)
                await asyncio.sleep(2)
                if pending:
                    await asyncio.gather(*list(pending), return_exceptions=True)
                credentials = {"profile": profile.__dict__, "platform": profile.platform, "backend": backend.id,
                    "cookies": await context.cookies(), "user_agent": await page.evaluate("navigator.userAgent"),
                    "contexts": contexts, "account_id": selected_account, "identity": {}}
                # Keep the auth tab until the target backend has actually proved
                # its session. A page title alone cannot confirm child access.
                credentials = await _probe_current_session(context, page, profile, backend, selected_account,
                    {**(previous or {}), "contexts": {**(previous or {}).get("contexts", {}), **contexts}}, contexts)
                succeeded = True
                return credentials
            except Exception as exc:
                if isinstance(exc, CommerceError):
                    raise
                # Original functions retain their human notification mechanisms.
                import traceback
                steps = [frame.name for frame in traceback.extract_tb(exc.__traceback__)[-5:]]
                raise NeedsHuman("现有认证流程尚未完成，请在原 Profile 处理登录或平台验证", stage="auth",
                    details={"cause": type(exc).__name__, "steps": steps, "backend": backend.id}) from None
            finally:
                context.remove_listener("request", observe)
                if succeeded:
                    for owned in list(context.pages):
                        if owned not in before and len(context.pages) > 1:
                            with contextlib.suppress(Exception):
                                await owned.close()
