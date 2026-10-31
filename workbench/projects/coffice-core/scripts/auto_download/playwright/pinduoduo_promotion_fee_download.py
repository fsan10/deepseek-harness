# -*- coding: utf-8 -*-
"""下载拼多多推广账户现金支出明细并按项目标准归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .pinduoduo_login import ensure_pinduoduo_login
from .report_validation import validate_report_columns, warn_unread_sheets

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Download, Locator, Page


PROMOTION_FINANCE_URL = "https://yingxiao.pinduoduo.com/mains/account/finance"
PROMOTION_REPORT_URL = "https://yingxiao.pinduoduo.com/mains/account/report"
PROMOTION_NAV_XPATH = '//*[@id="__msfe__side-nav_item_3516"]/a/span'
FINANCE_FLOW_XPATH = '//*[@id="page-container"]/div/div/div[1]/div/div[2]/ul/li[2]/span'
FUND_TYPE_INPUT = "#rc_select_0"
FLOW_TYPE_INPUT = "#rc_select_1"
QUERY_XPATH = (
    '//*[@id="page-container"]/div/div/div[2]/div/div[2]/div[2]/div[2]'
    "/div[2]/button[1]/span"
)
DOWNLOAD_XPATH = (
    '//*[@id="page-container"]/div/div/div[2]/div/div[2]/div[2]/div[4]'
    "/div[1]/button/span[2]"
)
REPORT_NAME = "推广费"
DEFAULT_SHEET_NAME = "Sheet0"
PROJECT_ROOT = Path(__file__).resolve().parents[3]

EXPECTED_COLUMNS = (
    "时间",
    "资金类型",
    "流水类型",
    "店铺名称",
    "交易金额",
    "余额",
    "交易摘要",
)
UI_TABLE_COLUMNS = ("时间", "资金类型", "流水类型", "交易金额 (元)")
DATE_PATTERN = re.compile(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})")
PROMOTION_START_DATE_INPUT = 'input[placeholder="开始日期"]'
PROMOTION_END_DATE_INPUT = 'input[placeholder="结束日期"]'
PROMOTION_DATE_PICKER = "div.anq-picker-dropdown.anq-range-picker-dropdown-cls"
SESSION_MARKERS = (
    "会话异常",
    "登录失效",
    "请先登录",
    "登录后继续",
    "未登录",
)


def log(stage: str, message: str) -> None:
    """输出可检索的阶段日志，不输出凭据或验证码。"""

    print(f"[PDD推广费][{stage}] {message}")


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\ufeff", "").split())


async def _visible(locator: "Locator") -> bool:
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def _first_visible(locator: "Locator") -> "Locator | None":
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def click_compat(locator: "Locator", *, timeout: int = 10_000) -> None:
    """点击拼多多 portal 控件；必要时回退到同一 DOM 节点的 click 事件。"""

    try:
        await locator.click(timeout=timeout, no_wait_after=True)
        return
    except Exception as first_error:
        try:
            await locator.evaluate("element => element.click()")
            return
        except Exception:
            raise first_error


async def _body_text(page: "Page") -> str:
    try:
        return await page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


async def has_session_failure(page: "Page") -> bool:
    if "/login" in (page.url or "").lower():
        return True
    text = await _body_text(page)
    return any(marker in text for marker in SESSION_MARKERS)


async def wait_report_controls(page: "Page", timeout: int = 60_000) -> None:
    """等待财务流水页真正渲染出筛选与下载控件。"""

    await page.locator("#page-container").wait_for(state="visible", timeout=timeout)
    await page.locator(FUND_TYPE_INPUT).wait_for(state="attached", timeout=timeout)
    await page.locator(FLOW_TYPE_INPUT).wait_for(state="attached", timeout=timeout)
    download = page.get_by_role("button", name="下载明细", exact=True).last
    await download.wait_for(state="visible", timeout=timeout)


async def _wait_report_candidate(page: "Page", timeout: int = 60_000) -> bool:
    try:
        await wait_report_controls(page, timeout=timeout)
        return True
    except Exception:
        return False


async def _open_report_from_finance(context: "BrowserContext", finance_page: "Page") -> "Page":
    """从推广平台财务管理页点击财务流水，兼容新标签页或当前页路由。"""

    if await _wait_report_candidate(finance_page, timeout=5_000):
        return finance_page

    flow = finance_page.locator(FINANCE_FLOW_XPATH).first
    if not await _visible(flow):
        flow = finance_page.get_by_role("menuitem", name="财务流水", exact=True).last
    await flow.wait_for(state="visible", timeout=60_000)
    known_pages = set(context.pages)
    await click_compat(flow)

    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        candidates = [finance_page]
        candidates.extend(
            page
            for page in context.pages
            if page not in known_pages and not page.is_closed()
        )
        for candidate in candidates:
            if candidate.is_closed() or "yingxiao.pinduoduo.com" not in candidate.url:
                continue
            if await _wait_report_candidate(candidate, timeout=1_000):
                return candidate
        await asyncio.sleep(0.25)

    # 财务平台是同一登录态；菜单未完成 SPA 路由时，使用用户指定的报表地址兜底。
    await finance_page.goto(PROMOTION_REPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    await wait_report_controls(finance_page, timeout=60_000)
    return finance_page


async def _open_from_mms_home(context: "BrowserContext", home: "Page") -> "Page":
    """从商家后台首页点击推广账户，处理跳转新标签页和当前页导航。"""

    if "mms.pinduoduo.com" not in home.url or "/login" in home.url:
        await home.goto("https://mms.pinduoduo.com/home", wait_until="domcontentloaded", timeout=60_000)

    nav = home.locator(PROMOTION_NAV_XPATH).first
    await nav.wait_for(state="visible", timeout=60_000)
    known_pages = set(context.pages)
    await click_compat(nav)

    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        candidates = [home]
        candidates.extend(
            page
            for page in context.pages
            if page not in known_pages and not page.is_closed()
        )
        for candidate in candidates:
            if candidate.is_closed() or "yingxiao.pinduoduo.com" not in candidate.url:
                continue
            if await _wait_report_candidate(candidate, timeout=1_000):
                return candidate
            if "/mains/account/finance" in candidate.url:
                return await _open_report_from_finance(context, candidate)
        await asyncio.sleep(0.25)
    raise RuntimeError("从拼多多商家后台点击“推广账户”后未打开推广平台")


async def _existing_promotion_page(context: "BrowserContext") -> "Page | None":
    """复用已经打开的推广页，避免每次运行都新建标签页。"""

    for candidate in context.pages:
        if candidate.is_closed() or "yingxiao.pinduoduo.com" not in candidate.url:
            continue
        if "/mains/account/report" in candidate.url:
            if await _wait_report_candidate(candidate, timeout=8_000):
                return candidate
        elif "/mains/account/finance" in candidate.url:
            try:
                return await _open_report_from_finance(context, candidate)
            except Exception:
                continue
    return None


@automation_component("pinduoduo.promotion.open", "拼多多推广费 · 打开报表页", category="report")
async def open_promotion_page(
    context: "BrowserContext", *, platform: str, company: str, shop: str
) -> tuple["Page", list["Page"]]:
    """优先复用现有推广页；没有可用页面时再走登录和商家后台兜底。"""

    existing = await _existing_promotion_page(context)
    if existing is not None and not await has_session_failure(existing):
        log("导航", f"复用现有财务流水页={existing.url}")
        return existing, []

    before_login_pages = set(context.pages)
    home = await ensure_pinduoduo_login(
        context, platform=platform, company=company, shop=shop
    )
    pages_to_close = [
        page for page in context.pages if page not in before_login_pages and not page.is_closed()
    ]
    log("登录", f"已确认商家后台登录态，首页={home.url.split('?')[0]}")

    existing_after_login = await _existing_promotion_page(context)
    if existing_after_login is not None and not await has_session_failure(existing_after_login):
        log("导航", f"复用登录后财务流水页={existing_after_login.url}")
        return existing_after_login, pages_to_close

    # 没有现成推广页时，只在登录态确认后复用商家首页点击入口；不额外创建直达标签页。
    log("导航", "当前没有可复用推广页，从商家后台点击“推广账户”")

    if home.is_closed() or "mms.pinduoduo.com" not in home.url or "/login" in home.url:
        before_retry_pages = set(context.pages)
        home = await ensure_pinduoduo_login(
            context, platform=platform, company=company, shop=shop
        )
        pages_to_close.extend(
            page
            for page in context.pages
            if page not in before_retry_pages
            and page not in pages_to_close
            and not page.is_closed()
        )

    fallback = await _open_from_mms_home(context, home)
    if fallback not in pages_to_close and fallback is not home:
        pages_to_close.append(fallback)
    return fallback, pages_to_close


async def _find_visible_option(
    page: "Page", label: str, *, list_id: str | None = None
) -> "Locator | None":
    """Find an exact option in the open select's own portal dropdown."""

    if list_id and re.fullmatch(r"[A-Za-z0-9_-]+", list_id):
        dropdowns = page.locator(
            ".anq-select-dropdown:not(.anq-select-dropdown-hidden)"
        )
        for dropdown_index in range(await dropdowns.count()):
            dropdown = dropdowns.nth(dropdown_index)
            if not await _visible(dropdown):
                continue
            if await dropdown.locator(f"#{list_id}").count() == 0:
                continue
            options = dropdown.locator(".anq-select-item-option")
            for option_index in range(await options.count()):
                option = options.nth(option_index)
                if (
                    await _visible(option)
                    and normalize_text(await option.inner_text()) == label
                ):
                    return option

    candidates = (
        page.get_by_role("option", name=label, exact=True),
        page.locator('[role="listbox"] [role="option"]').filter(has_text=label),
        page.locator(
            '.anq-select-dropdown:not(.anq-select-dropdown-hidden) '
            '.anq-select-item-option'
        ).filter(has_text=label),
        page.locator(
            '.anq-select-dropdown:not(.anq-select-dropdown-hidden) li'
        ).filter(has_text=label),
    )
    for candidate_set in candidates:
        target = await _first_visible(candidate_set)
        if target is not None and normalize_text(await target.inner_text()) == label:
            return target
    return None


async def choose_select_option(page: "Page", input_selector: str, label: str) -> None:
    """打开 antd 风格选择框并选择精确文本，避免点击表格中的同名单元格。"""

    input_locator = page.locator(input_selector).first
    await input_locator.wait_for(state="attached", timeout=30_000)
    container = input_locator.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' anq-select ')][1]"
    )
    selector = container.locator(".anq-select-selector").first
    list_id = normalize_text(await input_locator.get_attribute("aria-controls"))
    last_error: Exception | None = None

    async def selected_text() -> str:
        selected = container.locator(".anq-select-selection-item").first
        if await _visible(selected):
            return normalize_text(await selected.inner_text())
        return normalize_text(await selector.inner_text())

    async def wait_until_selected() -> bool:
        deadline = asyncio.get_running_loop().time() + 3
        while asyncio.get_running_loop().time() < deadline:
            if await selected_text() == label:
                return True
            await asyncio.sleep(0.1)
        return await selected_text() == label

    try:
        # The search input is opacity-zero and the select trigger is the actual
        # hit target. Scope the option lookup to this combobox's aria-controls
        # list so an unrelated portal option cannot falsely satisfy the check.
        await click_compat(selector, timeout=5_000)
        option: "Locator | None" = None
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            option = await _find_visible_option(page, label, list_id=list_id)
            if option is not None:
                break
            await asyncio.sleep(0.1)
        if option is None:
            raise RuntimeError("目标选择框的选项列表未打开")
        await click_compat(option, timeout=5_000)
        if await wait_until_selected():
            return
        raise RuntimeError(f"点击选项后实际显示“{await selected_text() or '请选择'}”")
    except Exception as exc:
        last_error = exc

    # Some portal builds render the option but do not commit the pointer click.
    # Use the combobox keyboard path and verify the committed selection itself.
    try:
        if await input_locator.get_attribute("aria-expanded") == "true":
            await input_locator.press("Escape")
        await input_locator.focus()
        await input_locator.press("ArrowDown")
        deadline = asyncio.get_running_loop().time() + 5
        options: list["Locator"] = []
        labels: list[str] = []
        while asyncio.get_running_loop().time() < deadline:
            dropdowns = page.locator(
                ".anq-select-dropdown:not(.anq-select-dropdown-hidden)"
            )
            for dropdown_index in range(await dropdowns.count()):
                dropdown = dropdowns.nth(dropdown_index)
                if not await _visible(dropdown):
                    continue
                if list_id and await dropdown.locator(f"#{list_id}").count() == 0:
                    continue
                candidate_options = dropdown.locator(".anq-select-item-option")
                current_options: list["Locator"] = []
                current_labels: list[str] = []
                for option_index in range(await candidate_options.count()):
                    candidate = candidate_options.nth(option_index)
                    if await _visible(candidate):
                        current_options.append(candidate)
                        current_labels.append(
                            normalize_text(await candidate.inner_text())
                        )
                if current_options:
                    options, labels = current_options, current_labels
                    break
            if options:
                break
            await asyncio.sleep(0.1)

        if label not in labels:
            raise RuntimeError("键盘选择时未找到目标选项")
        active_index = 0
        for index, option in enumerate(options):
            class_name = await option.get_attribute("class") or ""
            if "anq-select-item-option-active" in class_name:
                active_index = index
                break
        target_index = labels.index(label)
        while active_index < target_index:
            await input_locator.press("ArrowDown")
            active_index += 1
        while active_index > target_index:
            await input_locator.press("ArrowUp")
            active_index -= 1
        await input_locator.press("Enter")
        if await wait_until_selected():
            return
        raise RuntimeError(f"键盘确认后实际显示“{await selected_text() or '请选择'}”")
    except Exception as keyboard_error:
        actual = await selected_text()
        raise RuntimeError(
            f"拼多多选择框未确认选中“{label}”：实际显示“{actual or '请选择'}”；"
            f"点击路径={last_error}；键盘路径={keyboard_error}"
        ) from keyboard_error


async def _selected_select_text(page: "Page", input_selector: str) -> str:
    input_locator = page.locator(input_selector).first
    container = input_locator.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' anq-select ')][1]"
    )
    selected = container.locator(".anq-select-selection-item").first
    if await _visible(selected):
        return normalize_text(await selected.inner_text())
    selector = container.locator(".anq-select-selector").first
    return normalize_text(await selector.inner_text())


async def _visible_date_picker(page: "Page") -> "Locator | None":
    return await _first_visible(page.locator(PROMOTION_DATE_PICKER))


async def _open_date_picker(page: "Page", input_locator: "Locator") -> None:
    if await _visible_date_picker(page) is not None:
        return
    await click_compat(input_locator, timeout=10_000)
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if await _visible_date_picker(page) is not None:
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("拼多多推广费日期弹层未打开")


async def _fill_promotion_date_input(
    page: "Page", input_selector: str, value: str
) -> None:
    input_locator = page.locator(input_selector).first
    await input_locator.wait_for(state="visible", timeout=30_000)
    try:
        await input_locator.fill(value, timeout=5_000)
    except Exception:
        # 点击范围输入框后，推广平台会临时去掉开始框的 readonly；若版本未及时切换，
        # 只对当前 DOM 节点临时解除 readonly，再让 Playwright 触发标准 input 事件。
        await input_locator.evaluate(
            "element => { element.removeAttribute('readonly'); element.readOnly = false; }"
        )
        await input_locator.fill(value, timeout=5_000)
    await input_locator.press("Enter")
    await asyncio.sleep(0.3)
    actual = normalize_text(await input_locator.input_value())
    if actual != value:
        raise RuntimeError(
            f"拼多多推广费日期输入未生效：期望 {value}，实际 {actual or '空值'}"
        )


@automation_component("pinduoduo.promotion.set_date", "拼多多推广费 · 设置日期范围", category="report")
async def set_promotion_date_range(
    page: "Page", start_date: dt.date, end_date: dt.date
) -> None:
    """直接填写推广平台日期框并回车，不依赖易变的绝对 XPath。"""

    if start_date > end_date:
        raise ValueError(f"推广费开始日期晚于结束日期：{start_date} > {end_date}")
    start_value = start_date.strftime("%Y/%m/%d")
    end_value = end_date.strftime("%Y/%m/%d")
    start_input = page.locator(PROMOTION_START_DATE_INPUT).first
    end_input = page.locator(PROMOTION_END_DATE_INPUT).first
    await start_input.wait_for(state="visible", timeout=30_000)
    await end_input.wait_for(state="visible", timeout=30_000)

    await _open_date_picker(page, start_input)
    await _fill_promotion_date_input(page, PROMOTION_START_DATE_INPUT, start_value)
    if await _visible_date_picker(page) is None:
        await _open_date_picker(page, end_input)
    await _fill_promotion_date_input(page, PROMOTION_END_DATE_INPUT, end_value)

    final_start = normalize_text(await page.locator(PROMOTION_START_DATE_INPUT).first.input_value())
    final_end = normalize_text(await page.locator(PROMOTION_END_DATE_INPUT).first.input_value())
    if final_start != start_value or final_end != end_value:
        raise RuntimeError(
            "拼多多推广费日期范围未确认："
            f"实际为 {final_start or '空值'} ~ {final_end or '空值'}"
        )
    log("筛选", f"日期={start_value} 00:00:00 ~ {end_value} 23:59:59")


@automation_component("pinduoduo.promotion.apply_filters", "拼多多推广费 · 设置筛选", category="report")
async def apply_filters(
    page: "Page", *, start_date: dt.date | None = None, end_date: dt.date | None = None
) -> None:
    if (start_date is None) != (end_date is None):
        raise ValueError("推广费自定义日期必须同时提供开始日期和结束日期")
    if start_date is not None and end_date is not None:
        await set_promotion_date_range(page, start_date, end_date)
    await choose_select_option(page, FUND_TYPE_INPUT, "现金")
    log("筛选", "资金类型=现金")
    await choose_select_option(page, FLOW_TYPE_INPUT, "支出")
    log("筛选", "流水类型=支出")
    for input_selector, expected in (
        (FUND_TYPE_INPUT, "现金"),
        (FLOW_TYPE_INPUT, "支出"),
    ):
        actual = await _selected_select_text(page, input_selector)
        if actual != expected:
            raise RuntimeError(
                f"拼多多推广费筛选状态未保持：期望“{expected}”，"
                f"实际显示“{actual or '请选择'}”"
            )


async def _query_button(page: "Page") -> "Locator":
    span = page.locator(QUERY_XPATH).first
    if await _visible(span):
        button = span.locator("xpath=ancestor::button[1]")
        if await _visible(button):
            return button
    button = page.get_by_role("button", name="查询", exact=True).last
    await button.wait_for(state="visible", timeout=30_000)
    return button


async def _download_button(page: "Page") -> "Locator":
    span = page.locator(DOWNLOAD_XPATH).first
    if await _visible(span):
        button = span.locator("xpath=ancestor::button[1]")
        if await _visible(button):
            return button
    button = page.get_by_role("button", name="下载明细", exact=True).last
    await button.wait_for(state="visible", timeout=30_000)
    return button


@automation_component("pinduoduo.promotion.query", "拼多多推广费 · 查询", category="report")
async def query_filtered_rows(
    page: "Page", *, start_date: dt.date | None = None, end_date: dt.date | None = None
) -> tuple[int, Decimal]:
    """点击查询并确认页面明细符合现金/支出及可选日期筛选。"""

    query = await _query_button(page)
    await click_compat(query)
    deadline = asyncio.get_running_loop().time() + 30
    last_headers: list[str] = []
    last_rows = 0
    while asyncio.get_running_loop().time() < deadline:
        tables = page.locator("table")
        for index in range(await tables.count()):
            table = tables.nth(index)
            headers = [
                normalize_text(await table.locator("thead th").nth(i).inner_text())
                for i in range(await table.locator("thead th").count())
            ]
            if not all(column in headers for column in UI_TABLE_COLUMNS):
                continue
            last_headers = headers
            index_fund = headers.index("资金类型")
            index_flow = headers.index("流水类型")
            index_amount = headers.index("交易金额 (元)")
            index_time = headers.index("时间")
            rows = table.locator("tbody tr")
            last_rows = await rows.count()
            if not last_rows:
                continue
            amounts: list[Decimal] = []
            invalid: list[str] = []
            for row_index in range(last_rows):
                cells = rows.nth(row_index).locator("td")
                values = [
                    normalize_text(await cells.nth(cell_index).inner_text())
                    for cell_index in range(await cells.count())
                ]
                if max(index_time, index_fund, index_flow, index_amount) >= len(values):
                    invalid.append("列数不足")
                    continue
                if values[index_fund] != "现金" or values[index_flow] != "支出":
                    invalid.append("、".join(values[:4]))
                    continue
                row_date = parse_date_value(values[index_time])
                if row_date is None or (
                    start_date is not None and row_date < start_date
                ) or (end_date is not None and row_date > end_date):
                    invalid.append(f"日期不在请求范围：{values[index_time]}")
                    continue
                amount = parse_amount(values[index_amount])
                if amount is not None:
                    amounts.append(abs(amount))
            if invalid:
                continue
            if amounts:
                return last_rows, sum(amounts, Decimal("0.00"))
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"拼多多推广费查询结果未稳定为现金支出：表头={last_headers or '无'}，明细行数={last_rows}"
    )


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download: "Download", directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = download.suggested_filename or "pinduoduo_promotion_fee.xlsx"
    target = directory / filename
    if target.exists():
        stem, suffix = target.stem, target.suffix
        for sequence in range(2, 1000):
            target = directory / f"{stem}_{sequence:03d}{suffix}"
            if not target.exists():
                break
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"拼多多推广费下载文件为空：{target}")
    return target


def parse_amount(value: Any) -> Decimal | None:
    text = normalize_text(value).replace(",", "").replace("元", "")
    if not text or text in {"-", "—", "–"}:
        return None
    text = text.replace("+", "")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise RuntimeError(f"推广费交易金额无法解析：{value!r}") from exc


def parse_date_value(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    match = DATE_PATTERN.search(normalize_text(value))
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _read_workbook_rows(path: Path) -> tuple[str, list[list[Any]]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("缺少 openpyxl，无法验收拼多多推广费 XLSX") from exc
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            if not workbook.worksheets:
                raise RuntimeError(f"拼多多推广费工作簿没有工作表：{path}")
            worksheet = (
                workbook[DEFAULT_SHEET_NAME]
                if DEFAULT_SHEET_NAME in workbook.sheetnames
                else workbook.worksheets[0]
            )
            warn_unread_sheets("拼多多推广费", workbook.sheetnames, (worksheet.title,))
            if hasattr(worksheet, "reset_dimensions"):
                worksheet.reset_dimensions()
            rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
            return worksheet.title, rows
        finally:
            workbook.close()
    if suffix == ".xls":
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError("缺少 xlrd，无法验收拼多多推广费 XLS") from exc
        workbook = xlrd.open_workbook(path, on_demand=True)
        try:
            worksheet = workbook.sheet_by_index(0)
            warn_unread_sheets("拼多多推广费", workbook.sheet_names(), (worksheet.name,))
            rows = [worksheet.row_values(index) for index in range(worksheet.nrows)]
            return worksheet.name, rows
        finally:
            workbook.release_resources()
    raise RuntimeError(f"拼多多推广费文件类型不支持：{path.suffix}")


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_download(
    path: Path,
    shop: str,
    *,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> dict[str, Any]:
    """验收下载文件，使其可直接交给 pdd 推广费 ODS loader。"""

    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"拼多多推广费归档文件为空或不存在：{path}")
    if (start_date is None) != (end_date is None):
        raise ValueError("推广费验收日期必须同时提供开始日期和结束日期")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError(f"推广费验收开始日期晚于结束日期：{start_date} > {end_date}")
    sheet_name, rows = _read_workbook_rows(path)
    if not rows:
        raise RuntimeError(f"拼多多推广费工作表为空：{path}")

    headers = [normalize_text(value) for value in rows[0]]
    validate_report_columns(
        headers,
        EXPECTED_COLUMNS,
        report_name="拼多多推广费",
        missing_error_prefix="拼多多推广费表头不匹配，缺少：",
    )
    positions = {column: headers.index(column) for column in EXPECTED_COLUMNS}

    parsed_rows = 0
    dates: list[dt.date] = []
    total_amount = Decimal("0.00")
    for row_number, raw_row in enumerate(rows[1:], start=2):
        values = [normalize_text(value) for value in raw_row]
        if not any(values):
            continue
        if max(positions.values()) >= len(values):
            raise RuntimeError(f"拼多多推广费第 {row_number} 行列数不足")
        business_date = parse_date_value(raw_row[positions["时间"]])
        if business_date is None:
            raise RuntimeError(f"拼多多推广费第 {row_number} 行时间无法解析")
        if start_date is not None and business_date < start_date:
            raise RuntimeError(
                f"拼多多推广费第 {row_number} 行日期早于请求开始日期："
                f"{business_date} < {start_date}"
            )
        if end_date is not None and business_date > end_date:
            raise RuntimeError(
                f"拼多多推广费第 {row_number} 行日期晚于请求结束日期："
                f"{business_date} > {end_date}"
            )
        if values[positions["资金类型"]] != "现金":
            raise RuntimeError(
                f"拼多多推广费第 {row_number} 行资金类型不是现金：{values[positions['资金类型']]}"
            )
        if values[positions["流水类型"]] != "支出":
            raise RuntimeError(
                f"拼多多推广费第 {row_number} 行流水类型不是支出：{values[positions['流水类型']]}"
            )
        source_shop = values[positions["店铺名称"]]
        if source_shop and source_shop != shop:
            raise RuntimeError(
                f"拼多多推广费第 {row_number} 行店铺与 profile 不一致：{source_shop} != {shop}"
            )
        amount = parse_amount(raw_row[positions["交易金额"]])
        if amount is None:
            raise RuntimeError(f"拼多多推广费第 {row_number} 行交易金额为空")
        parsed_rows += 1
        dates.append(business_date)
        total_amount += abs(amount)

    if not parsed_rows:
        raise RuntimeError("拼多多推广费下载文件没有有效现金支出明细")
    return {
        "sheet_name": sheet_name,
        "row_count": parsed_rows,
        "min_date": min(dates).isoformat(),
        "max_date": max(dates).isoformat(),
        "total_amount": total_amount,
    }


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
    """调用项目统一移动重命名脚本，不覆盖已有归档。"""

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
        raise RuntimeError(
            f"move_report.py 归档失败：{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def archive_path_from_log(move_log: str) -> Path:
    for line in move_log.splitlines():
        stripped = line.strip()
        if stripped.startswith("-> "):
            return Path(stripped[3:].strip())
    raise RuntimeError(f"move_report.py 未返回归档路径：{move_log}")


async def close_pages(pages: list["Page"]) -> None:
    seen: set[int] = set()
    for page in reversed(pages):
        identity = id(page)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass


@automation_component("pinduoduo.promotion.workflow", "拼多多推广费 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path | None,
    dest: Path,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="pdd_promotion_fee_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    opened_pages: list["Page"] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            context = browser.contexts[0]
            page, opened_pages = await open_promotion_page(
                context, platform=platform, company=company, shop=shop
            )
            log("页面", f"推广财务流水页已就绪：{page.url}")
            await apply_filters(page, start_date=start_date, end_date=end_date)
            row_count, table_amount = await query_filtered_rows(
                page, start_date=start_date, end_date=end_date
            )
            log("查询", f"现金支出明细 {row_count} 行，页面合计 {table_amount:.2f} 元")

            download_button = await _download_button(page)
            async with page.expect_download(timeout=120_000) as download_info:
                await click_compat(download_button)
            downloaded = await save_download(await download_info.value, actual_work_dir)
            log("下载", f"临时文件={downloaded}")

            summary = await asyncio.to_thread(
                validate_download,
                downloaded,
                shop,
                start_date=start_date,
                end_date=end_date,
            )
            log(
                "验收",
                f"工作表={summary['sheet_name']}，有效行={summary['row_count']}，"
                f"日期范围={summary['min_date']}~{summary['max_date']}，"
                f"现金支出合计={summary['total_amount']:.2f} 元",
            )
            move_log = await asyncio.to_thread(
                move_report,
                downloaded,
                platform=platform,
                company=company,
                shop=shop,
                business_date=(end_date.isoformat() if end_date is not None else summary["max_date"]),
                dest=dest,
            )
            print(move_log)
            archived = archive_path_from_log(move_log)
            archived_summary = await asyncio.to_thread(
                validate_download,
                archived,
                shop,
                start_date=start_date,
                end_date=end_date,
            )
            log(
                "归档",
                f"文件={archived}，大小={archived.stat().st_size} 字节，"
                f"有效行={archived_summary['row_count']}，可读性与表头校验通过",
            )
    finally:
        await close_pages(opened_pages)
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="拼多多推广账户现金支出明细下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--platform", required=True, help="profile note 中的平台中文名")
    parser.add_argument("--company", required=True, help="profile note 中的公司全称")
    parser.add_argument("--shop", required=True, help="profile note 中的店铺名")
    parser.add_argument(
        "--start-date",
        default=None,
        help="自定义推广费开始日期，格式 YYYY-MM-DD（可用 YYYY/MM/DD）",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="自定义推广费结束日期，格式 YYYY-MM-DD（可用 YYYY/MM/DD）",
    )
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None, help="下载临时目录")
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data", help="归档根目录")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if (args.start_date is None) != (args.end_date is None):
        print("--start-date 与 --end-date 必须同时提供", file=sys.stderr)
        return 2

    def parse_cli_date(raw: str, flag: str) -> dt.date:
        try:
            return dt.date.fromisoformat(raw.replace("/", "-"))
        except ValueError:
            raise ValueError(f"{flag} 日期格式必须是 YYYY-MM-DD 或 YYYY/MM/DD：{raw}")

    try:
        start_date = parse_cli_date(args.start_date, "--start-date") if args.start_date else None
        end_date = parse_cli_date(args.end_date, "--end-date") if args.end_date else None
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("--start-date 不能晚于 --end-date")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
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
                start_date,
                end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
