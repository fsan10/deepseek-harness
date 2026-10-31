# -*- coding: utf-8 -*-
"""天猫推广费下载脚本共用的登录、日期与归档能力。"""

from __future__ import annotations

from .component_runtime import automation_component, component_event

import asyncio
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlencode

from playwright.async_api import TimeoutError as PlaywrightTimeout

from .login_extensions.tmall_finance_login import DEFAULT_USERNAME, DEFAULT_PASSWORD_ENV
from .outcomes import NeedsHumanError
from .tmall_alipay_fund_download import find_work_page, unique_download_path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALIMAMA_LOGIN_URL = "https://ad.alimama.com/index.htm"
QIANNIU_HOME_URL = "https://myseller.taobao.com/home.htm"


def is_alimama_report_page(url: str) -> bool:
    """判断当前页面是否已经进入淘宝联盟推广数据页。"""
    return "/portal/v2/report/promotionDataPage.htm" in url


def is_alimama_target_page(url: str, target_url: str) -> bool:
    """判断当前页面是否匹配指定的阿里妈妈目标域名、路径和 hash 路由。"""
    current = urlparse(url)
    target = urlparse(target_url)
    if (current.scheme, current.netloc, current.path) != (
        target.scheme,
        target.netloc,
        target.path,
    ):
        return False
    target_route = target.fragment.split("?", 1)[0]
    return not target_route or current.fragment.split("?", 1)[0] == target_route


def report_period(mode: str, today: date | None = None, *, start_date: str | None = None,
                  end_date: str | None = None, month: str | None = None) -> tuple[date, date]:
    """返回最新可取的日或完整月账单范围。"""
    current = today or date.today()
    if bool(start_date) != bool(end_date) or month and (start_date or end_date):
        raise ValueError("开始/结束日期须成对提供，不能与月份同时使用")
    if month:
        import calendar
        start = date.fromisoformat(month + "-01")
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        if mode != "month" or end >= current:
            raise ValueError("--month仅用于已结束的月账单")
        return start, end
    if start_date and end_date:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start > end or end > current:
            raise ValueError("业务日期区间无效或包含未来日期")
        if mode == "month":
            import calendar
            if start.day != 1 or start.year != end.year or start.month != end.month or end.day != calendar.monthrange(end.year, end.month)[1]:
                raise ValueError("月账单须覆盖同一完整自然月")
        return start, end
    if mode == "day":
        yesterday = current - timedelta(days=1)
        return yesterday, yesterday
    if mode != "month":
        raise ValueError(f"不支持的账单粒度：{mode}")
    previous_month_last_day = current.replace(day=1) - timedelta(days=1)
    return previous_month_last_day.replace(day=1), previous_month_last_day


def period_label(start: date, end: date, mode: str) -> str:
    return start.strftime("%Y-%m") if mode == "month" else end.isoformat()


def wanxiangtai_url(start: date, end: date) -> str:
    query = urlencode(
        {
            "spm": "",
            "costStartTime": start.replace(day=1).isoformat(),
            "costEndTime": end.isoformat(),
            "detailTab": "cash",
            "time": "acount",
            "currentPage": "1",
            "trade": "DEDUCT",
            "cashStart": start.isoformat(),
            "cashEnd": end.isoformat(),
        }
    )
    return f"https://one.alimama.com/index.html#!/account/detail?{query}"


async def ensure_wanxiangtai_booking_time(page):
    """在现金明细下载前确认记账时间，避免交易日期导致跨日错位。"""
    booking = page.locator('.mx-trigger-label').filter(has_text="记账时间")
    transaction = page.locator('.mx-trigger-label').filter(has_text="交易日期")
    await page.wait_for_function("""() => [...document.querySelectorAll('.mx-trigger-label')]
        .some(e => ['记账时间', '交易日期'].includes(e.textContent.trim()))""", timeout=60_000)
    if not await booking.count():
        await transaction.last.click()
        await page.locator('.mx-output-item[title="记账时间"] .mx-output-link').click()
    await booking.wait_for(state="visible", timeout=30_000)
    await page.wait_for_function("""() => new URLSearchParams(location.hash.split('?')[1]).get('time') === 'acount'""", timeout=30_000)


@automation_component("tmall.promotion.open", "天猫推广 · 打开阿里妈妈报表", category="report")
async def open_alimama_page(browser, target_url: str, username: str, password_env: str):
    """Reuse this profile's session, entering through Qianniu when necessary."""
    existing = [p for context in browser.contexts for p in context.pages
                if urlparse(p.url).netloc == 'ad.alimama.com']
    for page in reversed(existing):
        if await _alimama_authenticated(page):
            component_event('login_session_reused', '复用当前 Profile 已登录的淘宝联盟会话')
            return await _open_alimama_target(page, target_url)
        if await _click_quick_enter_if_present(page):
            await _wait_for_alimama_login(page, quick_enter_clicked=True)
            return await _open_alimama_target(page, target_url)

    # Keep all navigation in one cookie jar. Never copy cookies between profiles
    # or create a new browser context for the Alimama login.
    fallback = existing[-1] if existing else await find_work_page(browser)
    context = fallback.context
    page = await _open_alimama_from_qianniu(context)
    if page is None:
        # Qianniu itself needs authentication. Preserve that page and retain the
        # existing embedded-password fallback for standalone promotion runs.
        page = fallback if fallback in existing else await context.new_page()
        if page.url != ALIMAMA_LOGIN_URL:
            await page.goto(ALIMAMA_LOGIN_URL, wait_until='domcontentloaded', timeout=60_000)

    surface = await _wait_for_password_form(page)
    if surface is not None:
        from apps.fund_split_adjust.server import load_project_env
        load_project_env()
        password = os.getenv(password_env, '')
        if not username or not password:
            raise RuntimeError(f'阿里妈妈登录凭据不完整；请检查项目.env中的{password_env}及登录账号')
        component_event('inline_login_form_ready', '已定位首页内嵌iframe中的#container登录表单')
        try:
            await surface.locator('#fm-login-id').filter(visible=True).first.fill(username, timeout=10_000)
            await surface.locator('#fm-login-password').filter(visible=True).first.fill(password, timeout=10_000)
        except Exception:
            # Playwright's original exception can quote the fill/type argument.
            raise RuntimeError('阿里妈妈登录表单输入失败；已隐藏凭据，请检查当前登录页') from None
        await surface.get_by_role('button', name='登录', exact=True).click()
        component_event('inline_login_submitted', '已提交内嵌密码登录表单；凭据未写入事件')
        await _wait_for_alimama_login(page)
    return await _open_alimama_target(page, target_url)


async def _open_alimama_from_qianniu(context):
    """Open Qianniu's real menu link and retain either its popup or same tab."""
    seller = next((p for p in reversed(context.pages)
                   if urlparse(p.url).netloc == 'myseller.taobao.com'), None)
    if seller is None:
        seller = await context.new_page()
    parsed = urlparse(seller.url)
    if parsed.netloc != 'myseller.taobao.com' or not parsed.path.startswith('/home.htm'):
        await seller.goto(QIANNIU_HOME_URL, wait_until='domcontentloaded', timeout=60_000)
    if urlparse(seller.url).netloc != 'myseller.taobao.com':
        return None

    entry = seller.get_by_role('link', name='淘宝联盟', exact=True).filter(visible=True).first
    try:
        if not await entry.count():
            menu = seller.get_by_role('button', name='推广', exact=True).filter(visible=True).first
            await menu.wait_for(state='visible', timeout=15_000)
            await menu.hover(timeout=10_000)
            try:
                await entry.wait_for(state='visible', timeout=1500)
            except PlaywrightTimeout:
                await menu.click(timeout=10_000, no_wait_after=True)
        await entry.wait_for(state='visible', timeout=10_000)
        href = await entry.get_attribute('href')
        if urlparse(href or '').netloc != 'ad.alimama.com':
            raise RuntimeError('千牛淘宝联盟菜单的目标地址不符合预期')
        before = set(context.pages)
        await entry.click(timeout=10_000, no_wait_after=True)
    except PlaywrightTimeout:
        if urlparse(seller.url).netloc != 'myseller.taobao.com' or await seller.locator(
            '#fm-login-id, iframe#alibaba-login-box'
        ).filter(visible=True).count():
            return None
        raise RuntimeError('千牛“推广→淘宝联盟”菜单未能打开；已保留当前页面') from None

    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if urlparse(seller.url).netloc == 'ad.alimama.com':
            component_event('qianniu_union_opened', '已从同一 Profile 的千牛菜单进入淘宝联盟')
            return seller
        for popup in reversed(context.pages):
            if popup not in before and (urlparse(popup.url).netloc in {
                'ad.alimama.com', 'login.taobao.com',
            } or popup.url in {'about:blank', ''}):
                component_event('qianniu_union_opened', '已接管千牛淘宝联盟菜单打开的同一上下文标签页')
                return popup
        await asyncio.sleep(0.1)
    raise RuntimeError('点击千牛淘宝联盟后未找到对应页面；已保留当前 Profile')


async def _wait_for_alimama_login(page, *, quick_enter_clicked=False):
    """Allow one quick-entry confirmation to settle without resetting the page."""
    parsed = urlparse(page.url)
    confirmed_pages = {(parsed.netloc, parsed.path)} if quick_enter_clicked else set()
    deadline = asyncio.get_running_loop().time() + 120
    while asyncio.get_running_loop().time() < deadline:
        if await _alimama_authenticated(page):
            component_event('login_authenticated', '阿里妈妈已进入登录后的商家中心')
            break
        parsed = urlparse(page.url)
        phase = (parsed.netloc, parsed.path)
        if phase not in confirmed_pages and await _click_quick_enter_if_present(page):
            confirmed_pages.add(phase)
            await asyncio.sleep(0.5)
            continue
        current = await _password_form(page)
        if current is not None:
            keep = current.get_by_role('button', name=re.compile(r'^不保持')).filter(visible=True)
            if await keep.count():
                await keep.first.click()
            error = current.locator('.login-error-msg').filter(visible=True)
            if await error.count() and (await error.first.inner_text()).strip():
                raise NeedsHumanError('阿里妈妈登录校验未通过，请在当前Profile检查账号或验证要求；未重复提交密码')
        await asyncio.sleep(0.5)
    else:
        raise NeedsHumanError('阿里妈妈登录仍需验证或确认，请在当前Profile完成后重试')


async def _open_alimama_target(page, target_url):
    # The Wanxiangtai hash query carries the requested business dates. Matching
    # only its route would leave a previous report period in place.
    if page.url != target_url:
        await page.goto(target_url, wait_until='domcontentloaded', timeout=60_000)
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        if await _password_form(page) is not None:
            raise NeedsHumanError('阿里妈妈报表要求再次登录，请保留当前Profile检查登录验证')
        if is_alimama_target_page(page.url, target_url):
            return page
        await asyncio.sleep(0.25)
    raise NeedsHumanError('阿里妈妈报表授权未完成，请在当前Profile完成登录或验证后重试')


async def _password_form(page):
    # The first Taobao iframe is the homepage's embedded form. A header
    # "立即登录" popup appends another iframe; never search or submit that one.
    if not await page.locator('iframe[src*="login.taobao.com/member/login.jhtml"]').count():
        return None
    surface = _inline_login_container(page)
    try:
        account = surface.locator('#fm-login-id').filter(visible=True)
        password = surface.locator('#fm-login-password').filter(visible=True)
        if await surface.is_visible() and await account.count() and await password.count():
            return surface
    except Exception:
        pass
    return None


def _inline_login_container(page):
    return page.frame_locator('iframe[src*="login.taobao.com/member/login.jhtml"]').first.locator(
        'xpath=//*[@id="container"]')


async def _wait_for_password_form(page, timeout_seconds=30):
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    confirmed_pages = set()
    session_redirect_followed = False
    while asyncio.get_running_loop().time() < deadline:
        if await _alimama_authenticated(page):
            return None
        parsed = urlparse(page.url)
        phase = (parsed.netloc, parsed.path)
        if phase not in confirmed_pages and await _click_quick_enter_if_present(page):
            confirmed_pages.add(phase)
            await asyncio.sleep(0.5)
            continue
        surface = await _password_form(page)
        if surface is not None:
            return surface
        if not session_redirect_followed and await _follow_alimama_session_link(page):
            session_redirect_followed = True
            continue
        try:
            tab = _inline_login_container(page).get_by_text('密码登录', exact=True).filter(visible=True)
            if await tab.count():
                await tab.first.click()
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise NeedsHumanError('千牛会话未完成阿里妈妈授权，请在当前Profile完成登录或验证后重试')


async def _follow_alimama_session_link(page):
    """Use the homepage's normal Taobao SSO link without opening its login popup."""
    current = urlparse(page.url)
    if current.netloc != 'ad.alimama.com' or current.path != '/index.htm':
        return False
    link = page.get_by_role('link', name='立即登录', exact=True).filter(visible=True).first
    if not await link.count():
        return False
    href = await link.get_attribute('href')
    login = urlparse(href or '')
    if (login.scheme, login.netloc, login.path) != ('https', 'login.m.taobao.com', '/login.htm'):
        return False
    redirect = urlparse(parse_qs(login.query).get('redirectURL', [''])[0])
    if redirect.netloc == 'jump.taobao.com':
        redirect = urlparse(parse_qs(redirect.query).get('target', [''])[0])
    if redirect.scheme != 'https' or redirect.netloc != 'ad.alimama.com':
        return False
    await page.goto(href, wait_until='domcontentloaded', timeout=60_000)
    component_event('login_session_redirect_followed', '已在同一标签页进入淘宝现有会话确认页')
    return True


async def _click_quick_enter_if_present(page):
    """Optional confirmation; its direct link takes priority over the button."""
    for role in ('link', 'button'):
        control = page.get_by_role(role, name='快速进入', exact=True).filter(visible=True)
        if await control.count():
            await control.first.click(timeout=10_000, no_wait_after=True)
            component_event('quick_enter_confirmed', '已点击可选的快速进入，继续等待商家中心')
            return True
    return False


async def _alimama_authenticated(page):
    parsed = urlparse(page.url)
    if parsed.netloc != 'ad.alimama.com' or not parsed.path.startswith('/portal/'):
        return False
    try:
        return await page.get_by_role('link', name='退出', exact=True).filter(visible=True).count() > 0
    except Exception:
        return False


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download, work_dir: Path, fallback_name: str) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    target = unique_download_path(work_dir, download.suggested_filename or fallback_name)
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"推广费下载文件为空：{target}")
    return target


@automation_component("tmall.promotion.capture_download", "天猫推广 · 触发并捕获下载", category="report")
async def click_and_capture_download(page, click, timeout_ms: int = 120_000):
    """捕获当前页或下载占位新页触发的下载事件。"""
    loop = asyncio.get_running_loop()
    completed = loop.create_future()

    def receive(download) -> None:
        if not completed.done():
            completed.set_result(download)

    def watch(new_page) -> None:
        new_page.on("download", receive)

    context = page.context
    page.on("download", receive)
    context.on("page", watch)
    try:
        await click()
        return await asyncio.wait_for(completed, timeout=timeout_ms / 1000)
    finally:
        page.remove_listener("download", receive)
        context.remove_listener("page", watch)


@automation_component("report.archive", "归档标准报表", category="file")
def move_report(
    source: Path,
    platform: str,
    company: str,
    shop: str,
    report_name: str,
    bill_date: str,
    dest: Path,
) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.auto_download.move_report",
            "--platform", platform,
            "--company", company,
            "--shop", shop,
            "--report", report_name,
            "--date", bill_date,
            "--src", str(source.parent),
            "--dest", str(dest),
            "--pattern", source.name,
            "--within", "10",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def month_choices_from_text(text: str) -> list[str]:
    """提取联盟“月”浮层可见的 YYYY年M月 或 YYYY-M 选项。"""
    choices: list[str] = []
    for year, month in re.findall(r"(20\d{2})\s*[年\-/.]\s*(1[0-2]|0?[1-9])\s*月?", text):
        value = f"{year}-{int(month):02d}"
        if value not in choices:
            choices.append(value)
    return choices
