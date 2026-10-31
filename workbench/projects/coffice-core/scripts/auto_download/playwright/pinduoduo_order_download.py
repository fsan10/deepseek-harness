# -*- coding: utf-8 -*-
"""下载拼多多近30日订单对账报表并按项目标准归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from .pinduoduo_login import ensure_pinduoduo_login

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Download, Page


ORDERS_URL = "https://mms.pinduoduo.com/orders/list?tab=0"
EXPORT_URL = "https://mms.pinduoduo.com/orders/exportExcel?exportType=0"
ORDER_REPORT_API_FRAGMENT = "/mangkhut/mms/recentOrderList"
REPORT_NAME = "订单"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ORDER_TIME_QUICK_RANGE = "近30日"
DISPLAYED_RANGE_RE = re.compile(
    r"(?P<start>20\d{2}-\d{1,2}-\d{1,2})\s+\d{1,2}:\d{2}:\d{2}\s*~\s*"
    r"(?P<end>20\d{2}-\d{1,2}-\d{1,2})\s+\d{1,2}:\d{2}:\d{2}"
)


async def click_compat(locator) -> None:
    """处理拼多多首页消息浮层拦截指针事件的情况。"""

    try:
        await locator.click(timeout=5_000)
    except Exception:
        await locator.evaluate("element => element.click()")


async def single_control_click(locator) -> None:
    """对日期弹层控件只触发一次 DOM click，避开页面的外部点击误判。"""

    await locator.evaluate(
        """element => {
            if (typeof element.click === 'function') {
                element.click();
                return;
            }
            element.dispatchEvent(new MouseEvent('click', {
                bubbles: true, cancelable: true, view: window
            }));
        }"""
    )


async def close_important_popup(page: "Page") -> bool:
    """关闭拼多多页面上会遮挡导出按钮的「重要提示」浮层。

    该浮层是 portal 节点，类名带构建哈希；优先使用当前版本的完整类名，
    再用稳定的类名前缀兜底。返回值表示本次是否实际关闭了至少一个浮层。
    """

    closed = False
    selectors = (
        "i.ImportantList_close__d0eKb",
        'i[class*="ImportantList_close"]',
    )
    for selector in selectors:
        locators = page.locator(selector)
        for index in range(await locators.count()):
            candidate = locators.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                await click_compat(candidate)
                closed = True
                await asyncio.sleep(0.2)
            except Exception:
                # 浮层可能在循环期间自行消失；不要让它阻断账单下载。
                continue
    return closed


def default_business_date() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def expected_range(start_date: str, end_date: str | None = None) -> str:
    end_date = end_date or start_date
    return f"{start_date} 00:00:00 ~ {end_date} 23:59:59"


def parse_displayed_range(value: str) -> tuple[str, str]:
    """从快捷日期控件的只读值中提取实际起止日期。"""

    match = DISPLAYED_RANGE_RE.search(value or "")
    if match is None:
        raise RuntimeError(f"拼多多订单日期控件值无法解析：{value!r}")
    start = date.fromisoformat(match.group("start")).isoformat()
    end = date.fromisoformat(match.group("end")).isoformat()
    if start > end:
        raise RuntimeError(f"拼多多订单日期控件起止日期异常：{value!r}")
    return start, end


def resolve_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    if start_date is None and end_date is None:
        business_date = default_business_date()
        return business_date, business_date
    if not start_date or not end_date:
        raise ValueError("--start-date 与 --end-date 必须同时提供")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("--start-date 不能晚于 --end-date")
    return start.isoformat(), end.isoformat()


@automation_component("pinduoduo.order.open", "拼多多订单 · 打开页面", category="report")
async def open_order_page(
    context: "BrowserContext", *, platform: str, company: str, shop: str
) -> tuple["Page", bool]:
    """复用当前拼多多页面，避免日期调试时反复创建新 tab。"""

    existing_pages = set(context.pages)
    page = await ensure_pinduoduo_login(
        context, platform=platform, company=company, shop=shop
    )
    created = page not in existing_pages
    await page.bring_to_front()
    if "/orders/list" not in page.url:
        await page.goto(ORDERS_URL, wait_until="domcontentloaded", timeout=60_000)
    if "/login" in page.url:
        raise RuntimeError("拼多多订单页登录会话异常，登录后仍被重定向到登录页")
    await page.get_by_text("订单查询", exact=True).last.wait_for(
        state="visible", timeout=60_000
    )
    await close_important_popup(page)
    return page, created


@automation_component("pinduoduo.order.set_date", "拼多多订单 · 设置近30日", category="report")
async def choose_recent_30_days(page: "Page") -> tuple[str, str]:
    """默认使用“订单下单时间”左侧快捷下拉框的近30日。"""

    label = page.locator(
        'div[data-testid="beast-core-grid-col-wrapper"][label="订单下单时间"]'
    ).first
    await label.wait_for(state="visible", timeout=60_000)
    row = label.locator("xpath=..")
    await close_important_popup(page)
    selector = row.locator(
        'div[data-testid="beast-core-select"] '
        'input[data-testid="beast-core-select-htmlInput"]'
    ).first
    option = page.get_by_role("option", name=ORDER_TIME_QUICK_RANGE, exact=True).filter(
        visible=True
    )
    # 用户可能已经打开快捷列表；此时直接选项，避免再次点击输入框把列表收起。
    if not await option.count():
        await click_compat(selector)
        option = page.get_by_role("option", name=ORDER_TIME_QUICK_RANGE, exact=True).filter(
            visible=True
        )
    await option.last.wait_for(state="visible", timeout=15_000)
    await click_compat(option.last)
    date_input = row.locator(
        'input[data-testid="beast-core-rangePicker-htmlInput"]'
    ).first
    deadline = asyncio.get_running_loop().time() + 15
    actual = ""
    while asyncio.get_running_loop().time() < deadline:
        if await selector.input_value() != ORDER_TIME_QUICK_RANGE:
            await asyncio.sleep(0.2)
            continue
        actual = await date_input.input_value()
        if actual:
            return parse_displayed_range(actual)
        await asyncio.sleep(0.2)
    raise RuntimeError(
        f"拼多多订单快捷日期选择失败：期望 {ORDER_TIME_QUICK_RANGE!r}，"
        f"快捷值={await selector.input_value()!r}，日期值={actual!r}"
    )


async def _click_exact_visible(locator, text: str) -> None:
    for _ in range(8):
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            try:
                if (await candidate.inner_text()).strip() != text:
                    continue
                await candidate.scroll_into_view_if_needed(timeout=2_000)
                await candidate.click(force=True, timeout=5_000)
                return
            except Exception:
                # 时间列表每次选择后会重绘，重新解析 locator 再点击。
                continue
        await asyncio.sleep(0.15)
    try:
        observed = await locator.all_inner_texts()
    except Exception:
        observed = []
    raise RuntimeError(
        f"拼多多日期控件中未找到可点击选项：{text}（候选数量={len(observed)}）"
    )


async def _select_calendar_day(page: "Page", table_index: int, day: int) -> None:
    clicked = await page.evaluate(
        """({tableIndex, day}) => {
            const isVisible = element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0;
            };
            const roots = [...document.querySelectorAll(
                '[data-testid="beast-core-rangePicker-dropdown-contentRoot"]'
            )].filter(isVisible);
            const root = roots.at(-1);
            const table = root?.querySelectorAll(
                '[data-testid="beast-core-rangePicker-table"]'
            )[tableIndex];
            if (!table) return false;
            const cell = [...table.querySelectorAll('[role="date-cell"]')].find(element => {
                const classes = element.getAttribute('class') || '';
                return element.textContent.trim() === day
                    && !classes.includes('outOfMonth')
                    && !classes.includes('disabled');
            });
            if (!cell) return false;
            cell.click();
            return true;
        }""",
        {"tableIndex": table_index, "day": str(day)},
    )
    if not clicked:
        raise RuntimeError(f"拼多多日期控件中未找到日期：{day}")
    await asyncio.sleep(0.5)


async def _visible_range_root(page: "Page", *, timeout: float = 0):
    roots = page.locator(
        '[data-testid="beast-core-rangePicker-dropdown-contentRoot"]:visible'
    )
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if await roots.count():
            return roots.last
        if timeout <= 0 or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.1)
    raise RuntimeError("拼多多订单日期弹层未打开")


async def _visible_left_month(page: "Page") -> tuple[int, int] | None:
    """读取日历左面板月份，不依赖构建哈希 class 或 body 绝对 XPath。"""

    visible = await page.evaluate(
        """() => {
            const isVisible = element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0;
            };
            const roots = [...document.querySelectorAll(
                '[data-testid="beast-core-rangePicker-dropdown-contentRoot"]'
            )].filter(isVisible);
            const root = roots.at(-1);
            if (!root) return null;
            const labels = [...root.querySelectorAll('span')]
                .map(element => element.textContent.trim())
                .filter(text => /^(?:[1-9]|1[0-2])月$/.test(text))
                .slice(0, 2);
            const year = root.querySelector(
                '[data-testid="beast-core-rangePicker-select-0"] ' +
                'input[data-testid="beast-core-select-htmlInput"]'
            )?.value || '';
            return {year, labels};
        }"""
    )
    if not visible or not visible["labels"]:
        return None
    try:
        return int(visible["year"].rstrip("年")), int(visible["labels"][0][:-1])
    except ValueError:
        return None


async def _click_month_switcher(page: "Page", *, forward: bool) -> None:
    """按弹层内的 data-testid 点击一次月份切换控件。"""

    testid = "beast-core-icon-right" if forward else "beast-core-icon-left"
    clicked = await page.evaluate(
        """testid => {
            const isVisible = element => {
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden'
                    && rect.width > 0 && rect.height > 0;
            };
            const roots = [...document.querySelectorAll(
                '[data-testid="beast-core-rangePicker-dropdown-contentRoot"]'
            )].filter(isVisible);
            const root = roots.at(-1);
            const switcher = root?.querySelector('[data-testid="' + testid + '"]');
            if (!switcher) return false;
            switcher.dispatchEvent(new MouseEvent('click', {
                bubbles: true, cancelable: true, view: window
            }));
            return true;
        }""",
        testid,
    )
    if not clicked:
        raise RuntimeError("拼多多订单日历缺少月份切换按钮")


async def _open_range_picker(
    page: "Page", picker, *, existing_timeout: float = 0
):
    try:
        return await _visible_range_root(page, timeout=existing_timeout)
    except RuntimeError:
        pass
    # 页面有 document-level outside-click 处理器；Playwright 鼠标点击会在
    # 弹层刚创建后又把它收起。顶层输入也只触发一次 DOM click，避免重复事件。
    await single_control_click(picker)
    try:
        return await _visible_range_root(page, timeout=10)
    except RuntimeError as exc:
        state = await page.evaluate(
            """() => ({
                url: location.href,
                pickerCount: document.querySelectorAll('input[data-testid="beast-core-rangePicker-htmlInput"]').length,
                roots: [...document.querySelectorAll('[data-testid="beast-core-rangePicker-dropdown-contentRoot"]')].map(element => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return {display: style.display, visibility: style.visibility, width: rect.width, height: rect.height};
                })
            })"""
        )
        raise RuntimeError(f"{exc}；点击后 DOM 状态：{state}") from exc


async def _time_input(page: "Page", input_testid: str):
    """从当前可见日期 portal 内按稳定 testid 解析时间输入。"""

    root = await _visible_range_root(page, timeout=2)
    primary = root.locator(f'input[data-testid="{input_testid}"]').last
    if await primary.count():
        await primary.wait_for(state="visible", timeout=10_000)
        return primary

    # 结算中心的同一组件版本把开始/结束输入都标成同一个 testid；
    # 用弹层内的 DOM 顺序区分，不依赖 body 绝对 XPath。
    generic = root.locator(
        'input[data-testid="beast-core-timePicker-html-input"]'
    )
    index = 1 if input_testid.endswith("-end") else 0
    if await generic.count() > index:
        candidate = generic.nth(index)
        await candidate.wait_for(state="visible", timeout=10_000)
        return candidate
    raise RuntimeError(
        f"拼多多订单日期弹层缺少时间输入：{input_testid}"
    )


async def _visible_time_picker_portal(page: "Page"):
    """返回最新的时间选择 portal；开始/结束输入各自会创建同名列表。"""

    portals = page.locator('[data-testid="beast-core-portal"]')
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        for index in range(await portals.count() - 1, -1, -1):
            candidate = portals.nth(index)
            lists = candidate.locator(
                '[data-testid^="beast-core-timePicker-list-"]'
            )
            if await lists.count() and await lists.first.is_visible():
                return candidate
        await asyncio.sleep(0.1)
    raise RuntimeError("拼多多时间选择器 portal 未打开")


async def _select_time(
    page: "Page", input_testid: str, hour: str, minute: str, second: str
) -> None:
    time_input = await _time_input(page, input_testid)
    expected = f"{hour}:{minute}:{second}"
    if await time_input.input_value() == expected:
        return
    # 该页面的 document-level pointerdown 会把鼠标点击误判为弹层外点击；
    # 触发 input 的 DOM click 只执行一次，可保留日期弹层并打开时间 portal。
    await single_control_click(time_input)
    await _visible_time_picker_portal(page)
    await page.evaluate(
        """async ({values}) => {
            const sleep = (milliseconds) => new Promise(resolve => setTimeout(resolve, milliseconds));
            for (const [part, value] of [['hh', values[0]], ['mm', values[1]], ['ss', values[2]]]) {
                let item = null;
                for (let attempt = 0; attempt < 30 && !item; attempt += 1) {
                    const portals = [...document.querySelectorAll('[data-testid="beast-core-portal"]')]
                        .filter(element => element.querySelector('[data-testid="beast-core-timePicker-list-hh"]'));
                    const portal = portals.at(-1);
                    const list = portal?.querySelector(
                        '[data-testid="beast-core-timePicker-list-' + part + '"]'
                    );
                    if (list) {
                        item = [...list.querySelectorAll('li')].find(element => element.textContent.trim() === value);
                    }
                    if (!item) await sleep(100);
                }
                if (!item) {
                    const state = [...document.querySelectorAll('[data-testid="beast-core-portal"]')]
                        .map((element, index) => ({
                            index,
                            hasTime: !!element.querySelector('[data-testid="beast-core-timePicker-list-hh"]'),
                            lists: [...element.querySelectorAll('[data-testid^="beast-core-timePicker-list-"]')]
                                .map(list => ({id: list.getAttribute('data-testid'), values: [...list.querySelectorAll('li')].slice(0, 3).map(li => li.textContent.trim())}))
                        }));
                    throw new Error(`时间列表缺少选项：${part}=${value}，portal=${JSON.stringify(state)}`);
                }
                item.scrollIntoView({block: 'center'});
                item.click();
                await sleep(300);
            }
        }""",
        {"values": [hour, minute, second]},
    )
    actual = await time_input.input_value()
    if actual != expected:
        raise RuntimeError(
            f"拼多多订单时间设置失败：期望 {expected!r}，实际 {actual!r}"
        )


@automation_component("pinduoduo.order.set_date", "拼多多订单 · 设置日期范围", category="report")
async def choose_date_range(page: "Page", start_date: str, end_date: str) -> None:
    label = page.locator(
        'div[data-testid="beast-core-grid-col-wrapper"][label="订单下单时间"]'
    ).first
    await label.wait_for(state="visible", timeout=60_000)
    row = label.locator("xpath=..")
    await close_important_popup(page)
    picker = row.locator(
        'input[data-testid="beast-core-rangePicker-htmlInput"]'
    ).first
    await _open_range_picker(page, picker)

    target = date.fromisoformat(start_date)
    for _ in range(24):
        visible = await _visible_left_month(page)
        if visible and visible[0] == target.year and visible[1] == target.month:
            break
        if visible is None:
            await asyncio.sleep(0.15)
            continue
        current = date(visible[0], visible[1], 1)
        desired = date(target.year, target.month, 1)
        await _click_month_switcher(page, forward=current < desired)
        await asyncio.sleep(0.3)
    else:
        raise RuntimeError(f"拼多多订单日历未定位到目标月份：{start_date}")

    await _select_calendar_day(page, 0, target.day)
    await _open_range_picker(page, picker, existing_timeout=2)
    await _select_calendar_day(page, 0, date.fromisoformat(end_date).day)
    # 结束日期提交后组件可能异步重绘并收起弹层；只有确认不可见时才打开一次。
    await _open_range_picker(page, picker, existing_timeout=2)
    await _select_time(
        page,
        "beast-core-rangePicker-timePicker-htmlInput-begin",
        "00",
        "00",
        "00",
    )
    await _select_time(
        page,
        "beast-core-rangePicker-timePicker-htmlInput-end",
        "23",
        "59",
        "59",
    )
    confirm = page.get_by_role("button", name="确认", exact=True).filter(visible=True).last
    await single_control_click(confirm)
    expected = expected_range(start_date, end_date)
    deadline = asyncio.get_running_loop().time() + 15
    actual = ""
    while asyncio.get_running_loop().time() < deadline:
        actual = await picker.input_value()
        if actual == expected:
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"拼多多订单日期选择失败：期望 {expected!r}，实际 {actual!r}")


@automation_component("pinduoduo.order.query", "拼多多订单 · 查询", category="report")
async def query_orders(page: "Page") -> None:
    query = page.get_by_role("button", name="查询", exact=True).filter(visible=True)
    try:
        async with page.expect_response(
            lambda response: ORDER_REPORT_API_FRAGMENT in response.url
            and response.status == 200,
            timeout=120_000,
        ):
            await click_compat(query)
    except Exception as exc:
        raise TimeoutError("等待拼多多订单查询接口返回 200 超时") from exc


@automation_component("pinduoduo.order.create_export", "拼多多订单 · 创建导出", category="report")
async def create_export(page: "Page") -> "Page":
    await close_important_popup(page)
    batch_export = page.get_by_role("button", name="批量导出", exact=True).filter(
        visible=True
    )
    await batch_export.scroll_into_view_if_needed()
    await click_compat(batch_export)
    report_option = page.locator("label").filter(has_text="对账报表").filter(
        visible=True
    ).last
    await report_option.wait_for(state="visible", timeout=15_000)
    if "RDG_active" not in (await report_option.get_attribute("class") or ""):
        await report_option.scroll_into_view_if_needed()
        await click_compat(report_option)
    generate = page.get_by_role("button", name="生成报表", exact=True).filter(
        visible=True
    )
    await generate.scroll_into_view_if_needed()
    known_pages = set(page.context.pages)
    try:
        await generate.click(force=True, timeout=5_000)
    except Exception:
        # 弹窗由 fixed portal 渲染时，Chromium 可能仍将按钮报告为 viewport 外；
        # 继续调用同一 DOM 按钮的 click 事件，不绕过页面业务逻辑。
        await generate.evaluate("element => element.click()")
    await close_important_popup(page)
    # 正常提交会在当前页路由到导出记录；若平台提示“五分钟内只能生成一次”
    # 或“重复提交任务”，也直接进入导出记录复用已有任务，不再次生成。
    deadline = asyncio.get_running_loop().time() + 12
    while asyncio.get_running_loop().time() < deadline:
        if "/orders/exportExcel" in page.url:
            await close_important_popup(page)
            return page
        for candidate in page.context.pages:
            if candidate in known_pages or candidate.is_closed():
                continue
            if "/orders/exportExcel" in candidate.url:
                await candidate.wait_for_load_state("domcontentloaded", timeout=30_000)
                await close_important_popup(candidate)
                await page.close()
                return candidate
        await asyncio.sleep(0.25)
    # 当前版本通常自动路由；这是对平台未自动切换页面时的安全兜底。
    await page.goto(EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    await close_important_popup(page)
    return page


@automation_component("pinduoduo.order.wait_ready", "拼多多订单 · 等待导出就绪", category="report")
async def newest_download_button(page: "Page", start_date: str, end_date: str):
    def matches_date_range(text: str) -> bool:
        # 自定义日期通常显示 00:00/23:59，快捷项会显示实际选择时分；
        # 只要同一任务卡同时包含已核对的起止日期即可，避免绑定页面时间格式。
        return start_date in text and end_date in text

    deadline = asyncio.get_running_loop().time() + 120
    while asyncio.get_running_loop().time() < deadline:
        await close_important_popup(page)
        cards = page.locator("div.download-box").filter(has_text="生成报表时间：")
        # 页面将最新任务排在第一行；先核对任务卡的拼单成功日期，再下载。
        for index in range(min(await cards.count(), 20)):
            row = cards.nth(index)
            try:
                text = await row.inner_text(timeout=1_000)
            except Exception:
                continue
            if matches_date_range(text):
                button = row.locator("button").filter(has_text="下载报表").first
                if await button.count() and await button.is_visible():
                    await close_important_popup(page)
                    return button
        # 部分版本任务卡类名会变化；只有在按钮的任务祖先仍明确包含目标日期时才兜底，
        # 绝不因为“第一个按钮”而下载其他日期的报表。
        if await cards.count() == 0:
            buttons = page.locator("button").filter(has_text="下载报表")
            for index in range(await buttons.count()):
                button = buttons.nth(index)
                if not await button.is_visible():
                    continue
                try:
                    ancestor = button.locator(
                        "xpath=ancestor::*[contains(., '拼单成功时间')][1]"
                    )
                    if matches_date_range(await ancestor.inner_text(timeout=1_000)):
                        await close_important_popup(page)
                        return button
                except Exception:
                    continue
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            # React 路由切换期间 reload 可能收到 ERR_ABORTED/frame detached；
            # 回到固定导出记录地址继续轮询即可。
            await page.goto(EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
        await close_important_popup(page)
    cards_count = await page.locator("div.download-box").count()
    buttons_count = await page.locator("button").filter(has_text="下载报表").count()
    raise TimeoutError(
        f"拼多多订单导出记录未生成：{start_date} 至 {end_date}"
        f"（任务卡{cards_count}，下载按钮{buttons_count}）"
    )


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download: "Download", directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = download.suggested_filename or "pinduoduo_order.xlsx"
    target = directory / filename
    if target.exists():
        stem, suffix = target.stem, target.suffix
        for sequence in range(2, 1000):
            target = directory / f"{stem}_{sequence:03d}{suffix}"
            if not target.exists():
                break
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"拼多多订单下载文件为空：{target}")
    return target


@automation_component("report.archive", "归档标准报表", category="file")
def move_report(
    source: Path,
    *,
    platform: str,
    company: str,
    shop: str,
    business_date: str,
    dest: Path,
) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
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
            "10",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


@automation_component("pinduoduo.order.workflow", "拼多多订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path | None,
    dest: Path,
    start_date: str | None = None,
    end_date: str | None = None,
    date_only: bool = False,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="pdd_order_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    use_quick_range = start_date is None and end_date is None
    if not use_quick_range:
        start_date, end_date = resolve_date_range(start_date, end_date)
    page = None
    created = False
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            context = browser.contexts[0]
            page, created = await open_order_page(
                context, platform=platform, company=company, shop=shop
            )
            if use_quick_range:
                start_date, end_date = await choose_recent_30_days(page)
                print(
                    f"默认日期快捷选择成功：{ORDER_TIME_QUICK_RANGE}，"
                    f"实际范围 {start_date}  ~  {end_date}"
                )
            else:
                await choose_date_range(page, start_date, end_date)
            if date_only:
                if use_quick_range:
                    print(
                        f"日期设置校验成功：快捷{ORDER_TIME_QUICK_RANGE}，"
                        f"实际日期 {start_date} ~ {end_date}"
                    )
                else:
                    print(
                        f"日期设置校验成功：{start_date} 00:00:00 ~ {end_date} 23:59:59"
                    )
                if created and not page.is_closed():
                    await page.close()
                page = None
                return 0
            await query_orders(page)
            page = await create_export(page)
            button = await newest_download_button(page, start_date, end_date)
            async with page.expect_download(timeout=120_000) as download_info:
                await close_important_popup(page)
                await click_compat(button)
            downloaded = await save_download(await download_info.value, actual_work_dir)
            print(f"已下载拼多多订单临时文件：{downloaded}")
            move_log = await asyncio.to_thread(
                move_report,
                downloaded,
                platform=platform,
                company=company,
                shop=shop,
                business_date=end_date,
                dest=dest,
            )
            print(move_log)
            if created and not page.is_closed():
                await page.close()
            page = None
    finally:
        if page is not None and created:
            try:
                await page.close()
            except Exception:
                pass
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="拼多多订单报表下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    parser.add_argument("--start-date", default=None, help="订单下单时间起始日期，YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="订单下单时间结束日期，YYYY-MM-DD")
    parser.add_argument("--date-only", action="store_true", help="只设置并校验日期，不创建导出任务")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            run(
                args.cdp,
                args.platform,
                args.company,
                args.shop,
                Path(args.work_dir) if args.work_dir else None,
                Path(args.dest),
                args.start_date,
                args.end_date,
                args.date_only,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
