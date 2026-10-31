# -*- coding: utf-8 -*-
"""下载小红书近 30 天订单标准报表并归档。

小红书订单页的导出是当前页面直接下载 XLSX，不经过订单导出历史页。脚本
通过 CDP 连接 Cloak Login 已启动的 profile，按页面真实业务顺序完成导航、
日期快捷筛选、查询、全部导出、提示确认、XLSX 校验和归档。
"""

from __future__ import annotations

from scripts.auto_download.move_report import archive_report

import argparse
import asyncio
import re
import sys
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from etl.xhs.load_xhs_order_ods import EXPECTED_COLUMNS

from .component_runtime import automation_component
from .report_validation import validate_report_columns, warn_unread_sheets
from .xiaohongshu_download_common import (
    ARK_HOST,
    LOGIN_HOST,
    XHS_HOME_URL,
    click_compat,
    dismiss_ad_popups,
    ensure_logged_in,
    is_login_page,
    read_header,
    save_download,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Download, Locator, Page


PLATFORM = "小红书"
REPORT_NAME = "订单"
DEFAULT_PROFILE = "XHS-小红书-MOCK旗舰店"
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")

# 这些 XPath 来自当前小红书订单页；所有绝对层级定位均配有可见文本备用。
ORDER_MENU_XPATH = "xpath=//*[@id=\"root-menu-wrapper\"]/div[3]/div[6]/div[2]/div[1]/span"
ORDER_ROOT_XPATH = "xpath=//*[@id=\"fulfillmentorderark-mount-container\"]"
DATE_FILTER_XPATH = (
    "xpath=//*[@id=\"fulfillmentorderark-mount-container\"]/div[2]/div/div[2]/div[2]/div/div[7]/div/div"
)
DATE_START_XPATH = (
    "xpath=//*[@id=\"fulfillmentorderark-mount-container\"]/div[2]/div/div[2]/div[2]/div/div[7]/div/div/div[2]/div[1]/input"
)
DATE_END_XPATH = (
    "xpath=//*[@id=\"fulfillmentorderark-mount-container\"]/div[2]/div/div[2]/div[2]/div/div[7]/div/div/div[2]/div[2]/input"
)
DATE_POPUP_XPATH = "xpath=/html/body/div[38]"
DATE_PRESET_XPATH = "xpath=/html/body/div[38]/div[3]/div/button[5]/div/span"
QUERY_BUTTON_XPATH = (
    "xpath=//*[@id=\"fulfillmentorderark-mount-container\"]/div[2]/div/div[2]/div[2]/div/div[8]/button[3]"
)
EXPORT_BUTTON_XPATH = "xpath=//*[@id=\"new_order_manage_step_second\"]/div[1]/button[3]"
NOTICE_XPATH = "xpath=/html/body/div[16]/div"
NOTICE_CONFIRM_XPATH = "xpath=/html/body/div[16]/div/div[3]/div/button[2]"

_DATE_PRESET_RE = re.compile(r"^\s*近\s*30\s*天\s*$")
_NOTICE_TEXT_RE = re.compile(r"确定|导出|提示|订单")
_CALENDAR_MONTH_RE = re.compile(r"(20\d{2})\s*[年/.\-]\s*(\d{1,2})\s*月?")
_CALENDAR_PREV_RE = re.compile(r"上一|上个|前一|上月|prev|previous|left|向左", re.I)
_CALENDAR_NEXT_RE = re.compile(r"下一|下个|后一|下月|next|right|向右", re.I)

XHS_ORDER_HEADERS = tuple(str(column).strip() for column in EXPECTED_COLUMNS)


def log(message: str) -> None:
    """输出可实时观察的阶段日志，便于脚本等待页面或下载时诊断。"""
    print(message, flush=True)


def _visible(locator: "Locator") -> "Locator":
    return locator.filter(visible=True)


async def _first_visible(locators: list["Locator"]):
    for locator in locators:
        with suppress(Exception):
            count = await locator.count()
            for index in range(count):
                candidate = locator.nth(index)
                if await candidate.is_visible():
                    return candidate
    return None


async def _wait_first(
    page: "Page", locators: list["Locator"], label: str, timeout: float = 30_000
):
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while asyncio.get_running_loop().time() < deadline:
        candidate = await _first_visible(locators)
        if candidate is not None:
            return candidate
        await asyncio.sleep(0.2)
    raise RuntimeError(f"小红书{label}未出现，当前页面：{page.url}")


async def _body_excerpt(page: "Page") -> str:
    with suppress(Exception):
        return (await page.locator("body").inner_text(timeout=3_000)).strip()[:500]
    return ""


async def _log_closed_popups(page: "Page") -> None:
    count = await dismiss_ad_popups(page)
    if count:
        log(f"[XHS] 已关闭广告弹窗：{count}个")


def _parse_iso_date(value: str, option: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{option} 必须使用 YYYY-MM-DD 格式：{value!r}") from exc


def _normalized_date_tokens(value: str) -> set[str]:
    compact = re.sub(r"\D", "", value or "")
    tokens = {value, value.replace("-", "/"), value.replace("-", ".")}
    if len(compact) >= 8:
        tokens.add(compact[:8])
    return {token for token in tokens if token}


def _date_value_contains(value: str, expected: str) -> bool:
    return any(token in (value or "") for token in _normalized_date_tokens(expected))


@automation_component("xhs.order.open_home", "小红书 · 打开工作台", category="report")
async def open_home_page(context: "BrowserContext", profile: str) -> "Page":
    page = next(
        (
            candidate
            for candidate in context.pages
            if not candidate.is_closed() and url_host(candidate.url) in {ARK_HOST, LOGIN_HOST, ""}
        ),
        None,
    )
    if page is None:
        page = await context.new_page()

    log(f"[XHS] profile={profile}")
    log("[XHS] 正在打开小红书首页")
    await page.goto(XHS_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    # ark 首页可能在 DOMContentLoaded 后才异步跳转到统一登录页。
    # 等登录页或已登录菜单任一状态明确后再判断登录态，避免竞态下把
    # 尚未完成跳转的 ark 页面误判为已登录。
    deadline = asyncio.get_running_loop().time() + 45
    home_menu = page.locator("#root-menu-wrapper")
    while asyncio.get_running_loop().time() < deadline:
        if page.is_closed():
            raise RuntimeError("小红书首页在确认登录状态前已关闭")
        if is_login_page(page):
            break
        if url_host(page.url) == ARK_HOST and await home_menu.is_visible():
            break
        await asyncio.sleep(0.25)
    else:
        raise TimeoutError(f"小红书首页未进入登录页或商家后台：{page.url}")
    login_required = is_login_page(page)
    if login_required:
        log("[XHS] 检测到登录状态失效，复用 xiaohongshu_download_common.py 登录流程")
    await ensure_logged_in(page)
    if login_required:
        log("[XHS] 登录成功")
    await _log_closed_popups(page)
    return page


def url_host(url: str) -> str:
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/]+)", url or "")
    return match.group(1).split(":", 1)[0].lower() if match else ""


@automation_component("xhs.order.open_management", "小红书订单 · 打开管理页", category="report")
async def open_order_management(page: "Page") -> "Page":
    context = page.context
    menu = await _wait_first(
        page,
        [
            page.locator(ORDER_MENU_XPATH).locator("xpath=.."),
            page.locator(ORDER_MENU_XPATH),
            _visible(page.get_by_text("订单管理", exact=True)),
        ],
        "订单管理入口",
        timeout=45_000,
    )
    log("[XHS] 正在打开订单管理")
    before = set(context.pages)
    await _log_closed_popups(page)
    try:
        await click_compat(menu)
    except Exception:
        # 当前首页菜单由 Vue 自定义节点渲染。Cloak CDP 下 Playwright 的
        # locator.evaluate 兜底偶尔拿不到标准 HTMLElement，使用用户确认的
        # XPath 在页面上下文内点击其最近的 menu-item 作为兼容路径。
        log("[XHS] 首页菜单使用页面 DOM 兼容点击")
        clicked = await page.evaluate(
            """
            (xpath) => {
                const node = document.evaluate(
                    xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                ).singleNodeValue;
                const target = node?.closest?.('.menu-item') || node;
                if (!target || typeof target.click !== 'function') return false;
                target.click();
                return true;
            }
            """,
            ORDER_MENU_XPATH.removeprefix("xpath="),
        )
        if not clicked:
            raise RuntimeError("小红书订单管理入口无法通过页面 DOM 点击")

    deadline = asyncio.get_running_loop().time() + 45
    while asyncio.get_running_loop().time() < deadline:
        candidates = [
            candidate
            for candidate in context.pages
            if not candidate.is_closed() and candidate not in before
        ]
        for candidate in candidates:
            if await _first_visible([candidate.locator(ORDER_ROOT_XPATH)]) is not None:
                page = candidate
                break
        if await _first_visible([page.locator(ORDER_ROOT_XPATH)]) is not None:
            await _log_closed_popups(page)
            log("[XHS] 订单管理页已打开")
            return page
        await asyncio.sleep(0.25)

    excerpt = await _body_excerpt(page)
    raise RuntimeError(f"小红书订单管理页未加载：{page.url}；页面摘要：{excerpt}")


async def _locate_order_date_filter(page: "Page"):
    order_date_filter = page.locator("div.d-daterangepicker").filter(
        has_text=re.compile(r"下单时间")
    )
    date_controls = [
        page.locator(DATE_FILTER_XPATH),
        _visible(order_date_filter).first,
        _visible(page.locator('input[placeholder*="下单时间"]')).first,
    ]
    if await _first_visible(date_controls) is None:
        expand = await _first_visible(
            [
                _visible(page.get_by_role("button", name="展开", exact=True)),
                _visible(page.get_by_text("展开", exact=True)),
            ]
        )
        if expand is not None:
            log("[XHS] 订单筛选区已折叠，正在展开")
            await click_compat(expand)
            for _ in range(60):
                if await _first_visible(date_controls) is not None:
                    break
                await asyncio.sleep(0.2)

    date_filter = await _wait_first(
        page,
        date_controls,
        "下单时间筛选组件",
        timeout=30_000,
    )
    return date_filter


async def _open_order_date_picker(page: "Page"):
    date_filter = await _locate_order_date_filter(page)
    log("[XHS] 正在设置下单时间")
    await _log_closed_popups(page)
    await click_compat(date_filter)

    start = await _wait_first(
        page,
        [
            page.locator(DATE_START_XPATH),
            _visible(date_filter.locator(".d-daterangepicker-input-start input")).first,
            _visible(
                page.locator(
                    'input[placeholder="开始时间"], input[placeholder="开始范围"]'
                )
            ),
        ],
        "下单时间开始输入框",
        timeout=15_000,
    )
    await click_compat(start)

    popup = await _wait_first(
        page,
        [
            page.locator(DATE_POPUP_XPATH),
            _visible(
                page.locator(
                    '[role="dialog"], [class*="picker" i], [class*="calendar" i]'
                ).filter(has_text=_DATE_PRESET_RE)
            ),
            _visible(page.get_by_text(_DATE_PRESET_RE)),
        ],
        "近30天日期弹层",
        timeout=15_000,
    )
    return date_filter, start, popup


async def _read_date_picker_values(date_filter: "Locator") -> list[str]:
    values: list[str] = []
    inputs = date_filter.locator("input")
    with suppress(Exception):
        for index in range(await inputs.count()):
            candidate = inputs.nth(index)
            if await candidate.is_visible():
                values.append((await candidate.input_value()).strip())
    return values


async def _try_fill_custom_date_inputs(
    date_filter: "Locator", start_date: str, end_date: str
) -> list[str]:
    """Use the current XHS editable range inputs when the picker exposes them."""
    inputs = date_filter.locator("input")
    visible_inputs: list["Locator"] = []
    with suppress(Exception):
        for index in range(await inputs.count()):
            candidate = inputs.nth(index)
            if await candidate.is_visible() and await candidate.is_enabled():
                visible_inputs.append(candidate)
    if len(visible_inputs) < 2:
        return []

    try:
        await visible_inputs[0].fill(f"{start_date} 00:00:00")
        await visible_inputs[0].press("Enter")
        await visible_inputs[1].fill(f"{end_date} 23:59:59")
        await visible_inputs[1].press("Enter")
    except Exception:
        return []
    await asyncio.sleep(0.2)
    return await _read_date_picker_values(date_filter)


@automation_component("xhs.order.set_date", "小红书订单 · 设置日期", category="report")
async def select_recent_30_days(page: "Page") -> None:
    date_filter, start, popup = await _open_order_date_picker(page)
    preset = await _wait_first(
        page,
        [
            page.locator(DATE_PRESET_XPATH),
            popup.get_by_role("button", name=_DATE_PRESET_RE),
            popup.get_by_text(_DATE_PRESET_RE),
            _visible(page.get_by_role("button", name=_DATE_PRESET_RE)),
        ],
        "近30天快捷按钮",
        timeout=15_000,
    )
    await click_compat(preset)

    # 当前 XHS 版本可能只渲染一个可读的范围输入框；若存在第二个
    # 输入框则一并记录，但不能用一个未提供的结束框 XPath 阻断快捷项。
    end = await _first_visible(
        [
            page.locator(DATE_END_XPATH),
            date_filter.locator("input").nth(1),
            _visible(
                page.locator(
                    'input[placeholder="结束时间"], input[placeholder="结束范围"]'
                )
            ),
        ]
    )
    values: tuple[str, str] = ("", "")
    for _ in range(40):
        with suppress(Exception):
            start_value = (await start.input_value()).strip()
            end_value = (await end.input_value()).strip() if end is not None else ""
            values = (start_value, end_value)
        if values[0] and (values[1] or end is None):
            break
        await asyncio.sleep(0.15)
    if not values[0] or (end is not None and not values[1]):
        raise RuntimeError(f"点击“近30天”后日期输入框未填充：{values}")
    with suppress(Exception):
        if await popup.is_visible():
            await page.keyboard.press("Escape")
    selected_range = f"{values[0]} ~ {values[1]}" if values[1] else values[0]
    log(f"[XHS] 已选择近30天：{selected_range}")


def _calendar_months(text: str) -> list[tuple[int, int]]:
    months: list[tuple[int, int]] = []
    for year, month in _CALENDAR_MONTH_RE.findall(text or ""):
        value = (int(year), int(month))
        if value not in months:
            months.append(value)
    return months


async def _calendar_months_visible(popup: "Locator") -> list[tuple[int, int]]:
    with suppress(Exception):
        text = await popup.inner_text(timeout=2_000)
        months = _calendar_months(text)
        if months:
            return months

    # Some picker versions hide the header text but expose ISO dates on cells.
    dates = popup.locator("[data-date], [title], [aria-label]")
    months: list[tuple[int, int]] = []
    with suppress(Exception):
        for index in range(min(await dates.count(), 300)):
            candidate = dates.nth(index)
            if not await candidate.is_visible():
                continue
            descriptor = " ".join(
                filter(
                    None,
                    [
                        await candidate.get_attribute("data-date"),
                        await candidate.get_attribute("title"),
                        await candidate.get_attribute("aria-label"),
                    ],
                )
            )
            match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月]", descriptor)
            if match:
                value = (int(match.group(1)), int(match.group(2)))
                if value not in months:
                    months.append(value)
    return months


async def _calendar_navigation_button(popup: "Locator", direction: str):
    pattern = _CALENDAR_PREV_RE if direction == "prev" else _CALENDAR_NEXT_RE
    candidates = popup.locator('button, [role="button"], a')
    with suppress(Exception):
        for index in range(min(await candidates.count(), 120)):
            candidate = candidates.nth(index)
            if not await candidate.is_visible():
                continue
            descriptor = " ".join(
                filter(
                    None,
                    [
                        await candidate.inner_text(timeout=300),
                        await candidate.get_attribute("aria-label"),
                        await candidate.get_attribute("title"),
                        await candidate.get_attribute("class"),
                        await candidate.get_attribute("data-testid"),
                    ],
                )
            )
            if pattern.search(descriptor):
                return candidate
    return None


async def _switch_calendar_month(
    popup: "Locator", target: tuple[int, int], *, max_steps: int = 24
) -> None:
    for _ in range(max_steps + 1):
        months = await _calendar_months_visible(popup)
        if target in months:
            return
        if not months:
            raise RuntimeError("小红书日期弹层未显示可识别的月份")
        current = months[0]
        direction = "prev" if current > target else "next"
        button = await _calendar_navigation_button(popup, direction)
        if button is None:
            raise RuntimeError(
                f"小红书日期弹层无法从 {current[0]}年{current[1]}月切换到 "
                f"{target[0]}年{target[1]}月"
            )
        before = months
        await click_compat(button, timeout=5_000)
        for _ in range(40):
            await asyncio.sleep(0.1)
            after = await _calendar_months_visible(popup)
            if after != before:
                break
    raise RuntimeError(f"小红书日期弹层无法切换到 {target[0]}年{target[1]}月")


async def _first_enabled_calendar_candidate(locator: "Locator"):
    with suppress(Exception):
        for index in range(min(await locator.count(), 80)):
            candidate = locator.nth(index)
            if not await candidate.is_visible():
                continue
            if not await candidate.is_enabled():
                continue
            if (await candidate.get_attribute("aria-disabled") or "").lower() == "true":
                continue
            class_name = await candidate.get_attribute("class") or ""
            if re.search(r"disabled|unavailable", class_name, re.I):
                continue
            return candidate
    return None


async def _click_calendar_date(popup: "Locator", target: date) -> None:
    await _switch_calendar_month(popup, (target.year, target.month))
    iso = target.isoformat()
    values = (
        iso,
        target.strftime("%Y/%m/%d"),
        target.strftime("%Y.%m.%d"),
        f"{target.year}年{target.month}月{target.day}日",
        f"{target.year}年{target.month:02d}月{target.day:02d}日",
    )
    for attribute in ("data-date", "date", "title", "aria-label"):
        for value in values:
            candidate = await _first_enabled_calendar_candidate(
                popup.locator(f'[{attribute}="{value}"]')
            )
            if candidate is not None:
                await click_compat(candidate, timeout=5_000)
                return

    # Final compatibility fallback for date pickers that expose only day text.
    day = await _first_enabled_calendar_candidate(
        popup.get_by_text(str(target.day), exact=True)
    )
    if day is None:
        raise RuntimeError(f"小红书日期弹层未找到日期：{iso}")
    await click_compat(day, timeout=5_000)


async def _close_custom_date_picker(page: "Page", popup: "Locator") -> None:
    with suppress(Exception):
        if not await popup.is_visible():
            return
    confirm = await _first_visible(
        [
            popup.get_by_role("button", name=re.compile(r"^\s*(确定|确认)\s*$")),
            popup.get_by_text(re.compile(r"^\s*(确定|确认)\s*$")),
        ]
    )
    if confirm is not None:
        await click_compat(confirm, timeout=5_000)
        return
    with suppress(Exception):
        await page.keyboard.press("Escape")


@automation_component("xhs.order.set_date", "小红书订单 · 设置日期", category="report")
async def select_custom_date_range(
    page: "Page", start_date: str, end_date: str
) -> None:
    start_target = _parse_iso_date(start_date, "--start-date")
    end_target = _parse_iso_date(end_date, "--end-date")
    if start_target > end_target:
        raise ValueError(f"--start-date 不能晚于 --end-date：{start_date} > {end_date}")

    # 当前订单页的两个输入框是可编辑的；直接写入完整时间并回车，
    # 触发页面自己的日期状态更新，避免依赖日历月份和日期节点结构。
    date_filter = await _locate_order_date_filter(page)
    values = await _try_fill_custom_date_inputs(date_filter, start_date, end_date)
    combined = " ~ ".join(values)
    if values and _date_value_contains(combined, start_date) and _date_value_contains(
        combined, end_date
    ):
        log(f"[XHS] 已选择自定义日期范围：{combined}")
        return

    # 兼容旧版只提供日历选择的页面。
    date_filter, _start, popup = await _open_order_date_picker(page)
    await _click_calendar_date(popup, start_target)
    await asyncio.sleep(0.2)
    await _click_calendar_date(popup, end_target)
    await _close_custom_date_picker(page, popup)

    values = await _read_date_picker_values(date_filter)
    combined = " ~ ".join(values)
    if not values or not _date_value_contains(combined, start_date) or not _date_value_contains(
        combined, end_date
    ):
        raise RuntimeError(
            f"自定义日期范围未提交：期望 {start_date} ~ {end_date}，页面值 {combined!r}"
        )
    log(f"[XHS] 已选择自定义日期范围：{combined}")


@automation_component("xhs.order.query", "小红书订单 · 查询", category="report")
async def query_orders(page: "Page") -> None:
    query = await _wait_first(
        page,
        [
            page.locator(QUERY_BUTTON_XPATH),
            _visible(page.get_by_role("button", name="查询", exact=True)),
            _visible(page.get_by_text("查询", exact=True)),
        ],
        "查询按钮",
        timeout=15_000,
    )
    log("[XHS] 正在查询订单")
    await _log_closed_popups(page)
    await click_compat(query)
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=5_000)
    await asyncio.sleep(0.8)
    await _log_closed_popups(page)
    log("[XHS] 查询完成")


async def _find_export_notice(page: "Page"):
    return await _wait_first(
        page,
        [
            _visible(
                page.locator("div.d-modal-mask").filter(
                    has_text=re.compile(
                        r"为保护消费者信息安全|单次导出商品行数上限"
                    )
                )
            ),
            page.locator(NOTICE_XPATH),
            _visible(
                page.locator(
                    '[role="dialog"], [class*="modal" i], [class*="confirm" i], '
                    '[class*="notice" i]'
                ).filter(has_text=_NOTICE_TEXT_RE)
            ),
            _visible(page.locator("body > div").filter(has_text=_NOTICE_TEXT_RE)),
        ],
        "导出提示弹窗",
        timeout=20_000,
    )


@automation_component("xhs.order.export", "小红书订单 · 导出", category="report")
async def export_orders(page: "Page", work_dir: Path) -> Path:
    export = await _wait_first(
        page,
        [
            page.locator(EXPORT_BUTTON_XPATH),
            _visible(page.get_by_role("button", name="全部导出", exact=True)),
            _visible(page.get_by_text("全部导出", exact=True)),
        ],
        "全部导出按钮",
        timeout=20_000,
    )
    log("[XHS] 正在创建订单导出任务")
    await _log_closed_popups(page)
    async with page.expect_download(timeout=180_000) as download_info:
        await click_compat(export)
        notice = await _find_export_notice(page)
        log("[XHS] 检测到导出提示弹窗")
        confirm = await _wait_first(
            page,
            [
                _visible(
                    notice.locator("button").filter(
                        has_text=re.compile(r"^\s*确定\s*$")
                    ).last
                ),
                page.locator(NOTICE_CONFIRM_XPATH),
                notice.get_by_role("button", name="确定", exact=True),
                _visible(page.get_by_role("button", name="确定", exact=True)).last,
                notice.get_by_text("确定", exact=True),
                _visible(page.locator("button").filter(has_text=re.compile(r"^\s*确定\s*$"))).last,
            ],
            "导出提示弹窗确定按钮",
            timeout=10_000,
        )
        await click_compat(confirm)
        log("[XHS] 已确认导出提示")
    download: "Download" = await download_info.value
    log("[XHS] 导出任务创建成功")
    source = await save_download(download, work_dir, "xiaohongshu_order.xlsx")
    log("[XHS] 订单报表下载完成")
    log(f"[XHS] xlsx_path={source}")
    return source


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_order_report(report: Path) -> None:
    """校验小红书订单 XLSX 可读且包含 ODS loader 的必需表头字段。"""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(report, read_only=True, data_only=True)
    except Exception as exc:
        raise RuntimeError(f"小红书订单 XLSX 读取失败：{exc}") from exc
    try:
        if not workbook.sheetnames:
            raise RuntimeError("小红书订单 XLSX 没有工作表")
        warn_unread_sheets(
            "小红书订单", workbook.sheetnames, (workbook.worksheets[0].title,)
        )
        header = read_header(workbook.worksheets[0])
        validate_report_columns(
            header,
            XHS_ORDER_HEADERS,
            report_name="小红书订单",
            missing_error_prefix="小红书订单表头异常，缺少必需字段：",
        )
    finally:
        workbook.close()


@automation_component("xhs.order.workflow", "小红书订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    business_date: str | None = None,
    profile: str = DEFAULT_PROFILE,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    business_date = business_date or end_date or date.today().isoformat()
    work_dir.mkdir(parents=True, exist_ok=True)
    page: "Page | None" = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            context = browser.contexts[0]
            page = await open_home_page(context, profile)
            page = await open_order_management(page)
            if start_date and end_date:
                await select_custom_date_range(page, start_date, end_date)
            else:
                await select_recent_30_days(page)
            await query_orders(page)
            source = await export_orders(page, work_dir)
            log("[XHS] 正在校验订单报表")
            await asyncio.to_thread(validate_order_report, source)
            log("[XHS] XLSX 校验成功")
            log("[XHS] 正在归档订单报表")
            archive_path = await asyncio.to_thread(
                archive_report,
                source,
                platform,
                company,
                shop,
                REPORT_NAME,
                business_date,
                dest,
            )
            log(f"[XHS] archive_path={archive_path}")
            log("[XHS] 文件移动成功")
            log("[XHS] 任务完成")
    finally:
        if page is not None and not page.is_closed():
            with suppress(Exception):
                await page.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书订单标准报表下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="本次运行的 Cloak Login profile 名称")
    parser.add_argument("--platform", default=PLATFORM)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument(
        "--work-dir",
        default=None,
        help="XLSX 下载工作目录；默认 data\\.automation_cache\\xiaohongshu_order\\<shop>",
    )
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="归档根目录")
    parser.add_argument("--business-date", default=None, help="归档日期前缀，默认查询结束日期或今天")
    parser.add_argument("--start-date", default=None, help="自定义下单开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义下单结束日期 YYYY-MM-DD")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr, flush=True)
        return 2
    if (args.start_date is None) != (args.end_date is None):
        print("--start-date 和 --end-date 必须同时提供", file=sys.stderr, flush=True)
        return 2
    if args.start_date and args.end_date:
        try:
            start_target = _parse_iso_date(args.start_date, "--start-date")
            end_target = _parse_iso_date(args.end_date, "--end-date")
        except ValueError as exc:
            print(str(exc), file=sys.stderr, flush=True)
            return 2
        if start_target > end_target:
            print("--start-date 不能晚于 --end-date", file=sys.stderr, flush=True)
            return 2
    work_dir = (
        Path(args.work_dir)
        if args.work_dir
        else Path(args.dest) / ".automation_cache" / "xiaohongshu_order" / args.shop
    )
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
                args.profile,
                args.start_date,
                args.end_date,
            )
        )
    except Exception as exc:
        print(f"[XHS] 执行失败：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
