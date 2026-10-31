# -*- coding: utf-8 -*-
"""快手小店订单标准报表下载。

流程完全走快手商家后台的可见页面：从首页点击“订单查询”，使用日期弹层的
“最近一个月”快捷项（失败时才回退到自定义日期），在“批量导出订单”侧栏
选择标准报表并创建任务，然后在独立的导出历史页发送文件提取码、下载受密码
保护的 XLSX，使用 msoffcrypto 解密后调用 move_report.py 归档。

导出任务、短信验证码和文件提取码都写入可恢复状态文件。进程中断或平台的
5 分钟导出频控出现时，重跑会复用已有历史任务，不会重复创建导出任务。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from .automation_challenge import create_challenge, probe_relay, reopen_for_human, wait_answer
from .component_runtime import automation_component, component_event
from .outcomes import NeedsHumanError
from .kuaishou_download_common import new_page, save_download

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Download, Locator, Page


PLATFORM = "快手"
REPORT_NAME = "订单"
HOME_URL = "https://s.kwaixiaodian.com/zone/home"
ORDER_LIST_URL = "https://s.kwaixiaodian.com/zone/order/list"
EXPORT_HISTORY_URL = "https://s.kwaixiaodian.com/zone/order/exportList"
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")
PROJECT_ROOT = Path(__file__).resolve().parents[3]

_VISIBLE = ":visible"
_STANDARD_RE = re.compile(r"^\s*标准报表\s*$")
_QUERY_RE = re.compile(r"^\s*查\s*询\s*$")
_DOWNLOAD_RE = re.compile(r"^\s*下载报表\s*$")
_SEND_CODE_RE = re.compile(r"^\s*发送文件提取码\s*$")
_EXPORT_RE = re.compile(r"^\s*导\s*出\s*$")
_ATTENTION_RE = re.compile(r"请\s*注\s*意|敏感|信息安全")
_ERROR_RE = re.compile(r"验证码|校验码|提取码|密码|导出|失败|错误|过期")
_EXPORT_SUBMIT_API_FRAGMENT = "/order/export/submit/"
_ENCRYPT_PHONE_API_FRAGMENT = "/order/encrypt/phone"
_ORDER_RECORD_COUNT_RE = re.compile(r"共\s*计\s*([0-9０-９,，]+)\s*条")
_RATE_LIMIT_RE = re.compile(
    r"操作过于频繁|请勿重复提交|重复提交(?:任务|报表)?|"
    r"短时间内(?:不能|无法|请勿)|"
    r"(?:5|５)\s*分钟(?:后|内)\s*(?:再试|重试|再操作)|"
    r"五分钟(?:后|内)\s*(?:再试|重试|再操作)",
    flags=re.IGNORECASE,
)
_CREATED_RE = re.compile(
    r"(?:生成时间|创建时间)\s*[:：]?\s*(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"
    r"(?:[日 ]|T)?(?:([01]?\d|2[0-3])[:时](\d{1,2})[:分](\d{1,2}))?"
)


def _visible(locator: "Locator") -> "Locator":
    return locator.filter(visible=True)


async def click_compat(locator: "Locator") -> None:
    """正常点击失败时再使用 DOM click，兼容固定悬浮层和动画。"""

    try:
        await locator.click(timeout=8_000)
    except Exception:
        await locator.evaluate("element => element.click()")


def _state_path(work_dir: Path) -> Path:
    return work_dir / "kuaishou_order_task.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def recent_month_range(*, today: date | None = None) -> tuple[str, str]:
    """返回快手“最近一个月”的保底日期范围（结束日含当天共 30 天）。"""

    end = today or date.today()
    return (end - timedelta(days=29)).isoformat(), end.isoformat()


def parse_order_record_count(text: str) -> int | None:
    """解析订单列表可见的“共计N条”，缺少该结果标识时返回 None。"""

    match = _ORDER_RECORD_COUNT_RE.search(text or "")
    if not match:
        return None
    digits = match.group(1).translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
    return int(digits.replace(",", ""))


def _date_only(value: str) -> str:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", value or "")
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _date_range_matches(
    text: str,
    start_date: str,
    end_date: str,
    *,
    require_start: bool = False,
) -> bool:
    dates = [_date_only(item) for item in re.findall(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", text)]
    dates = [item for item in dates if item]
    if not dates:
        return False
    # 普通恢复允许平台不同版本将起始日按自然月边界展示；强制新建时则
    # 必须同时看到起止日期，防止把同一结束日的旧短范围报表误当成近30日。
    if require_start:
        return start_date in dates and end_date in dates
    return end_date in dates or (start_date in dates and end_date in dates)


def _parse_created(text: str) -> tuple[int, ...]:
    values = _CREATED_RE.findall(text or "")
    parsed: list[tuple[int, ...]] = []
    for year, month, day, hour, minute, second in values:
        parsed.append((int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)))
    return max(parsed) if parsed else (0,)


async def _body_text(page: "Page") -> str:
    with suppress(Exception):
        return (await page.locator("body").inner_text(timeout=3_000)).strip()
    return ""


async def _visible_short_text(page: "Page", pattern: re.Pattern[str], *, limit: int = 20) -> bool:
    """只扫描短的可见提示，避免静态帮助文案触发频控/错误判断。"""

    selectors = '[role="alert"], [aria-live], [class*="toast" i], [class*="message" i], [class*="notice" i], [class*="notification" i]'
    nodes = _visible(page.locator(selectors))
    try:
        count = min(await nodes.count(), limit)
    except Exception:
        return False
    for index in range(count):
        try:
            text = (await nodes.nth(index).inner_text(timeout=500)).strip()
        except Exception:
            continue
        if text and len(text) <= 300 and pattern.search(text):
            print(f"[KUAISHOU] 页面提示：{text[:160]}")
            return True
    return False


async def _find_shop_cards(page: "Page", shop: str) -> "Locator":
    cards = _visible(page.locator('[class*="accountItem"]')).filter(has_text=shop)
    if await cards.count():
        return cards.last
    # 版本类名变化时，通过店铺名向上寻找最近的可点击祖先。
    name = _visible(page.get_by_text(shop, exact=True)).last
    if await name.count():
        ancestor = name.locator(
            "xpath=ancestor::*[contains(translate(@class,'ACCOUNTITEM','accountitem'),'accountitem')][1]"
        )
        if await ancestor.count():
            return ancestor
        return name
    return cards


@automation_component("kuaishou.ensure_login", "快手 · 检查登录态", category="report")
async def ensure_kuaishou_login(page: "Page", shop: str) -> "Page":
    """在当前 profile 中完成员工登录和店铺选择。

    账号与密码由 profile 保存；脚本不读取 Chrome 密码库。若保存凭据没有被
    页面自动带出，可通过未写入源码的 ``KUAISHOU_LOGIN_USERNAME`` /
    ``KUAISHOU_LOGIN_PASSWORD`` 进程环境变量补填。
    """

    if page.url.startswith("https://s.kwaixiaodian.com/zone/"):
        return page
    if not page.url or page.url == "about:blank":
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    if page.url.startswith("https://s.kwaixiaodian.com/zone/"):
        return page
    if "login.kwaixiaodian.com" not in page.url:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)

    employee = _visible(page.get_by_text("我是员工", exact=True))
    if await employee.count():
        with suppress(Exception):
            await click_compat(employee.last)

    login_button = _visible(page.get_by_role("button", name="快手商家账号登录", exact=True)).last
    if not await login_button.count():
        raise RuntimeError("快手登录页未找到“快手商家账号登录”按钮")

    async def wait_login_result(seconds: float = 20.0) -> bool:
        deadline = asyncio.get_running_loop().time() + seconds
        while asyncio.get_running_loop().time() < deadline:
            if page.url.startswith("https://s.kwaixiaodian.com/zone/"):
                return True
            cards = await _find_shop_cards(page, shop)
            if await cards.count():
                return False
            await asyncio.sleep(0.25)
        return False

    with suppress(Exception):
        await click_compat(login_button)
    if not await wait_login_result(30):
        cards = await _find_shop_cards(page, shop)
        if not await cards.count():
            # 仅在 profile 保存的表单确实没有触发登录时使用显式环境变量；
            # 不读取或打印任何输入框明文。
            username = os.getenv("KUAISHOU_LOGIN_USERNAME") or os.getenv("KS_LOGIN_USERNAME")
            password = os.getenv("KUAISHOU_LOGIN_PASSWORD") or os.getenv("KS_LOGIN_PASSWORD")
            if username and password:
                account = _visible(page.locator('input[placeholder*="手机号"], input[type="text"]')).first
                secret = _visible(page.locator('input[placeholder*="密码"], input[type="password"]')).first
                if await account.count() and await secret.count():
                    await account.fill(username)
                    await secret.fill(password)
                    await click_compat(login_button)
                    await wait_login_result(30)
            cards = await _find_shop_cards(page, shop)

    if page.url.startswith("https://s.kwaixiaodian.com/zone/"):
        return page
    cards = await _find_shop_cards(page, shop)
    if not await cards.count():
        text = await _body_text(page)
        if "选择登录店铺" in text:
            raise RuntimeError(f"快手登录成功但未找到店铺“{shop}”")
        raise RuntimeError("快手员工登录未完成；请在指定 profile 中保存账号密码")
    await click_compat(cards.last)
    deadline = asyncio.get_running_loop().time() + 45
    while asyncio.get_running_loop().time() < deadline:
        if page.url.startswith("https://s.kwaixiaodian.com/zone/"):
            return page
        await asyncio.sleep(0.25)
    raise TimeoutError("选择快手登录店铺后未进入商家后台")


@automation_component("kuaishou.order.open_page", "快手订单 · 打开页面", category="report")
async def open_order_page(context: "BrowserContext", shop: str) -> tuple["Page", bool]:
    existing = next(
        (
            candidate
            for candidate in context.pages
            if not candidate.is_closed() and "/zone/order/list" in candidate.url
        ),
        None,
    )
    if existing is not None:
        await existing.bring_to_front()
        return existing, False

    available_pages = [candidate for candidate in context.pages if not candidate.is_closed()]
    # Cloak/快手偶尔会留下一个旧登录页或 about:blank；优先复用已认证的
    # zone 页面，避免把 stale 登录页误当成当前 profile 页面。
    page = next(
        (candidate for candidate in available_pages if candidate.url.startswith("https://s.kwaixiaodian.com/zone/")),
        None,
    ) or (available_pages[0] if available_pages else None)
    created = page is None
    if page is None:
        page = await context.new_page()
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    page = await ensure_kuaishou_login(page, shop)

    # A previous interrupted run may have left the profile on the export
    # history page.  That page is authenticated but does not render the home
    # navigation, so return to the home route before locating “订单查询”.
    if "/zone/order/list" not in page.url and not page.url.rstrip("/").endswith("/zone/home"):
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)

    if "/zone/order/list" not in page.url:
        # 首页由前端异步渲染；domcontentloaded 只代表 HTML 已到达，首屏菜单
        # 可能仍为空。必须等“订单查询”真实出现在可见 DOM 后再点击，避免
        # 首次进入 profile 时因过早查找而误报“未找到入口”。
        nav = _visible(page.get_by_text("订单查询", exact=True))
        try:
            await nav.last.wait_for(state="visible", timeout=30_000)
        except PlaywrightTimeout:
            # 首页通常有“订单查询”快捷入口；若页面还没有渲染快捷区，
            # 先点击“订单”展开一级菜单再重新定位。
            order_menu = _visible(page.get_by_text("订单", exact=True))
            try:
                await order_menu.last.wait_for(state="visible", timeout=10_000)
            except PlaywrightTimeout as exc:
                raise RuntimeError("快手首页未找到“订单查询”入口") from exc
            with suppress(Exception):
                await click_compat(order_menu.last)
            nav = _visible(page.get_by_text("订单查询", exact=True))
            try:
                await nav.last.wait_for(state="visible", timeout=15_000)
            except PlaywrightTimeout as exc:
                raise RuntimeError("快手首页未找到“订单查询”入口") from exc
        await click_compat(nav.last)
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            if "/zone/order/list" in page.url:
                break
            candidate = next(
                (item for item in context.pages if not item.is_closed() and "/zone/order/list" in item.url),
                None,
            )
            if candidate is not None:
                page = candidate
                break
            await asyncio.sleep(0.2)
        if "/zone/order/list" not in page.url and not any(
            not item.is_closed() and "/zone/order/list" in item.url for item in context.pages
        ):
            raise TimeoutError("点击“订单查询”后未进入快手订单列表")
    await _visible(page.get_by_role("button", name=_QUERY_RE)).last.wait_for(
        state="visible", timeout=60_000
    )
    return page, created


async def _input_values(page: "Page") -> tuple[str, str]:
    start = _visible(page.locator('input[placeholder="开始时间"]')).first
    end = _visible(page.locator('input[placeholder="结束时间"]')).first
    if not await start.count() or not await end.count():
        raise RuntimeError("快手订单页未找到开始时间/结束时间输入框")
    return await start.input_value(), await end.input_value()


async def _force_fill_readonly(locator: "Locator", value: str) -> None:
    try:
        await locator.fill(value, timeout=3_000)
    except Exception:
        await locator.evaluate("(element, value) => { element.removeAttribute('readonly'); element.value = value; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }", value)


async def _ensure_time_inputs(page: "Page") -> tuple["Locator", "Locator"]:
    """等待日期输入框；查询条件折叠时先展开“展开全部”。

    快手订单页首屏偶尔只渲染查询项设置和少量条件，开始/结束时间会被
    放在折叠区域内。这里先给页面一个短暂的正常渲染窗口；若仍不可见，
    点击当前可见的折叠控件，再重新等待输入框，避免把“未渲染”误判为
    页面结构不支持日期筛选。
    """

    start_selector = 'input[placeholder="开始时间"]'
    end_selector = 'input[placeholder="结束时间"]'
    start = _visible(page.locator(start_selector)).first
    end = _visible(page.locator(end_selector)).first
    try:
        await start.wait_for(state="visible", timeout=8_000)
        await end.wait_for(state="visible", timeout=8_000)
        return start, end
    except PlaywrightTimeout:
        # 该节点是快手 ProForm 的折叠控件，类名比文案稳定；文案定位作为
        # 版本兼容保底。只对可见节点操作，避免点击隐藏旧节点。
        expand = _visible(page.locator(".ant-pro-form-layout-collapse")).last
        if not await expand.count():
            expand = _visible(page.get_by_text("展开全部", exact=True)).last
        if await expand.count():
            await expand.wait_for(state="visible", timeout=8_000)
            await click_compat(expand)
        # 重新创建可见 locator，确保点击折叠控件后使用的是新渲染的节点。
        start = _visible(page.locator(start_selector)).first
        end = _visible(page.locator(end_selector)).first
        await start.wait_for(state="visible", timeout=30_000)
        await end.wait_for(state="visible", timeout=30_000)
        return start, end


@automation_component("report.date_range.set", "设置业务日期范围", category="report")
async def choose_recent_month(
    page: "Page", start_date: str, end_date: str, *, use_preset: bool = True
) -> tuple[str, str]:
    """优先点击弹层快捷项；当前快手页面没有快捷项时使用日历/输入保底。"""

    start, end = await _ensure_time_inputs(page)
    try:
        await start.click(timeout=8_000)
    except Exception:
        await start.locator("xpath=ancestor::div[contains(@class,'ant-picker-range')][1]").click()

    if use_preset:
        preset = _visible(page.locator(".ant-picker-dropdown li.ant-picker-preset").filter(has_text=re.compile(r"^\s*最近一个月\s*$"))).last
        try:
            await preset.wait_for(state="visible", timeout=8_000)
            await click_compat(preset)
            for _ in range(30):
                values = await _input_values(page)
                if values[0] and values[1]:
                    print(f"[KUAISHOU] 已选择“最近一个月”：{values[0]} ~ {values[1]}")
                    return values
                await asyncio.sleep(0.15)
        except Exception:
            # 保底路径：通过键盘输入指定范围。快手不同版本的 readonly 属性
            # 仅用于阻止鼠标编辑，移除后仍会触发 React 的 input/change 事件。
            with suppress(Exception):
                await page.keyboard.press("Escape")

    start_value = f"{start_date} 00:00:00"
    end_value = f"{end_date} 23:59:59"
    await _force_fill_readonly(start, start_value)
    await start.press("Enter")
    await _force_fill_readonly(end, end_value)
    await end.press("Enter")
    actual = await _input_values(page)
    if not actual[0] or not actual[1]:
        raise RuntimeError(f"快手订单时间范围选择失败：{actual[0]!r} ~ {actual[1]!r}")
    print(f"[KUAISHOU] 已使用日期保底：{actual[0]} ~ {actual[1]}")
    return actual


@automation_component("kuaishou.order.query", "快手订单 · 查询", category="report")
async def click_query_and_wait(page: "Page", *, timeout_seconds: float = 20.0) -> None:
    before = await _body_text(page)
    response_seen = False

    def on_response(response) -> None:
        nonlocal response_seen
        if response.status == 200 and any(
            fragment in response.url
            for fragment in ("/seller/order/query/v3", "/seller/order/query/view", "/order/query")
        ):
            response_seen = True

    page.on("response", on_response)
    try:
        query = _visible(page.get_by_role("button", name=_QUERY_RE)).last
        await click_compat(query)
        deadline = asyncio.get_running_loop().time() + max(3.0, min(timeout_seconds, 20.0))
        while asyncio.get_running_loop().time() < deadline:
            if response_seen:
                await asyncio.sleep(0.3)
                return
            current = await _body_text(page)
            if current != before:
                return
            await asyncio.sleep(0.25)
        if not response_seen:
            raise TimeoutError("快手订单查询在等待窗口内未完成")
    finally:
        page.remove_listener("response", on_response)


async def open_export_panel(page: "Page") -> "Locator":
    button = _visible(page.get_by_role("button", name="导出数据", exact=True)).last
    if not await button.count():
        raise RuntimeError("快手订单页未找到“导出数据”按钮")
    await click_compat(button)
    drawer = _visible(page.locator(".ant-drawer.ant-drawer-open")).last
    await drawer.wait_for(state="visible", timeout=15_000)
    return drawer


async def read_order_record_count(page: "Page") -> int:
    """读取订单列表当前筛选结果的可见记录数。"""

    count_locator = page.locator('div[class*="pro-toolbar-total-content"]:visible')
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        for index in range(await count_locator.count()):
            count = parse_order_record_count(
                (await count_locator.nth(index).inner_text()).strip()
            )
            if count is not None:
                return count
        await asyncio.sleep(0.25)
    raise RuntimeError("查询后未识别快手订单结果数")


async def ensure_standard_report(drawer: "Locator") -> None:
    standard = _visible(drawer.locator('[class*="tabItem"]').filter(has_text=_STANDARD_RE)).last
    if not await standard.count():
        standard = _visible(drawer.get_by_text("标准报表", exact=True)).last
    if not await standard.count():
        raise RuntimeError("快手导出侧栏未找到“标准报表”选项")
    classes = await standard.get_attribute("class") or ""
    aria = await standard.get_attribute("aria-selected")
    if "Active" not in classes and "active" not in classes.lower() and aria not in {"true", "1"}:
        await click_compat(standard)


async def _find_code_dialog(page: "Page") -> "Locator | None":
    # 快手当前版本会把短信校验直接渲染在订单导出 drawer 内，稳定标识是
    # #register_captcha/“请输入验证码”；优先从输入框向上取 drawer body，
    # 不依赖外层 role 或动态 CSS 类名。
    code_field = _visible(page.locator('#register_captcha, input[placeholder="请输入验证码"]')).first
    if await code_field.count():
        drawer_body = _visible(
            code_field.locator("xpath=ancestor::div[contains(@class,'ant-drawer-body')][1]")
        ).first
        if await drawer_body.count():
            return drawer_body
        form = _visible(code_field.locator("xpath=ancestor::form[1]")).first
        if await form.count():
            return form

    candidates = _visible(page.locator(
        '[role="dialog"], [role="document"], .ant-modal, '
        '.ant-drawer.ant-drawer-open, .ant-drawer-content, .ant-drawer-body, '
        '[class*="phoneVertify" i], [class*="codeForm" i], '
        '[class*="modal" i], [class*="dialog" i]'
    ))
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        try:
            text = (await candidate.inner_text(timeout=500)).strip()
        except Exception:
            continue
        if "验证码" in text or "短信" in text or "获取验证码" in text:
            if await candidate.locator('input:not([type="hidden"]):not([disabled])').count():
                return candidate
    return None


def _is_pending_order_export_text(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text)
    return (
        "批量导出订单" in normalized
        and "生成报表" in normalized
        and ("短信验证码" in normalized or "请输入验证码" in normalized)
    )


async def _pending_order_export_drawer(page: "Page") -> "Locator | None":
    """Return a still-open order-export drawer when a previous run stopped at SMS verification."""

    if await _find_code_dialog(page) is None:
        return None
    drawer = _visible(page.locator(".ant-drawer.ant-drawer-open")).last
    if not await drawer.count():
        return None
    text = (await drawer.inner_text(timeout=1_000)).strip()
    return drawer if _is_pending_order_export_text(text) else None


async def _code_input(dialog: "Locator") -> "Locator":
    specific = _visible(dialog.locator(
        'input[placeholder*="验证码"], input[aria-label*="验证码"], input[name*="verify" i], input[id*="verify" i], input[name*="captcha" i], input[id*="captcha" i]'
    )).first
    if await specific.count():
        return specific
    return _visible(dialog.locator('input:not([type="hidden"]):not([disabled])')).first


async def _platform_response_state(response: Any, *, action: str) -> str:
    """读取快手接口结果；只返回状态，不记录响应正文。"""

    body = ""
    with suppress(Exception):
        body = await response.text()
    if _RATE_LIMIT_RE.search(body):
        return "rate_limit"
    status = int(getattr(response, "status", 0) or 0)
    if status < 200 or status >= 300:
        raise RuntimeError(f"快手{action}接口 HTTP {status}")
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        return "ok"

    code = payload.get("code")
    if code is not None and str(code).lower() not in {"0", "200", "true", "success"}:
        raise RuntimeError(f"快手{action}接口返回业务失败")
    for key in ("success", "ok"):
        if payload.get(key) is False:
            raise RuntimeError(f"快手{action}接口返回业务失败")
    return "ok"


async def _click_get_code(dialog: "Locator", page: "Page") -> None:
    get_code = _visible(dialog.get_by_text("获取验证码", exact=True)).last
    if not await get_code.count():
        get_code = _visible(page.get_by_text("获取验证码", exact=True)).last
    if not await get_code.count():
        raise RuntimeError("快手订单验证码弹窗未找到“获取验证码”按钮")
    await get_code.wait_for(state="visible", timeout=8_000)
    response = None
    try:
        async with page.expect_response(
            lambda candidate: _ENCRYPT_PHONE_API_FRAGMENT in candidate.url,
            timeout=15_000,
        ) as response_info:
            await click_compat(get_code)
        response = await response_info.value
    except PlaywrightTimeout:
        # 某些 profile 中短信请求已经完成并改变了页面状态，但 CDP 没有把
        # 该跨域响应交给 expect_response。此时不能把“验证码已发送”误报成
        # 失败；继续用平台弹窗的发送确认收口，后续提交仍然以导出接口结果为准。
        pass
    if response is not None:
        response_state = await _platform_response_state(response, action="验证码")
        if response_state == "rate_limit":
            raise RuntimeError("快手验证码接口返回操作过于频繁")
    # 点击本身不是成功标准；必须等平台显示已发送提示、倒计时或将按钮置
    # 为 disabled，确认短信请求确实发出后才允许等待人工输入。
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        with suppress(Exception):
            text = (await dialog.inner_text(timeout=500)).strip()
            if "验证码已发送" in text or "请注意查收" in text:
                suffix = "接口响应未被CDP捕获，" if response is None else ""
                print(f"[KUAISHOU] 已点击“获取验证码”，{suffix}平台已确认验证码发送")
                return
        with suppress(Exception):
            if await get_code.is_disabled():
                suffix = "接口响应未被CDP捕获，" if response is None else ""
                print(f"[KUAISHOU] 已点击“获取验证码”，{suffix}按钮已进入倒计时")
                return
            button_text = (await get_code.inner_text(timeout=500)).strip()
            if re.search(r"\d+\s*(?:秒|s)", button_text, flags=re.IGNORECASE):
                suffix = "接口响应未被CDP捕获，" if response is None else ""
                print(f"[KUAISHOU] 已点击“获取验证码”，{suffix}按钮已进入倒计时")
                return
        await asyncio.sleep(0.25)
    raise TimeoutError("点击“获取验证码”后未确认验证码已发送")


async def _verification_error(page: "Page", dialog: "Locator") -> bool:
    for locator in (
        dialog.locator('[role="alert"], [class*="error" i]'),
        _visible(page.locator('[role="alert"], [class*="error" i]')),
    ):
        with suppress(Exception):
            for index in range(min(await locator.count(), 20)):
                text = (await locator.nth(index).inner_text(timeout=500)).strip()
                if text and _ERROR_RE.search(text) and any(word in text for word in ("验证码", "校验码", "错误", "失败")):
                    return True
    return False


@automation_component("human.verification.wait", "等待飞书验证码 / 密码", category="human")
async def _request_stateful_answer(
    *,
    challenge_key: str,
    challenge_type: str,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
    page_url: str,
    state_path: Path,
    state: dict[str, Any],
    after_create: Callable[[], Awaitable[None]] | None = None,
    after_existing: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """保存 challenge_id，重启时继续等待同一条飞书请求。"""

    if "错误" in purpose:
        await reopen_for_human(state, challenge_key)
        _write_state(state_path, state)
    existing_id = str(state.get(challenge_key) or "").strip()
    if existing_id:
        # A process can stop after creating a challenge but before executing
        # the platform-side action (for example, clicking “发送文件提取码”).
        # The caller may request that action once before resuming the same
        # challenge.  SMS verification deliberately leaves this unset so a
        # resumed challenge does not send a second SMS.
        if after_existing is not None:
            await after_existing()
        try:
            answer = await wait_answer(challenge_id=existing_id)
        except RuntimeError as exc:
            message = str(exc)
            stale_verification = (
                challenge_type == "verification_code"
                and "验证码请求不存在" in message
            )
            if (
                "过期" not in message
                and "取消" not in message
                and not stale_verification
            ):
                raise
            state.pop(challenge_key, None)
            _write_state(state_path, state)
        else:
            state.pop(challenge_key, None)
            state[challenge_key + "_last_answered"] = existing_id
            _write_state(state_path, state)
            component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
            return answer

    await asyncio.to_thread(probe_relay)
    challenge = await create_challenge(
        challenge_type=challenge_type,
        platform=platform,
        company=company,
        shop=shop,
        purpose=purpose,
        page_url=page_url,
    )
    challenge_id = str(challenge.get("challenge_id") or "").strip()
    if not challenge_id:
        raise RuntimeError("自动化验证码服务未返回 challenge_id")
    state[challenge_key] = challenge_id
    _write_state(state_path, state)
    component_event("waiting_human", "Challenge 已创建，等待自动接收或人工回复", detail={"challenge_id": challenge_id, "challenge_type": challenge_type if "challenge_type" in locals() else "archive_password"})
    print("[KUAISHOU] 验证码请求已生成，等待自动接收或人工回复")
    try:
        if after_create is not None:
            await after_create()
        answer = await wait_answer(
            challenge_id=challenge_id,
            timeout_seconds=int(challenge.get("timeout_seconds") or 300),
        )
    except RuntimeError as exc:
        if "过期" in str(exc) or "取消" in str(exc):
            state.pop(challenge_key, None)
            _write_state(state_path, state)
        raise
    state.pop(challenge_key, None)
    state[challenge_key + "_last_answered"] = challenge_id
    _write_state(state_path, state)
    component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
    return answer


async def complete_export_verification(
    page: "Page",
    drawer: "Locator",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> None:
    """处理快手订单导出的短信验证码；挑战并非每次都出现。"""

    deadline = asyncio.get_running_loop().time() + 30
    dialog = await _find_code_dialog(page)
    while dialog is None and asyncio.get_running_loop().time() < deadline:
        # 点击“导出”后旧 drawer 会先卸载，新验证码 drawer 可能稍后才挂载；
        # 不能以旧 drawer 短暂不可见作为“无需验证码”的判断。
        await asyncio.sleep(0.25)
        dialog = await _find_code_dialog(page)
    if dialog is None:
        # 无短信挑战时，导出侧栏会关闭或出现成功/频控提示；仅在侧栏仍可见
        # 且没有任何结果时才判定失败，避免将延迟渲染误认为已提交。
        if await _visible(drawer).count():
            text = await _body_text(page)
            if not any(marker in text for marker in ("导出成功", "导出记录", "重复提交", "操作过于频繁")):
                raise RuntimeError("快手订单导出后未找到验证码弹窗或提交结果")
        return

    field = await _code_input(dialog)
    if not await field.count():
        raise RuntimeError("快手订单导出验证码弹窗未找到输入框")
    print("[KUAISHOU] 检测到短信验证码弹窗，准备登记验证码接收请求")
    get_code_clicked = False
    for attempt in range(3):
        if not get_code_clicked:
            await asyncio.to_thread(probe_relay)

        async def request_sms() -> None:
            nonlocal get_code_clicked
            await _click_get_code(dialog, page)
            get_code_clicked = True

        answer = await _request_stateful_answer(
            challenge_key="verification_challenge_id",
            challenge_type="verification_code",
            platform=platform,
            company=company,
            shop=shop,
            purpose="订单报表下载验证码" if attempt == 0 else "上一次验证码输入错误，请重新输入。订单报表下载验证码",
            page_url=page.url,
            state_path=state_path,
            state=state,
            after_create=request_sms,
        )
        await field.fill(answer)
        submit = _visible(dialog.get_by_role("button", name=re.compile(r"生成报表|确定|确认|提交"))).last
        if not await submit.count():
            submit = _visible(page.get_by_role("button", name=re.compile(r"生成报表|确定|确认|提交"))).last
        if not await submit.count():
            raise RuntimeError("快手订单验证码弹窗未找到生成报表按钮")
        try:
            async with page.expect_response(
                lambda response: _EXPORT_SUBMIT_API_FRAGMENT in response.url,
                timeout=15_000,
            ) as response_info:
                await click_compat(submit)
            response = await response_info.value
        except PlaywrightTimeout as exc:
            raise TimeoutError("点击“生成报表”后未捕获快手导出接口响应") from exc
        response_state = await _platform_response_state(response, action="订单导出")
        if response_state == "rate_limit":
            print("[KUAISHOU] 平台导出接口返回操作过于频繁，等待5分钟后重试")
            await asyncio.sleep(300)
            get_code_clicked = False
            with suppress(Exception):
                await field.fill("")
            continue
        await asyncio.sleep(0.5)
        if not await _verification_error(page, dialog):
            return
        print("[KUAISHOU] 验证码输入错误，已申请重新输入")
        get_code_clicked = False
        with suppress(Exception):
            await field.fill("")
    raise NeedsHumanError("连续三次快手订单导出验证码错误")


@automation_component("kuaishou.order.create_export", "快手订单 · 创建导出", category="report")
async def create_export_once(
    page: "Page",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> None:
    drawer = await open_export_panel(page)
    await ensure_standard_report(drawer)
    export = _visible(drawer.get_by_role("button", name=_EXPORT_RE)).last
    if not await export.count():
        raise RuntimeError("快手订单导出侧栏未找到“导出”按钮")
    await click_compat(export)
    await complete_export_verification(
        page,
        drawer,
        platform=platform,
        company=company,
        shop=shop,
        state_path=state_path,
        state=state,
    )
    state["stage"] = "EXPORT_CREATED"
    state["creation_proof"] = "submitted_or_rate_limit"
    state["created_at"] = datetime.now().isoformat(timespec="seconds")
    _write_state(state_path, state)
    print("[KUAISHOU] 订单导出任务已提交")


async def _history_rows(page: "Page") -> list["Locator"]:
    rows = _visible(page.locator("li.ant-list-item"))
    if await rows.count():
        return [rows.nth(index) for index in range(await rows.count())]
    rows = _visible(page.locator('[class*="list-item" i], [class*="report-item" i]'))
    return [rows.nth(index) for index in range(await rows.count())]


async def _row_text(row: "Locator") -> str:
    with suppress(Exception):
        return (await row.inner_text(timeout=2_000)).strip()
    return ""


async def find_matching_history_row(
    page: "Page",
    start_date: str,
    end_date: str,
    *,
    require_download: bool = False,
    created_after: tuple[int, ...] | None = None,
    require_start: bool = False,
) -> "Locator | None":
    candidates: list[tuple[tuple[int, ...], Locator]] = []
    for row in await _history_rows(page):
        text = await _row_text(row)
        if "标准报表" not in text:
            continue
        if not _date_range_matches(text, start_date, end_date, require_start=require_start):
            continue
        created = _parse_created(text)
        if created_after is not None and created <= created_after:
            continue
        if require_download:
            button = _visible(row.get_by_role("button", name=_DOWNLOAD_RE)).first
            if not await button.count():
                continue
        candidates.append((created, row))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1] if candidates else None


async def open_export_history(context: "BrowserContext") -> "Page":
    page = await context.new_page()
    await page.goto(EXPORT_HISTORY_URL, wait_until="domcontentloaded", timeout=60_000)
    # An empty history is valid immediately after task creation.  Wait for
    # the document/list shell rather than requiring the first row to exist;
    # wait_latest_report() will poll rows until the task is generated.
    await page.locator("body").wait_for(state="visible", timeout=30_000)
    with suppress(Exception):
        await page.locator(".ant-list, [class*='list' i]").first.wait_for(
            state="visible", timeout=10_000
        )
    return page


@automation_component("report.wait_export_ready", "等待导出任务就绪", category="report")
async def wait_latest_report(
    page: "Page",
    start_date: str,
    end_date: str,
    *,
    timeout_seconds: float = 900.0,
    created_after: tuple[int, ...] | None = None,
) -> "Locator":
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    reload_count = 0
    while asyncio.get_running_loop().time() < deadline:
        row = await find_matching_history_row(
            page,
            start_date,
            end_date,
            require_download=True,
            created_after=created_after,
            require_start=created_after is not None,
        )
        if row is not None:
            print("[KUAISHOU] 已找到最新可下载标准订单报表")
            return row
        for candidate in await _history_rows(page):
            text = await _row_text(candidate)
            if "生成失败" in text or "导出失败" in text:
                raise RuntimeError(f"快手订单报表生成失败：{text[:200]}")
        await asyncio.sleep(5)
        reload_count += 1
        if reload_count % 6 == 0:
            with suppress(Exception):
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
    raise TimeoutError("等待快手订单报表生成可下载超时")


async def request_file_password(
    page: "Page",
    row: "Locator",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> str:
    text = await _row_text(row)
    report_id_match = re.search(r"报表ID\s*([A-Za-z0-9_-]+)", text)
    report_id = report_id_match.group(1) if report_id_match else "unknown"
    send = _visible(row.get_by_role("button", name=_SEND_CODE_RE)).first

    async def after_create() -> None:
        if not await send.count():
            raise RuntimeError("快手订单历史记录未找到“发送文件提取码”按钮")
        await click_compat(send)
        # 发送动作本身已经触发平台短信/提取码；先落盘这个事实，再等待
        # 确认弹窗，进程若恰好在弹窗阶段中断也不会重复发送。
        state["file_code_sent"] = True
        _write_state(state_path, state)
        # 点击发送后平台会给出确认提醒；必须确认后才会真正发送提取码。
        # 快手按钮的可见名称是“确 定”（中间带空格），不同版本也会
        # 使用“确定/确认”；允许字符间空白但仍要求完整按钮名称。
        confirm = _visible(
            page.get_by_role(
                "button",
                name=re.compile(r"^\s*(?:确\s*定|确\s*认)\s*$"),
            )
        ).last
        try:
            # 弹窗由异步状态更新渲染，不能先用 count() 做瞬时判断；
            # wait_for 会在按钮稍后出现时继续等待。
            await confirm.wait_for(state="visible", timeout=12_000)
        except PlaywrightTimeout as exc:
            raise RuntimeError("快手订单发送文件提取码后未找到确认按钮") from exc
        await click_compat(confirm)

    # 如果任务重启时 challenge_id 已保存，复用同一条 Challenge；只有
    # 该 Challenge 在创建后尚未执行平台发送动作时才补点一次按钮。
    sent = bool(state.get("file_code_sent"))
    existing_id = bool(str(state.get("file_password_challenge_id") or "").strip())
    # 已存在的 Challenge 可能已经触发过平台发送；为避免重复短信/提取码，
    # 重启时只等待原 Challenge，不再次点击发送。全新 Challenge 才执行
    # after_create；正常首次运行仍由该回调完成发送和确认。
    callback = None if sent or existing_id else after_create
    return await _request_stateful_answer(
        challenge_key="file_password_challenge_id",
        challenge_type="archive_password",
        platform=platform,
        company=company,
        shop=shop,
        purpose=f"订单报表文件提取码（报表ID {report_id}）",
        page_url=page.url,
        state_path=state_path,
        state=state,
        after_create=callback,
        after_existing=callback,
    )


@automation_component("file.download", "下载报表文件", category="file")
async def send_file_code_and_download(
    page: "Page",
    row: "Locator",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
    work_dir: Path,
) -> tuple[Path, str]:
    password = await request_file_password(
        page,
        row,
        platform=platform,
        company=company,
        shop=shop,
        state_path=state_path,
        state=state,
    )

    download = None
    button = _visible(row.get_by_role("button", name=_DOWNLOAD_RE)).first
    if not await button.count():
        raise RuntimeError("快手订单历史记录未找到“下载报表”按钮")
    try:
        async with page.expect_download(timeout=120_000) as info:
            await click_compat(button)
        download = await info.value
    except PlaywrightTimeout as exc:
        raise TimeoutError("快手订单报表下载超时") from exc
    downloaded = await save_download(download, work_dir, "kuaishou_order.xlsx")
    state["stage"] = "DOWNLOADED"
    state["download_path"] = str(downloaded)
    _write_state(state_path, state)
    print(f"[KUAISHOU] 订单报表已下载：{downloaded}")
    return downloaded, password


def decrypt_xlsx(source: Path, password: str, destination: Path) -> Path:
    """用 msoffcrypto 解密快手加密 XLSX；未加密文件直接复制。"""

    try:
        import msoffcrypto  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 XLSX 解密依赖 msoffcrypto-tool，请先安装该包") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as input_file:
            office = msoffcrypto.OfficeFile(input_file)
            encrypted = bool(office.is_encrypted())
            if not encrypted:
                shutil.copy2(source, destination)
                return destination
            office.load_key(password=password)
            with destination.open("wb") as output_file:
                office.decrypt(output_file)
    except Exception as exc:
        message = str(exc).lower()
        if "password" in message or "key" in message or "decrypt" in message or "encrypted" in message:
            raise ValueError("快手订单文件提取码错误") from exc
        raise RuntimeError(f"快手订单 XLSX 解密失败：{exc}") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("快手订单解密后的 XLSX 文件为空")
    return destination


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_xlsx(path: Path) -> None:
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 XLSX 校验依赖 openpyxl") from exc
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        if not workbook.sheetnames:
            raise RuntimeError("快手订单 XLSX 没有工作表")
        workbook.close()
    except Exception as exc:
        raise RuntimeError(f"快手订单 XLSX 读取校验失败：{exc}") from exc


def move_report(source: Path, *, platform: str, company: str, shop: str, business_date: str, dest: Path) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.auto_download.move_report",
            "--platform",
            platform,
            "--company",
            company,
            "--shop",
            shop,
            "--report",
            REPORT_NAME,
            "--date",
            business_date,
            "--src",
            str(source.parent),
            "--dest",
            str(dest),
            "--pattern",
            source.name,
            "--within",
            "30",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


@automation_component("file.archive.extract", "解压 / 解密归档", category="file")
async def process_download(
    page: "Page",
    downloaded: Path,
    first_password: str,
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
    business_date: str,
    dest: Path,
) -> None:
    state["stage"] = "DECRYPTING"
    _write_state(state_path, state)
    target = downloaded.with_name(f"{downloaded.stem}_decrypted.xlsx")
    passwords = [first_password]
    for attempt in range(3):
        password = passwords[-1]
        try:
            # 上一次错误密码可能已经留下了部分解密文件；删除后再尝试，
            # 避免 openpyxl 读取到残缺输出而掩盖真正的提取码结果。
            with suppress(OSError):
                target.unlink(missing_ok=True)
            await asyncio.to_thread(decrypt_xlsx, downloaded, password, target)
            await asyncio.to_thread(validate_xlsx, target)
            break
        except ValueError:
            if attempt >= 2:
                # msoffcrypto 可能已经写出一个不完整的目标文件后才报告
                # 密码错误；失败恢复必须只保留原始加密 XLSX，避免后续
                # 任务误把残缺文件当成可读取报表。
                with suppress(OSError):
                    target.unlink(missing_ok=True)
                raise NeedsHumanError("连续三次快手订单文件提取码错误，保留加密 XLSX 供人工恢复")
            print("[KUAISHOU] 文件提取码输入错误，已申请重新输入；不重复下载报表")
            state["stage"] = "PASSWORD_REQUIRED"
            _write_state(state_path, state)
            retry = await _request_stateful_answer(
                challenge_key="file_password_challenge_id",
                challenge_type="archive_password",
                platform=platform,
                company=company,
                shop=shop,
                purpose=f"上一次文件提取码错误，请重新输入。订单报表文件提取码（{downloaded.name}）",
                page_url=page.url,
                state_path=state_path,
                state=state,
            )
            passwords.append(retry)
    else:
        raise RuntimeError("快手订单 XLSX 解密失败")

    print(await asyncio.to_thread(move_report, target, platform=platform, company=company, shop=shop, business_date=business_date, dest=dest))
    state["stage"] = "COMPLETED"
    state["report_path"] = str(target)
    _write_state(state_path, state)
    with suppress(OSError):
        downloaded.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        state_path.unlink(missing_ok=True)
    print("[KUAISHOU] 订单报表解密、归档完成")


@automation_component("kuaishou.order.workflow", "快手订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    business_date: str | None = None,
    start_date_override: str | None = None,
    end_date_override: str | None = None,
    force_new: bool = False,
) -> int:
    default_start_date, default_end_date = recent_month_range()
    start_date = start_date_override or default_start_date
    end_date = end_date_override or default_end_date
    custom_range = start_date_override is not None or end_date_override is not None
    business_date = business_date or end_date
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(work_dir)
    state = _read_state(state_path)
    if (
        force_new
        or state.get("start_date") != start_date
        or state.get("end_date") != end_date
        or state.get("stage") == "COMPLETED"
    ):
        state = {
            "platform": platform,
            "company": company,
            "shop": shop,
            "start_date": start_date,
            "end_date": end_date,
            "stage": "EXPORT_NOT_CREATED",
        }
        _write_state(state_path, state)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器没有可用上下文")
        context = browser.contexts[0]
        page, created = await open_order_page(context, shop)
        history_page: Page | None = None
        created_after: tuple[int, ...] | None = None
        try:
            if state.get("stage") == "EXPORT_NOT_CREATED" and not force_new:
                pending_drawer = await _pending_order_export_drawer(page)
                if pending_drawer is not None:
                    print("[KUAISHOU] 检测到上次中断后仍打开的订单短信验证码弹窗，恢复该导出")
                    await complete_export_verification(
                        page,
                        pending_drawer,
                        platform=platform,
                        company=company,
                        shop=shop,
                        state_path=state_path,
                        state=state,
                    )
                    state["stage"] = "EXPORT_CREATED"
                    state["creation_proof"] = "resumed_pending_verification"
                    state["created_at"] = datetime.now().isoformat(timespec="seconds")
                    _write_state(state_path, state)
            if state.get("stage") == "EXPORT_NOT_CREATED":
                await choose_recent_month(page, start_date, end_date, use_preset=not custom_range)
                await click_query_and_wait(page)
                record_count = await read_order_record_count(page)
                print(f"[KUAISHOU] 订单查询记录数：{record_count}")
                if record_count == 0:
                    state["stage"] = "COMPLETED"
                    state["completion_proof"] = "zero_records_skip"
                    state["record_count"] = 0
                    state["completed_at"] = datetime.now().isoformat(timespec="seconds")
                    _write_state(state_path, state)
                    print("[KUAISHOU] 订单查询无记录，跳过导出")
                    return 0
                history_page = await open_export_history(context)
                if force_new:
                    started = datetime.now()
                    created_after = (
                        started.year,
                        started.month,
                        started.day,
                        started.hour,
                        started.minute,
                        started.second,
                    )
                    state["creation_mode"] = "force_new"
                    _write_state(state_path, state)
                    print("[KUAISHOU] 强制新建订单报表：忽略已有历史任务")
                    await page.bring_to_front()
                    await create_export_once(
                        page,
                        platform=platform,
                        company=company,
                        shop=shop,
                        state_path=state_path,
                        state=state,
                    )
                    await history_page.reload(wait_until="domcontentloaded", timeout=60_000)
                else:
                    # 已有完全匹配任务时直接复用，兼容快手五分钟导出限频。
                    existing = await find_matching_history_row(history_page, start_date, end_date)
                    if existing is not None:
                        state["stage"] = "EXPORT_CREATED"
                        state["creation_proof"] = "history_reused"
                        _write_state(state_path, state)
                        print("[KUAISHOU] 已发现相同日期范围的历史任务，复用该任务")
                    else:
                        await page.bring_to_front()
                        await create_export_once(
                            page,
                            platform=platform,
                            company=company,
                            shop=shop,
                            state_path=state_path,
                            state=state,
                        )
                        await history_page.bring_to_front()
            if history_page is None or history_page.is_closed():
                history_page = await open_export_history(context)
            row = await wait_latest_report(
                history_page,
                start_date,
                end_date,
                created_after=created_after,
            )
            downloaded = Path(state.get("download_path", "")) if state.get("download_path") else None
            password = ""
            if not downloaded or not downloaded.is_file():
                downloaded, password = await send_file_code_and_download(
                    history_page,
                    row,
                    platform=platform,
                    company=company,
                    shop=shop,
                    state_path=state_path,
                    state=state,
                    work_dir=work_dir,
                )
            else:
                # 下载已完成但进程可能在解密前中断时，重新打开同一行
                # 请求/等待提取码；若状态中已经确认发送，则不会再次发送。
                password = await request_file_password(
                    history_page,
                    row,
                    platform=platform,
                    company=company,
                    shop=shop,
                    state_path=state_path,
                    state=state,
                )
            await process_download(
                history_page,
                downloaded,
                password,
                platform=platform,
                company=company,
                shop=shop,
                state_path=state_path,
                state=state,
                business_date=business_date,
                dest=dest,
            )
        finally:
            if history_page is not None and not history_page.is_closed():
                with suppress(Exception):
                    await history_page.close()
            if created and not page.is_closed():
                with suppress(Exception):
                    await page.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="快手订单最近一个月标准报表下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--platform", default=PLATFORM)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--work-dir", default=None, help="可恢复工作目录；默认 data\\.automation_cache\\kuaishou_order\\<shop>")
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--business-date", default=None, help="归档日期前缀，默认查询结束日期")
    parser.add_argument("--start-date", default=None, help="订单查询起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="订单查询结束日期，格式 YYYY-MM-DD")
    parser.add_argument(
        "--force-new",
        action="store_true",
        help="忽略已有历史任务，重新生成本次日期范围报表并校验生成时间",
    )
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if bool(args.start_date) != bool(args.end_date):
        print("--start-date 和 --end-date 必须同时提供", file=sys.stderr)
        return 2
    if args.start_date and args.end_date:
        try:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        except ValueError:
            print("--start-date/--end-date 必须为 YYYY-MM-DD", file=sys.stderr)
            return 2
        if start_date > end_date:
            print("--start-date 不能晚于 --end-date", file=sys.stderr)
            return 2
        start_date_override = start_date.isoformat()
        end_date_override = end_date.isoformat()
    else:
        start_date_override = None
        end_date_override = None
    work_dir = Path(args.work_dir) if args.work_dir else Path(args.dest) / ".automation_cache" / "kuaishou_order" / args.shop
    try:
        return asyncio.run(
            run(
                args.cdp,
                args.platform,
                args.company,
                args.shop,
                work_dir,
                Path(args.dest),
                args.business_date,
                start_date_override,
                end_date_override,
                args.force_new,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 2 if getattr(exc, 'requires_human', False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
