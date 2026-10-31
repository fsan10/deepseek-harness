# -*- coding: utf-8 -*-
"""巨量千川升级版工作台登录、账户选择和千川入口恢复。

升级版工作台和抖店使用不同的登录页面。这里复用 Cloak profile 中保存的
邮箱凭据，只通过浏览器自动填充触发凭据，不读取、打印或把凭据传给脚本。
登录成功后总是重新打开 ``portal-fallback``，避免旧版首页和 AB 测试页面的
差异影响账户选择。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable
from urllib.parse import parse_qs, urlparse

from .automation_challenge import notify_human_handoff

if TYPE_CHECKING:
    from playwright.async_api import Browser, Locator, Page


WORKBENCH_URL = (
    "https://business.oceanengine.com/portal-fallback?"
    "oew_src=ecp_login&is_new_connect=0&is_new_user=0&utm_source=80"
)
WORKBENCH_LOGIN_RE = re.compile(r"^https://business\.oceanengine\.com/login(?:[/?#]|$)")
WORKBENCH_LEGACY_RE = re.compile(r"^https://business\.oceanengine\.com/site/index(?:[/?#]|$)")
QIANCHUAN_HOST = "qianchuan.jinritemai.com"
LOGIN_TIMEOUT_SECONDS = 45.0
HUMAN_VERIFICATION_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class QianchuanAccount:
    """可访问的千川账户；默认项来自用户提供并已实测的账户清单。"""

    aavid: str
    account_name: str
    company: str
    shop: str


# ``1854896545860682`` 是现有千川 profile 历史成功使用的账户。冲饮店的
# ``1860540938445002`` 仍保留为显式 --aavid 选项，不在 auto 模式下猜测，
# 以免同一店铺的两个千川账户被错归档。
DEFAULT_ACCOUNTS: tuple[QianchuanAccount, ...] = (
    QianchuanAccount(
        "1854896545860682",
        "津果日记生物科技（南京）有限公司-MGM-千川",
        "津果日记生物科技（南京）有限公司",
        "MOCK冲饮旗舰店",
    ),
    QianchuanAccount(
        "1855000024322052",
        "南京宁盏食品科技有限公司-MGM-千川",
        "南京宁盏食品科技有限公司",
        "MOCK宁盏冲饮专卖店",
    ),
    QianchuanAccount(
        "1855526984749068",
        "墨客咖时（南京）生物科技有限公司-MGM-千川",
        "墨客咖时（南京）生物科技有限公司",
        "MOCK官方旗舰店",
    ),
)


def normalize_account_text(value: str) -> str:
    """统一中英文括号和空白，兼容 profile note 与平台显示文本。"""

    return " ".join(
        value.replace("（", "(").replace("）", ")").replace("：", ":").split()
    )


def _same_business_value(left: str, right: str) -> bool:
    return normalize_account_text(left) == normalize_account_text(right)


def parse_aavid_from_url(url: str) -> str:
    """从千川 URL 读取 aavid；不从页面标题或固定标签序号猜测。"""

    query = parse_qs(urlparse(url).query)
    return (query.get("aavid") or query.get("aadvid") or [""])[0].strip()


def resolve_account(
    requested_aavid: str,
    company: str,
    shop: str,
    *,
    existing_aavids: Iterable[str] = (),
) -> QianchuanAccount:
    """解析显式账户或按 profile 业务备注解析默认账户。

    ``auto`` 只复用与 profile 公司、店铺映射一致的已打开账户；否则使用
    明确登记的店铺默认账户。同店铺的备用账户必须通过 ``--aavid`` 显式指定。
    """

    requested = requested_aavid.strip()
    known = list(DEFAULT_ACCOUNTS)
    if requested.lower() != "auto":
        if not requested.isdigit():
            raise ValueError(f"--aavid 必须是数字账户 ID 或 auto：{requested_aavid}")
        for account in known:
            if account.aavid == requested:
                return account
        # 显式账户可以是用户清单中的备用账户，平台名称仍由 profile note 提供。
        return QianchuanAccount(requested, "", company, shop)

    open_ids = [item.strip() for item in existing_aavids if item and item.strip()]
    candidates = [
        account
        for account in known
        if _same_business_value(account.company, company)
        and _same_business_value(account.shop, shop)
    ]
    if not candidates:
        raise ValueError(
            "无法按 profile note 自动解析千川账户；请显式传入 --aavid。"
            f" company={company!r}, shop={shop!r}"
        )

    for account in candidates:
        if account.aavid in open_ids:
            return account
    # A stale tab from another account must not override the profile's explicit
    # company/shop mapping. That could send the report into the wrong shop.
    return candidates[0]


async def _visible_locator(locator: "Locator") -> "Locator | None":
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def _visible_count(locator: "Locator") -> int:
    visible = 0
    for index in range(await locator.count()):
        try:
            if await locator.nth(index).is_visible():
                visible += 1
        except Exception:
            continue
    return visible


async def _body_text(page: "Page") -> str:
    try:
        return (await page.locator("body").inner_text(timeout=3_000)).strip()
    except Exception:
        return ""


async def _click_compat(locator: "Locator", *, timeout: int = 8_000) -> None:
    try:
        await locator.click(timeout=timeout)
        return
    except Exception as first_error:
        try:
            await locator.click(timeout=min(timeout, 2_000), force=True)
            return
        except Exception:
            try:
                await locator.evaluate("element => element.click()", timeout=2_000)
                return
            except Exception:
                raise first_error


async def workbench_login_surface_visible(page: "Page") -> bool:
    email = page.locator('input[name="email"], input[type="email"], input[placeholder*="邮箱"]')
    text = await _body_text(page)
    if await _visible_count(email):
        return "巨量引擎" in text or "登录" in text or WORKBENCH_LOGIN_RE.match(page.url) is not None
    # A valid session can client-side redirect from /login while the old URL
    # remains briefly visible.  Do not classify that transition as a login
    # surface solely from the URL; require the actual email form marker.
    return WORKBENCH_LOGIN_RE.match(page.url) is not None and (
        "登录巨量引擎账号" in text or "请输入邮箱" in text
    )


async def workbench_captcha_visible(page: "Page") -> bool:
    for selector in (
        "#captcha_container iframe",
        'iframe[id*="captcha" i]',
        'iframe[name*="captcha" i]',
        'iframe[src*="captcha" i]',
    ):
        if await _visible_count(page.locator(selector)):
            return True
    return False


async def workbench_state(page: "Page") -> str:
    if await workbench_login_surface_visible(page):
        return "login"
    if WORKBENCH_LEGACY_RE.match(page.url):
        return "legacy"
    text = await _body_text(page)
    if "business.oceanengine.com" in page.url and (
        "/portal-fallback" in page.url or "您可访问账户" in text or "升级版" in text
    ):
        return "workbench"
    return "other"


async def wait_for_workbench_state(
    page: "Page", *, timeout: float = LOGIN_TIMEOUT_SECONDS
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    state = "other"
    while asyncio.get_running_loop().time() < deadline:
        state = await workbench_state(page)
        if state != "other":
            return state
        await asyncio.sleep(0.25)
    return state


async def _autofill_saved_credentials(page: "Page", *, timeout: float = 15.0) -> None:
    email_selector = 'input[name="email"], input[type="email"], input[placeholder*="邮箱"]'
    password_selector = (
        'input[name="password"], input[type="password"], input[placeholder*="密码"]'
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not await workbench_login_surface_visible(page):
            state = await workbench_state(page)
            if state in {"legacy", "workbench"}:
                print("[QIANCHUAN_LOGIN] 当前会话已自动恢复，无需再次填充凭据")
                return
        email = await _visible_locator(page.locator(email_selector))
        password = await _visible_locator(page.locator(password_selector))
        if email is None or password is None:
            await asyncio.sleep(0.25)
            continue
        try:
            if await email.input_value() and await password.input_value():
                print("[QIANCHUAN_LOGIN] 当前 profile 已回填邮箱登录凭据")
                return
        except Exception:
            pass
        for target in (email, password, email):
            try:
                await target.click(timeout=8_000)
            except Exception:
                try:
                    await target.focus(timeout=2_000)
                except Exception:
                    # 页面可能在自动恢复会话时刚刚卸载了登录表单；回到
                    # 外层轮询重新判断状态，不把瞬时 detach 当成凭据错误。
                    break
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.4)
        try:
            if await email.input_value() and await password.input_value():
                print("[QIANCHUAN_LOGIN] 当前 profile 已回填邮箱登录凭据")
                return
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError("巨量引擎邮箱登录表单未自动填充；请在当前 profile 中选择已保存凭据")


async def _check_workbench_agreement(page: "Page", *, timeout: float = 15.0) -> None:
    selectors = (
        "div.account-center-agreement-check",
        ".account-center-input-agreement",
        '#ecomLoginForm input[type="checkbox"]',
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not await workbench_login_surface_visible(page):
            return
        for selector in selectors:
            checkbox = await _visible_locator(page.locator(selector))
            if checkbox is None:
                continue
            try:
                if await checkbox.get_attribute("class") and "checked" in (
                    await checkbox.get_attribute("class") or ""
                ):
                    return
                if await checkbox.get_attribute("type") == "checkbox" and await checkbox.is_checked():
                    return
            except Exception:
                pass
            await _click_compat(checkbox)
            print("[QIANCHUAN_LOGIN] 已勾选巨量引擎用户协议")
            return
        await asyncio.sleep(0.25)
    raise RuntimeError("巨量引擎登录页未找到用户协议复选框")


async def _click_workbench_login(page: "Page") -> None:
    candidates = (
        page.get_by_role("button", name="登录", exact=True),
        page.locator("button").filter(has_text=re.compile(r"^登录$")),
    )
    for candidate in candidates:
        button = await _visible_locator(candidate)
        if button is None:
            continue
        try:
            if await button.is_enabled():
                await _click_compat(button)
                return
        except Exception:
            continue
    raise RuntimeError("巨量引擎邮箱登录按钮未启用；请检查 profile 凭据和用户协议")


async def wait_for_workbench_human_verification(
    page: "Page", *, platform: str, company: str, shop: str,
    timeout: float = HUMAN_VERIFICATION_TIMEOUT_SECONDS,
) -> str:
    """等待人工完成真实验证，不识别、不绕过验证码。"""

    print("[QIANCHUAN_LOGIN] 检测到巨量引擎登录验证，请在已启动的 profile 中手动完成")
    if company and shop:
        try:
            await notify_human_handoff(
                platform=platform,
                company=company,
                shop=shop,
                purpose="巨量千川升级版工作台登录验证",
            )
            print("[QIANCHUAN_LOGIN] 已发送工作台登录人工接手提醒")
        except Exception:
            print("[QIANCHUAN_LOGIN] 登录人工接手提醒发送失败；仍等待 profile 页面")
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if not await workbench_captcha_visible(page):
            state = await workbench_state(page)
            if state in {"legacy", "workbench"}:
                return state
        await asyncio.sleep(0.5)
    raise RuntimeError("巨量引擎登录验证超时；保留当前 profile 页面供人工接管")


async def recover_workbench_login(
    page: "Page", *, platform: str, company: str, shop: str,
    timeout: float = LOGIN_TIMEOUT_SECONDS,
) -> str:
    """在已打开工作台页面上恢复登录，并返回登录后的页面状态。"""

    await _autofill_saved_credentials(page)
    await _check_workbench_agreement(page)
    await asyncio.sleep(0.5)
    if await workbench_state(page) == "login":
        await _click_workbench_login(page)

    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await workbench_captcha_visible(page):
            return await wait_for_workbench_human_verification(
                page, platform=platform, company=company, shop=shop
            )
        state = await workbench_state(page)
        if state in {"legacy", "workbench"}:
            return state
        await asyncio.sleep(0.5)
    raise RuntimeError(f"巨量引擎登录提交后未进入首页：{page.url.split('?')[0]}")


async def _existing_business_page(browser: "Browser") -> "Page | None":
    for context in browser.contexts:
        for page in context.pages:
            if not page.is_closed() and "business.oceanengine.com" in page.url:
                return page
    return None


async def open_workbench_page(
    browser: "Browser", *, platform: str, company: str, shop: str
) -> "Page":
    """登录后新建标签页重新打开升级版工作台 URL。"""

    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用的浏览器上下文")
    context = browser.contexts[0]
    page = await _existing_business_page(browser)
    if page is None:
        page = await context.new_page()

    await page.goto(WORKBENCH_URL, wait_until="domcontentloaded", timeout=60_000)
    state = await wait_for_workbench_state(page)
    if state == "login":
        await recover_workbench_login(
            page, platform=platform, company=company, shop=shop
        )
        # 明确复现用户验证过的兜底动作：登录完成后新建标签页，再次输入
        # portal-fallback，而不是依赖旧版首页或某个 AB 版本的按钮。
        page = await context.new_page()
        await page.goto(WORKBENCH_URL, wait_until="domcontentloaded", timeout=60_000)
        state = await wait_for_workbench_state(page)
    elif state == "legacy":
        page = await context.new_page()
        await page.goto(WORKBENCH_URL, wait_until="domcontentloaded", timeout=60_000)
        state = await wait_for_workbench_state(page)

    if state != "workbench":
        raise RuntimeError(
            "巨量引擎升级版工作台未加载账户列表："
            f"state={state}, url={page.url.split('?')[0]}"
        )
    return page


async def _wait_for_account_cards(
    page: "Page", *, account_id: str, timeout: float = 30.0
) -> "Locator":
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for selector in (".account-card", '[class*="account-card"]'):
            cards = page.locator(selector).filter(has_text=account_id)
            if await _visible_count(cards):
                return cards
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"升级版工作台账户列表中未找到千川账户 ID：{account_id}；"
        "请确认当前 profile 有该账户访问权限"
    )


async def open_qianchuan_account(
    workbench_page: "Page", account: QianchuanAccount
) -> "Page":
    """按账户 ID 找到卡片并点击“访问账户”，兼容新开标签或原页跳转。"""

    cards = await _wait_for_account_cards(workbench_page, account_id=account.aavid)
    card = cards.first
    await card.scroll_into_view_if_needed(timeout=8_000)
    await card.hover(timeout=8_000)
    button = await _visible_locator(
        card.get_by_role("button", name=re.compile(r"访问账户"))
    )
    if button is None:
        raise RuntimeError(f"千川账户卡片未出现“访问账户”按钮：{account.aavid}")

    context = workbench_page.context
    before = set(context.pages)
    # The access button may navigate the current tab instead of opening a popup.
    # Do not retry merely because a popup did not appear: the click may navigate
    # the current tab. Click without waiting for navigation, then inspect both
    # the current tab and any newly opened tabs below.
    bounds = await button.evaluate(
        """element => {
            const rect = element.getBoundingClientRect();
            return {
                left: rect.left,
                top: rect.top,
                right: rect.right,
                bottom: rect.bottom,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
            };
        }"""
    )
    outside_viewport = (
        bounds["left"] < 0
        or bounds["top"] < 0
        or bounds["right"] > bounds["viewportWidth"]
        or bounds["bottom"] > bounds["viewportHeight"]
    )
    if outside_viewport:
        # The workbench renders fixed-width account cards. In a narrow Cloak
        # viewport the hovered action sits beyond the right edge; Playwright's
        # pointer click scrolls toward it, which removes the card hover and hides
        # the button. Dispatch the exact, already-visible card button while the
        # hover state is still active, then inspect the same tab and any popup.
        try:
            await button.evaluate("element => element.click()", timeout=2_000)
        except Exception:
            # Navigation can destroy the page context after the click was
            # dispatched. Do not issue a second click; the page polling below
            # determines whether the account opened.
            pass
    else:
        try:
            await button.click(timeout=10_000, no_wait_after=True)
        except Exception as click_error:
            # The account card reveals this button on hover. On some workbench
            # builds it hides while the pointer moves from the card to the
            # button, even though the exact button was visible just before.
            try:
                await card.hover(timeout=3_000)
                await button.evaluate("element => element.click()", timeout=2_000)
            except Exception:
                raise click_error
    candidate = workbench_page

    deadline = asyncio.get_running_loop().time() + 30.0
    while asyncio.get_running_loop().time() < deadline:
        for page in context.pages:
            if page in before and page is not candidate:
                continue
            if QIANCHUAN_HOST not in page.url:
                continue
            if parse_aavid_from_url(page.url) == account.aavid:
                await page.wait_for_load_state("domcontentloaded", timeout=30_000)
                return page
        await asyncio.sleep(0.5)
    raise RuntimeError(f"访问千川账户后未打开对应千川页面：{account.aavid}")


def existing_qianchuan_aavids(browser: "Browser") -> list[str]:
    values: list[str] = []
    for context in browser.contexts:
        for page in context.pages:
            if QIANCHUAN_HOST not in page.url:
                continue
            value = parse_aavid_from_url(page.url)
            if value and value not in values:
                values.append(value)
    return values
