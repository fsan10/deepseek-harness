# -*- coding: utf-8 -*-
"""下载天猫“宝贝销售明细报表”订单报表并归档。

脚本只接收 Cloak Login profile 的 CDP wsEndpoint，登录由现有的
``tmall_finance_login.ensure_tmall_login`` 统一处理。页面上的关键操作仍然
使用真实可见控件完成；只有普通点击没有触发页面事件时，才回退为 DOM click，
以兼容千牛新版页面的 target=_blank 和 React 事件包装。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import (
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from ..move_report import parse_date
from .component_runtime import automation_component
from .login_extensions.tmall_finance_login import (
    DEFAULT_PASSWORD_ENV as DEFAULT_FINANCE_PASSWORD_ENV,
    ensure_tmall_login,
)
from .tmall_alipay_fund_download import find_work_page, run_project_module, unique_download_path

PLATFORM = "天猫"
REPORT_NAME = "订单"
REPORT_TYPE = "宝贝销售明细报表"
DEFAULT_PROFILE = "TMALL-天猫-MOCK旗舰店"
DEFAULT_USERNAME = "mock旗舰店:IT"
DEFAULT_PASSWORD_ENV = "TMALL_IT_LOGIN_PASSWORD"
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")
PROJECT_ROOT = Path(__file__).resolve().parents[3]

SELLER_HOME_URL = "https://myseller.taobao.com/home.htm"
ORDER_PAGE_URL = "https://myseller.taobao.com/home.htm/trade-platform/tp/sold"
EXPORT_LIST_URL = "https://myseller.taobao.com/home.htm/trade-platform/tp/export-list"
ORDER_PAGE_PATH = "/trade-platform/tp/sold"
EXPORT_LIST_PATH = "/trade-platform/tp/export-list"

DATE_TRIGGER_XPATH = (
    '//*[@id="icestarkNode"]/div/div[2]/div/div[3]/div[2]/div/div/form/div[7]/div/div/div'
)
SEARCH_BUTTON_XPATH = (
    '//*[@id="icestarkNode"]/div/div[2]/div/div[3]/div[2]/div/div/form/div[19]/button'
)

REQUIRED_FIELDS = (
    "子订单编号",
    "主订单编号",
    "商品标题",
    "购买数量",
    "商品属性",
    "订单状态",
    "商家编码",
    "买家应付货款",
    "买家实付金额",
    "退款状态",
    "退款金额",
    "订单创建时间",
    "订单付款时间",
)
REQUIRED_FIELD_SET = frozenset(REQUIRED_FIELDS)

RATE_LIMIT_RE = re.compile(r"5\s*分钟内只能导出一次|五分钟内只能导出一次")
DATE_RE = re.compile(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})")
DATETIME_RE = re.compile(
    r"(?P<date>20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})"
    r"(?:[ T日]\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{1,2})"
    r"(?:[:：](?P<second>\d{1,2}))?)?"
)

STATE_FILENAME = "tmall_order_download_state.json"
STATE_VERSION = 1


def log(message: str) -> None:
    """输出可被自动化流程识别的阶段日志。"""
    print(f"[TMALL] {message}", flush=True)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def recent_month_range(today: dt.date | None = None) -> tuple[str, str]:
    """返回“今天往前 30 天”到今天，日期格式与页面输入一致。"""
    end = today or dt.date.today()
    return (end - dt.timedelta(days=30)).isoformat(), end.isoformat()


def resolve_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """解析 CLI 日期；只传一端时按近一个月规则补齐另一端。"""
    if start_date is None and end_date is None:
        return recent_month_range()

    if end_date is None:
        try:
            end = dt.date.fromisoformat(dt.date.today().isoformat())
        except ValueError as exc:  # pragma: no cover - today() 不会触发
            raise ValueError("系统日期无法解析") from exc
    else:
        try:
            end = dt.date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError(f"结束日期格式错误：{end_date}，应为 YYYY-MM-DD") from exc

    if start_date is None:
        start = end - dt.timedelta(days=30)
    else:
        try:
            start = dt.date.fromisoformat(start_date)
        except ValueError as exc:
            raise ValueError(f"开始日期格式错误：{start_date}，应为 YYYY-MM-DD") from exc

    if start > end:
        raise ValueError(f"开始日期不能晚于结束日期：{start.isoformat()} > {end.isoformat()}")
    return start.isoformat(), end.isoformat()


def parse_history_date(value: str) -> dt.date | None:
    match = DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return dt.date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def parse_history_datetime(value: str) -> dt.datetime | None:
    match = DATETIME_RE.search(value or "")
    if not match:
        return None
    date_value = parse_history_date(match.group("date"))
    if date_value is None:
        return None
    try:
        return dt.datetime(
            date_value.year,
            date_value.month,
            date_value.day,
            int(match.group("hour") or 0),
            int(match.group("minute") or 0),
            int(match.group("second") or 0),
        )
    except ValueError:
        return None


def history_range(text: str) -> tuple[str, str] | None:
    match = re.search(
        r"创建时间\s*[:：]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})"
        r".*?到\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2})",
        text or "",
    )
    if not match:
        return None
    start = parse_history_date(match.group(1))
    end = parse_history_date(match.group(2))
    if start is None or end is None:
        return None
    return start.isoformat(), end.isoformat()


def history_range_matches(text: str, start_date: str, end_date: str) -> bool:
    """匹配历史页日期；兼容页面将起始日显示为输入日前一天的版本。"""
    value = history_range(text)
    if value is None:
        return False
    expected_start = dt.date.fromisoformat(start_date)
    allowed_starts = {
        expected_start.isoformat(),
        (expected_start - dt.timedelta(days=1)).isoformat(),
    }
    return value[0] in allowed_starts and value[1] == end_date


def state_request(start_date: str, end_date: str, company: str, shop: str) -> dict[str, str]:
    return {
        "platform": PLATFORM,
        "report": REPORT_NAME,
        "report_type": REPORT_TYPE,
        "company": company,
        "shop": shop,
        "start_date": start_date,
        "end_date": end_date,
    }


def default_work_dir(dest: Path, shop: str) -> Path:
    safe_shop = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", shop).strip("._") or "shop"
    return dest / ".automation_cache" / "tmall_order" / safe_shop


def read_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"导出状态文件无法读取：{path}") from exc
    if not isinstance(value, dict) or value.get("version") != STATE_VERSION:
        raise RuntimeError(f"导出状态文件版本不兼容：{path}")
    return value


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def new_state(request: dict[str, str]) -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "request": request,
        "stage": "NOT_STARTED",
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }


def update_state(path: Path, state: dict[str, Any], stage: str, **values: Any) -> None:
    state["stage"] = stage
    state["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    state.update(values)
    write_state(path, state)


def _visible(locator: Locator) -> Locator:
    return locator.filter(visible=True)


async def click_compat(locator: Locator) -> None:
    """先做真实点击，目标被遮挡或新版页面未响应时回退 DOM click。"""
    try:
        await locator.click(timeout=8_000)
    except (PlaywrightTimeout, PlaywrightError):
        await locator.evaluate("node => node.click()")


async def dismiss_intrusive_popup(page: Page) -> bool:
    """关闭千牛订单页会拦截日期控件的直播活动弹窗。

    该弹窗没有可访问文本，真实 DOM 以 ``popupWindow_body__6Gqd4``
    图片链接和 ``next-icon-close`` 关闭图标标识；只处理这个特征，避免
    误关日期、导出或注意事项等业务弹窗。
    """
    wrappers = page.locator("#qn-worbench-container .next-overlay-wrapper.opened")
    for index in range(await wrappers.count() - 1, -1, -1):
        wrapper = wrappers.nth(index)
        if not await wrapper.locator("a.popupWindow_body__6Gqd4").count():
            continue
        close = _visible(wrapper.locator(".next-icon-close")).last
        if not await close.count():
            continue
        await click_compat(close)
        with suppress(PlaywrightTimeout):
            await wrapper.wait_for(state="hidden", timeout=2_000)
        return True
    return False


async def wait_for_page_url(page: Page, pattern: str, timeout: int = 30_000) -> None:
    try:
        await page.wait_for_url(pattern, timeout=timeout)
        return
    except PlaywrightTimeout:
        pass
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while asyncio.get_running_loop().time() < deadline:
        if pattern.strip("*") in page.url:
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"等待页面地址超时：当前 {page.url}，期望 {pattern}")


async def find_visible_dialog(page: Page, text_pattern: re.Pattern[str] | None = None) -> Locator | None:
    dialogs = _visible(
        page.locator(
            '#qn-worbench-container .next-dialog, '
            '#qn-worbench-container [role="dialog"]'
        )
    )
    for index in range(await dialogs.count() - 1, -1, -1):
        dialog = dialogs.nth(index)
        try:
            text = await dialog.inner_text(timeout=1_000)
        except PlaywrightError:
            continue
        if text_pattern is None or text_pattern.search(text):
            return dialog
    return None


async def find_visible_button(container: Locator, pattern: re.Pattern[str]) -> Locator | None:
    buttons = _visible(container.locator("button"))
    for index in range(await buttons.count() - 1, -1, -1):
        button = buttons.nth(index)
        try:
            if pattern.search(normalize_text(await button.inner_text(timeout=1_000))):
                return button
        except PlaywrightError:
            continue
    return None


@automation_component("tmall.order.open_page", "天猫订单 · 打开页面", category="report")
async def open_order_page(
    browser: Any,
    username: str,
    password_env: str,
) -> tuple[Page, list[Page]]:
    page = await find_work_page(browser)
    created_pages: list[Page] = []
    log("复用天猫登录模块")
    await ensure_tmall_login(page, username, password_env)

    if ORDER_PAGE_PATH in page.url:
        if await dismiss_intrusive_popup(page):
            log("已关闭直播活动弹窗")
        await page.bring_to_front()
        return page, created_pages

    log("正在打开订单管理")
    await page.goto(SELLER_HOME_URL, wait_until="domcontentloaded")
    await ensure_tmall_login(page, username, password_env)
    transaction = _visible(
        page.locator('a[role="button"], button').filter(has_text=re.compile(r"^\s*交易\s*$"))
    ).last
    await transaction.wait_for(state="visible", timeout=30_000)

    context = page.context
    before = set(context.pages)
    new_page: Page | None = None
    try:
        async with context.expect_page(timeout=12_000) as page_info:
            await click_compat(transaction)
        new_page = await page_info.value
    except PlaywrightTimeout:
        pass

    if new_page is None:
        deadline = asyncio.get_running_loop().time() + 8
        while asyncio.get_running_loop().time() < deadline:
            candidates = [candidate for candidate in context.pages if candidate not in before]
            if candidates:
                new_page = candidates[-1]
                break
            if ORDER_PAGE_PATH in page.url:
                break
            await asyncio.sleep(0.25)

    target = new_page or page
    if new_page is not None:
        created_pages.append(new_page)
        await new_page.wait_for_load_state("domcontentloaded")

    if ORDER_PAGE_PATH not in target.url:
        href = await transaction.get_attribute("href")
        target_url = urljoin(SELLER_HOME_URL, href) if href else ORDER_PAGE_URL
        if "_firstmenuid_" not in target_url and ORDER_PAGE_PATH not in target_url:
            target_url = ORDER_PAGE_URL
        await target.goto(target_url, wait_until="domcontentloaded")
    await wait_for_page_url(target, f"**{ORDER_PAGE_PATH}", timeout=30_000)
    await target.bring_to_front()
    if await dismiss_intrusive_popup(target):
        log("已关闭直播活动弹窗")
    return target, created_pages


async def fill_date_input(input_box: Locator, value: str) -> None:
    # 千牛订单页偶发保留一个高度为 0 的直播入口 overlay；其锚点仍会
    # 拦截真实鼠标事件，但 DOM click 可以触发日期输入控件的 React 事件。
    await click_compat(input_box)
    await input_box.press("Control+A")
    await input_box.fill(value)
    if (await input_box.input_value()).strip() != value:
        await input_box.press("Control+A")
        await input_box.type(value, delay=30)


@automation_component("tmall.order.set_date", "天猫订单 · 设置日期", category="report")
async def set_order_date_range(page: Page, start_date: str, end_date: str) -> None:
    trigger = page.locator(f"xpath={DATE_TRIGGER_XPATH}")
    await trigger.wait_for(state="visible", timeout=30_000)
    if await dismiss_intrusive_popup(page):
        log("已关闭直播活动弹窗")
    await click_compat(trigger)

    date_inputs = _visible(
        page.locator('#qn-worbench-container input[placeholder="YYYY-MM-DD"]')
    )
    try:
        await date_inputs.first.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeout as exc:
        raise RuntimeError("日期弹层未出现 YYYY-MM-DD 输入框") from exc
    count = await date_inputs.count()
    if count < 2:
        raise RuntimeError(f"日期弹层输入框数量不足：{count}")

    start_input = date_inputs.nth(count - 2)
    end_input = date_inputs.nth(count - 1)
    if await dismiss_intrusive_popup(page):
        log("已关闭直播活动弹窗")
    await fill_date_input(start_input, start_date)
    await start_input.press("Tab")
    await end_input.wait_for(state="visible", timeout=5_000)
    if await dismiss_intrusive_popup(page):
        log("已关闭直播活动弹窗")
    await fill_date_input(end_input, end_date)
    await end_input.press("Tab")

    confirm = _visible(
        page.get_by_role("button", name="确定", exact=True)
    ).last
    await confirm.wait_for(state="visible", timeout=5_000)
    if not await confirm.is_enabled():
        values = [await start_input.input_value(), await end_input.input_value()]
        raise RuntimeError(f"日期已输入但确定按钮仍不可用：{values!r}")
    await click_compat(confirm)

    try:
        await start_input.wait_for(state="hidden", timeout=5_000)
    except PlaywrightTimeout:
        # 某些版本只收起弹层、不移除节点；触发器值仍是最终事实。
        pass
    visible_trigger_inputs = await await_visible_locators(trigger.locator("input"))
    selected_values = [(await item.input_value()).strip() for item in visible_trigger_inputs]
    if selected_values and not selected_values[0].startswith(start_date):
        raise RuntimeError(f"开始日期未写入订单筛选框：{selected_values!r}")
    if len(selected_values) > 1 and not selected_values[1].startswith(end_date):
        raise RuntimeError(f"结束日期未写入订单筛选框：{selected_values!r}")
    log(f"已选择近一个月：{start_date} 至 {end_date}")


async def await_visible_locators(locator: Locator) -> list[Locator]:
    result: list[Locator] = []
    for index in range(await locator.count()):
        item = locator.nth(index)
        if await item.is_visible():
            result.append(item)
    return result


async def wait_order_results(page: Page) -> None:
    deadline = asyncio.get_running_loop().time() + 60
    result_re = re.compile(r"共\s*查询到\s*[\d,]+\s*个订单")
    while asyncio.get_running_loop().time() < deadline:
        body_text = ""
        with suppress(PlaywrightError):
            body_text = await page.locator("body").inner_text(timeout=2_000)
        if result_re.search(body_text):
            return
        export_button = _visible(page.locator("#export-orders-btn"))
        if await export_button.count() and await export_button.first.is_enabled():
            # 没有订单时也可能没有“共查询到”文案，但导出按钮已恢复可用。
            return
        await asyncio.sleep(0.5)
    raise RuntimeError("订单列表加载超时，未看到查询结果或批量导出按钮")


@automation_component("tmall.order.search", "天猫订单 · 查询", category="report")
async def search_orders(page: Page, start_date: str, end_date: str) -> None:
    await set_order_date_range(page, start_date, end_date)
    search = _visible(page.locator(f"xpath={SEARCH_BUTTON_XPATH}"))
    if not await search.count():
        search = _visible(page.get_by_role("button", name="搜索订单", exact=True))
    search = search.last
    await search.wait_for(state="visible", timeout=15_000)
    await click_compat(search)
    await wait_order_results(page)
    log("查询完成")


async def open_export_dialog(page: Page) -> Locator:
    button = _visible(page.locator("#export-orders-btn")).last
    await button.wait_for(state="visible", timeout=30_000)
    await click_compat(button)
    dialog = await wait_for_dialog(page, re.compile(r"批量导出订单"), timeout=8_000)
    if dialog is None:
        # 千牛新版按钮偶尔吞掉一次 React click；重新读取同一真实节点并做 DOM fallback。
        await button.evaluate("node => node.click()")
        dialog = await wait_for_dialog(page, re.compile(r"批量导出订单"), timeout=15_000)
    if dialog is None:
        raise RuntimeError("点击批量导出后未出现订单导出弹窗")
    return dialog


async def wait_for_dialog(
    page: Page,
    text_pattern: re.Pattern[str] | None,
    timeout: int,
) -> Locator | None:
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while asyncio.get_running_loop().time() < deadline:
        dialog = await find_visible_dialog(page, text_pattern)
        if dialog is not None:
            return dialog
        await asyncio.sleep(0.25)
    return None


async def select_report_type(dialog: Locator) -> None:
    radios = _visible(dialog.locator("label.next-radio-wrapper"))
    for index in range(await radios.count()):
        radio = radios.nth(index)
        if normalize_text(await radio.inner_text()) != REPORT_TYPE:
            continue
        input_box = radio.locator('input[type="radio"]').first
        if not await input_box.is_checked():
            await click_compat(radio)
            await asyncio.sleep(0.3)
        if not await input_box.is_checked():
            await input_box.check(force=True)
        if not await input_box.is_checked():
            raise RuntimeError(f"无法选中报表类型：{REPORT_TYPE}")
        return
    raise RuntimeError(f"导出弹窗中未找到报表类型：{REPORT_TYPE}")


async def ensure_required_fields(dialog: Locator) -> None:
    labels = _visible(dialog.locator('label.next-checkbox-wrapper'))
    seen: list[str] = []
    for index in range(await labels.count()):
        label = labels.nth(index)
        text = normalize_text(await label.inner_text())
        if not text or text == "全选":
            continue
        seen.append(text)
        input_box = label.locator('input[type="checkbox"]').first
        if not await input_box.count():
            continue
        desired = text in REQUIRED_FIELD_SET
        current = await input_box.is_checked()
        if current == desired:
            continue
        try:
            await click_compat(label)
        except (PlaywrightTimeout, PlaywrightError):
            if desired:
                await input_box.check(force=True)
            else:
                await input_box.uncheck(force=True)

    # 再读一遍真实 checkbox property，避免只依据 CSS checked class。
    checked: set[str] = set()
    for index in range(await labels.count()):
        label = labels.nth(index)
        text = normalize_text(await label.inner_text())
        if text and text != "全选":
            input_box = label.locator('input[type="checkbox"]').first
            if await input_box.count() and await input_box.is_checked():
                checked.add(text)
    if checked != REQUIRED_FIELD_SET:
        missing = [field for field in REQUIRED_FIELDS if field not in checked]
        extra = sorted(checked - REQUIRED_FIELD_SET)
        raise RuntimeError(
            "自定义导出字段校验失败；"
            f"缺少={missing!r}，多选={extra!r}，页面字段={seen!r}"
        )
    log(f"已校验自定义导出字段（{len(REQUIRED_FIELDS)} 个）：{'、'.join(REQUIRED_FIELDS)}")


async def click_attention_confirm(page: Page) -> bool:
    dialog = await wait_for_dialog(page, re.compile(r"请\s*您\s*注意"), timeout=2_000)
    if dialog is None:
        return False
    # 旧版文案为“确定”，当前千牛新版实测为“确认”。
    confirm = await find_visible_button(dialog, re.compile(r"^(确定|确认)$"))
    if confirm is None:
        raise RuntimeError("“请您注意”弹窗中未找到确定按钮")
    await click_compat(confirm)
    with suppress(PlaywrightTimeout):
        await dialog.wait_for(state="hidden", timeout=10_000)
    return True


async def open_export_history(page: Page, trigger: Locator | None = None) -> tuple[Page, list[Page]]:
    context = page.context
    created_pages: list[Page] = []
    before = set(context.pages)

    if trigger is not None:
        try:
            async with context.expect_page(timeout=12_000) as page_info:
                await click_compat(trigger)
            candidate = await page_info.value
            created_pages.append(candidate)
        except PlaywrightTimeout:
            pass

    history: Page | None = None
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline:
        matching = [candidate for candidate in context.pages if EXPORT_LIST_PATH in candidate.url]
        if matching:
            history = matching[-1]
            break
        new_pages = [candidate for candidate in context.pages if candidate not in before]
        if new_pages:
            candidate = new_pages[-1]
            if EXPORT_LIST_PATH not in candidate.url:
                with suppress(PlaywrightError):
                    await candidate.wait_for_load_state("domcontentloaded", timeout=10_000)
            if EXPORT_LIST_PATH in candidate.url:
                history = candidate
                if candidate not in created_pages:
                    created_pages.append(candidate)
                break
        await asyncio.sleep(0.25)

    if history is None:
        history = page
        if EXPORT_LIST_PATH not in history.url:
            await history.goto(EXPORT_LIST_URL, wait_until="domcontentloaded")
    await history.wait_for_load_state("domcontentloaded")
    await history.bring_to_front()
    await wait_for_history_shell(history)
    return history, created_pages


async def wait_for_history_shell(page: Page) -> None:
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        text = ""
        with suppress(PlaywrightError):
            text = await page.locator("body").inner_text(timeout=2_000)
        if "报表申请时间" in text or "订单导出报表" in text:
            return
        await asyncio.sleep(0.5)
    raise RuntimeError(f"订单导出报表页加载超时：{page.url}")


async def visible_history_rows(page: Page) -> list[Locator]:
    rows = _visible(page.locator('div[class*="order-export_order-block"]'))
    if await rows.count():
        return [rows.nth(index) for index in range(await rows.count())]

    # 兼容 class hash 改名：只保留包含申请时间、报表类型且带操作按钮的最小块。
    fallback = _visible(page.locator("#icestarkNode div"))
    result: list[Locator] = []
    for index in range(await fallback.count()):
        row = fallback.nth(index)
        text = normalize_text(await row.inner_text())
        if "报表申请时间" not in text or "报表类型" not in text:
            continue
        if len(text) > 1_000:
            continue
        if await _visible(row.locator("button")).count():
            result.append(row)
    return result


async def history_record(
    row: Locator,
    start_date: str,
    end_date: str,
    submitted_at: dt.datetime | None,
    allow_existing: bool,
) -> tuple[Locator, dt.datetime | None, tuple[str, str] | None, bool] | None:
    text = normalize_text(await row.inner_text())
    if REPORT_TYPE not in text:
        return None
    observed_range = history_range(text)
    range_match = history_range_matches(text, start_date, end_date)
    if not range_match and end_date not in text:
        return None

    applied_match = re.search(r"报表申请时间\s*[:：]\s*([^\s]+(?:\s+[^\s]+)?)", text)
    applied_at = parse_history_datetime(applied_match.group(1)) if applied_match else None
    if not allow_existing and submitted_at is not None and applied_at is not None:
        if applied_at < submitted_at - dt.timedelta(minutes=2):
            return None

    download = _visible(row.get_by_role("button", name=re.compile(r"下载宝贝报表"))).last
    if not await download.count():
        return None
    strict = range_match
    return row, applied_at, observed_range, strict


@automation_component("report.wait_export_ready", "等待导出任务就绪", category="report")
async def wait_for_ready_history_record(
    page: Page,
    start_date: str,
    end_date: str,
    submitted_at: dt.datetime | None,
    allow_existing: bool,
    timeout_seconds: int,
) -> tuple[Locator, dt.datetime | None, tuple[str, str] | None, bool]:
    log("正在等待报表生成")
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_refresh = asyncio.get_running_loop().time()
    warned_fallback = False
    while asyncio.get_running_loop().time() < deadline:
        rows = await visible_history_rows(page)
        fallback_candidates: list[tuple[Locator, dt.datetime | None, tuple[str, str] | None, bool]] = []
        for row in rows:
            candidate = await history_record(
                row, start_date, end_date, submitted_at, allow_existing
            )
            if candidate is not None:
                if candidate[3]:
                    log("报表生成完成")
                    return candidate
                fallback_candidates.append(candidate)

        if fallback_candidates and allow_existing:
            if not warned_fallback:
                log("历史页日期起始日被平台规范化，复用最新宝贝销售明细报表")
                warned_fallback = True
            log("报表生成完成")
            return sorted(
                fallback_candidates,
                key=lambda value: value[1] or dt.datetime.min,
                reverse=True,
            )[0]

        body_text = ""
        with suppress(PlaywrightError):
            body_text = normalize_text(await page.locator("body").inner_text(timeout=2_000))
        if REPORT_TYPE in body_text and re.search(r"(?:生成|导出|下载).*失败", body_text):
            raise RuntimeError("天猫订单报表生成失败，请检查导出历史页中的错误状态")

        now = asyncio.get_running_loop().time()
        if now - last_refresh >= 30:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            await wait_for_history_shell(page)
            last_refresh = now
            log("已刷新订单导出报表页，继续等待")
        await asyncio.sleep(2)
    raise RuntimeError(f"等待“{REPORT_TYPE}”下载按钮超时（{timeout_seconds} 秒）")


@automation_component("file.download", "下载报表文件", category="file")
async def download_history_record(page: Page, row: Locator, work_dir: Path) -> Path:
    log("正在请求下载")
    button = _visible(row.get_by_role("button", name=re.compile(r"下载宝贝报表"))).last
    await button.wait_for(state="visible", timeout=10_000)
    async with page.expect_download(timeout=120_000) as download_info:
        await click_compat(button)
    download = await download_info.value
    filename = download.suggested_filename or "tmall_item_sales_detail.xlsx"
    if not filename.lower().endswith((".xlsx", ".xls")):
        raise RuntimeError(f"天猫订单报表不是 Excel 文件：{filename}")
    target = unique_download_path(work_dir, filename)
    await download.save_as(str(target))
    if not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError(f"天猫订单报表下载文件为空：{target}")
    log("XLSX 下载完成")
    log(f"xlsx_path={target}")
    return target


@automation_component("report.archive", "归档标准报表", category="file")
def archive_report(
    source: Path,
    dest: Path,
    company: str,
    shop: str,
    end_date: str,
) -> Path:
    parse_date(end_date)
    move_log = run_project_module(
        [
            "scripts.auto_download.move_report",
            "--platform",
            PLATFORM,
            "--company",
            company,
            "--shop",
            shop,
            "--report",
            REPORT_NAME,
            "--date",
            end_date,
            "--src",
            str(source.parent),
            "--dest",
            str(dest),
            "--pattern",
            source.name,
            "--within",
            "30",
        ]
    )
    target: Path | None = None
    for line in move_log.splitlines():
        if line.strip().startswith("->"):
            target = Path(line.split("->", 1)[1].strip())
            break
    if target is None or not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError(f"归档工具未返回有效目标文件：{move_log}")
    log("文件移动成功")
    log(f"archive_path={target}")
    return target


def cleanup_success_state(work_dir: Path, state_path: Path, state: dict[str, Any]) -> None:
    """成功后只清理本次脚本生成的状态/临时文件，不触碰用户其他文件。"""
    download_path = state.get("download_path")
    if download_path:
        candidate = Path(str(download_path))
        with suppress(OSError):
            if candidate.is_file() and candidate.parent.resolve() == work_dir.resolve():
                candidate.unlink()
    with suppress(OSError):
        state_path.unlink()
    with suppress(OSError):
        if not any(work_dir.iterdir()):
            work_dir.rmdir()


@automation_component("tmall.order.create_export", "天猫订单 · 创建导出", category="report")
async def create_export_task(
    page: Page,
    state_path: Path,
    state: dict[str, Any],
    start_date: str,
    end_date: str,
) -> tuple[Page, list[Page]]:
    log("正在创建订单导出任务")
    dialog = await open_export_dialog(page)
    await select_report_type(dialog)
    await ensure_required_fields(dialog)

    generate = await find_visible_button(dialog, re.compile(r"生成报表|5\s*分钟内只能导出一次"))
    if generate is None:
        raise RuntimeError("导出弹窗中未找到生成报表按钮")
    generate_text = normalize_text(await generate.inner_text())
    if RATE_LIMIT_RE.search(generate_text):
        log("检测到 5 分钟内只能导出一次，转到已生成报表")
        view = await find_visible_button(dialog, re.compile(r"^查看已生成报表$"))
        if view is None:
            raise RuntimeError("限频弹窗中未找到查看已生成报表按钮")
        update_state(
            state_path,
            state,
            "EXPORT_CREATED",
            creation_mode="rate_limited",
            submitted_at=dt.datetime.now().isoformat(timespec="seconds"),
        )
        history, pages = await open_export_history(page, view)
        return history, pages

    submitted_at = dt.datetime.now()
    update_state(
        state_path,
        state,
        "SUBMITTING",
        submitted_at=submitted_at.isoformat(timespec="seconds"),
        start_date=start_date,
        end_date=end_date,
    )
    await click_compat(generate)

    deadline = asyncio.get_running_loop().time() + 20
    attention_confirmed = False
    rate_limited = False
    while asyncio.get_running_loop().time() < deadline:
        if await click_attention_confirm(page):
            attention_confirmed = True
            break
        current_dialog = await find_visible_dialog(page, re.compile(r"批量导出订单"))
        if current_dialog is not None:
            text = normalize_text(await current_dialog.inner_text())
            if RATE_LIMIT_RE.search(text):
                rate_limited = True
                break
        await asyncio.sleep(0.5)

    if not attention_confirmed and not rate_limited:
        current_dialog = await find_visible_dialog(page, re.compile(r"批量导出订单"))
        if current_dialog is not None:
            raise RuntimeError("点击生成报表后未出现“请您注意”确认弹窗")

    if rate_limited:
        log("检测到 5 分钟内只能导出一次，转到已生成报表")
        current_dialog = await find_visible_dialog(page, re.compile(r"批量导出订单"))
        if current_dialog is None:
            raise RuntimeError("限频后导出弹窗已消失，无法打开已生成报表")
        view = await find_visible_button(current_dialog, re.compile(r"^查看已生成报表$"))
        if view is None:
            raise RuntimeError("限频弹窗中未找到查看已生成报表按钮")
        history, pages = await open_export_history(page, view)
        update_state(state_path, state, "EXPORT_CREATED", creation_mode="rate_limited")
        return history, pages

    log("导出任务创建成功")
    update_state(
        state_path,
        state,
        "EXPORT_CREATED",
        creation_mode="new",
        creation_confirmed=attention_confirmed,
    )
    history, pages = await open_export_history(page)
    return history, pages


@automation_component("tmall.order.workflow", "天猫订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    profile: str,
    company: str,
    shop: str,
    start_date: str,
    end_date: str,
    work_dir: Path,
    dest: Path,
    username: str,
    password_env: str,
    history_timeout: int,
) -> int:
    request = state_request(start_date, end_date, company, shop)
    state_path = work_dir / STATE_FILENAME
    state = read_state(state_path)
    if state is None or state.get("request") != request or state.get("stage") == "COMPLETED":
        state = new_state(request)
        write_state(state_path, state)

    log(f"profile={profile}")
    log(f"date_range={start_date}..{end_date}")
    work_dir.mkdir(parents=True, exist_ok=True)

    if state.get("stage") == "DOWNLOADED":
        download_path = Path(str(state.get("download_path", "")))
        if not download_path.exists():
            raise RuntimeError(f"状态显示已下载，但临时文件不存在：{download_path}")
        archive_report(download_path, dest, company, shop, end_date)
        update_state(state_path, state, "COMPLETED")
        cleanup_success_state(work_dir, state_path, state)
        log("任务完成")
        return 0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        created_pages: list[Page] = []
        try:
            stage = state.get("stage")
            if stage == "SUBMITTING":
                log("发现未完成的导出状态，先核对导出历史，避免重复创建")
                history, pages = await open_export_history(await find_work_page(browser))
                created_pages.extend(pages)
                submitted_at = parse_history_datetime(str(state.get("submitted_at", "")))
                record = await wait_for_ready_history_record(
                    history,
                    start_date,
                    end_date,
                    submitted_at,
                    False,
                    history_timeout,
                )
                update_state(state_path, state, "EXPORT_CREATED", creation_mode="recovered")
            elif stage == "EXPORT_CREATED":
                history, pages = await open_export_history(await find_work_page(browser))
                created_pages.extend(pages)
                submitted_at = parse_history_datetime(str(state.get("submitted_at", "")))
                record = await wait_for_ready_history_record(
                    history,
                    start_date,
                    end_date,
                    submitted_at,
                    state.get("creation_mode") == "rate_limited",
                    history_timeout,
                )
            else:
                order_page, pages = await open_order_page(browser, username, password_env)
                created_pages.extend(pages)
                await search_orders(order_page, start_date, end_date)
                history, pages = await create_export_task(
                    order_page, state_path, state, start_date, end_date
                )
                created_pages.extend(pages)
                submitted_at = parse_history_datetime(str(state.get("submitted_at", "")))
                record = await wait_for_ready_history_record(
                    history,
                    start_date,
                    end_date,
                    submitted_at,
                    state.get("creation_mode") == "rate_limited",
                    history_timeout,
                )

            row, applied_at, observed_range, strict = record
            if applied_at is not None:
                log(f"history_apply_time={applied_at.isoformat(sep=' ')}")
            if observed_range is not None and not strict:
                log(f"history_date_range={observed_range[0]}..{observed_range[1]}")
            downloaded = await download_history_record(history, row, work_dir)
            update_state(
                state_path,
                state,
                "DOWNLOADED",
                download_path=str(downloaded),
                history_apply_time=applied_at.isoformat() if applied_at else None,
            )
        finally:
            for created in reversed(created_pages):
                with suppress(PlaywrightError):
                    await created.close()

    download_path = Path(str(state.get("download_path", "")))
    if not download_path.exists():
        raise RuntimeError(f"下载阶段未留下临时 XLSX：{download_path}")
    archive_report(download_path, dest, company, shop, end_date)
    update_state(state_path, state, "COMPLETED")
    cleanup_success_state(work_dir, state_path, state)
    log("任务完成")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫宝贝销售明细订单报表下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login profile 返回的 wsEndpoint")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="profile 名称，仅用于日志")
    parser.add_argument("--platform", default=PLATFORM, help="兼容参数，固定为天猫")
    parser.add_argument("--company", required=True, help="profile note 中的公司全称")
    parser.add_argument("--shop", required=True, help="profile note 中的店铺名")
    parser.add_argument("--start-date", default=None, help="开始日期 YYYY-MM-DD，默认今天往前 30 天")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD，默认今天")
    parser.add_argument(
        "--work-dir", "--src", dest="work_dir", default=None,
        help="下载和失败恢复状态目录；默认归档根目录下的 .automation_cache",
    )
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="归档根目录")
    parser.add_argument("--username", default=DEFAULT_USERNAME, help="复用天猫 IT 登录账号")
    parser.add_argument(
        "--password-env", default=DEFAULT_PASSWORD_ENV or DEFAULT_FINANCE_PASSWORD_ENV,
        help="登录密码环境变量名",
    )
    parser.add_argument(
        "--history-timeout", type=int, default=900,
        help="订单导出历史页等待报表生成的最长秒数",
    )
    args = parser.parse_args()

    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if args.platform != PLATFORM:
        print(f"--platform 只支持 {PLATFORM}", file=sys.stderr)
        return 2
    try:
        start_date, end_date = resolve_date_range(args.start_date, args.end_date)
        dest = Path(args.dest)
        work_dir = Path(args.work_dir) if args.work_dir else default_work_dir(dest, args.shop)
        return asyncio.run(
            run(
                args.cdp,
                args.profile,
                args.company,
                args.shop,
                start_date,
                end_date,
                work_dir,
                dest,
                args.username,
                args.password_env,
                max(1, args.history_timeout),
            )
        )
    except Exception as exc:
        print(f"[TMALL] 执行失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
