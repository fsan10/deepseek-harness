# -*- coding: utf-8 -*-
"""京东订单明细信息【加密】报表下载。

该模块通过 Cloak Login 提供的 CDP 地址连接已经启动的京东 profile，完成：

* 登录失效时点击京麦登录页的“立即登录”；
* 打开订单导出页，深链异常时从“交易 -> 订单列表 -> 订单导出”进入；
* 新建一次指定日期范围（未指定时为近一个月）、订单状态为“全部”的订单明细导出任务；
* 每 5 秒刷新导出列表，按订单时间范围和任务提交时间选择对应的最新成功任务；
* 先下载外层 ZIP，再获取文件提取码，通过自动化 Challenge 等待自动接收或人工回复；
* 安全提取 ZIP 中唯一的 XLSX，使用 msoffcrypto 解密并校验后归档。

导出任务、下载文件和 Challenge ID 均保存到工作目录。进程中断后会继续已有
任务，不重复点击“新建导出任务”或“获取密码”。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from ..extract_report import repair_member_name
from .automation_challenge import create_challenge, probe_relay, reopen_for_human, wait_answer
from .component_runtime import automation_component, component_event
from .outcomes import NeedsHumanError
from .jd_download_common import (
    acquire_download_lock,
    move_report,
    release_download_lock,
    save_download,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Download, Locator, Page


PLATFORM = "京东"
REPORT_NAME = "订单"
HOME_URL = "https://shop.jd.com/jdm/home"
ORDER_EXPORT_URL = "https://shop.jd.com/jdm/trade/tools/export/ExprotList?exportTaskType=0"
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
JD_PREFIX = "https://shop.jd.com/jdm/"

_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?!\d)")
_CREATED_RE = re.compile(
    r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"
    r"(?:[日 T]|\s+)([01]?\d|2[0-3])[:时]([0-5]?\d)[:分]([0-5]?\d)?"
)
_ORDER_TYPE_RE = re.compile(r"订单(?:明细信息)?")
_FAILURE_RE = re.compile(r"失败|错误|异常|取消|无法生成")
_RATE_LIMIT_RE = re.compile(r"操作过于频繁|重复提交|(?:5|５)\s*分钟|五分钟|稍后再试", re.I)
_MONTH_PRESET_RE = re.compile(r"^\s*近\s*(?:1|一)\s*个?月\s*$")
_ZIP_REPORT_SUFFIXES = {".xlsx", ".xls", ".csv"}


@dataclass
class HistoryTask:
    """一个可见的京东导出历史任务及其右侧操作行。"""

    start_date: str
    end_date: str
    type_text: str
    created_at: datetime | None
    status: str
    source_row: "Locator"
    action_row: "Locator | None"


def _visible(locator: "Locator") -> "Locator":
    return locator.filter(visible=True)


async def click_compat(locator: "Locator") -> None:
    """正常点击失败时用 DOM click 兼容固定层、动画和 AG Grid 右侧钉住列。"""

    try:
        await locator.click(timeout=8_000)
    except Exception:
        await locator.evaluate("element => element.click()")


def _state_path(work_dir: Path) -> Path:
    return work_dir / "jd_order_task.json"


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
    """返回近一个月的保底范围：结束日含当天共 30 个自然日。"""

    end = today or date.today()
    return (end - timedelta(days=29)).isoformat(), end.isoformat()


def resolve_order_range(
    start_date: str | None,
    end_date: str | None,
    *,
    today: date | None = None,
) -> tuple[tuple[str, str], bool]:
    """Resolve an explicit natural-date range or the legacy rolling preset."""

    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date 和 --end-date 必须同时提供")
    if start_date is None and end_date is None:
        return recent_month_range(today=today), True
    try:
        start = date.fromisoformat(start_date or "")
        end = date.fromisoformat(end_date or "")
    except ValueError as exc:
        raise ValueError("订单日期必须是 YYYY-MM-DD") from exc
    if start > end:
        raise ValueError("订单开始日期不能晚于结束日期")
    return (start.isoformat(), end.isoformat()), False


def _date_only(value: str) -> str:
    match = _DATE_RE.search(value or "")
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def _extract_order_range(text: str) -> tuple[str, str]:
    """从“订单时间：开始 - 结束”文本中取两个业务日期。"""

    marker = re.search(r"订单时间\s*[：:]?", text or "")
    if not marker:
        return "", ""
    dates = [_date_only(match.group(0)) for match in _DATE_RE.finditer(text[marker.end():])]
    dates = [item for item in dates if item]
    if len(dates) < 2:
        return "", ""
    return dates[0], dates[1]


def _date_range_matches(text: str, start_date: str, end_date: str) -> bool:
    return _extract_order_range(text) == (start_date, end_date)


def _task_range_matches(
    text: str,
    start_date: str,
    end_date: str,
    *,
    allow_rolling_drift: bool = True,
) -> bool:
    """Match an explicit range and JD's rolling ``近1个月`` display.

    The live JD picker uses the previous 30*24 hours, while the fallback
    inputs use 30 natural days including today.  Around midday this makes the
    displayed start date one day earlier.  Keep the end date exact and allow
    only that one-day start-date drift, so a task from another business day is
    never selected by accident.
    """

    actual_start, actual_end = _extract_order_range(text)
    if (actual_start, actual_end) == (start_date, end_date):
        return True
    if not allow_rolling_drift:
        return False
    try:
        expected_start = date.fromisoformat(start_date)
    except ValueError:
        return False
    return actual_end == end_date and actual_start == (expected_start - timedelta(days=1)).isoformat()


def _parse_created(text: str) -> datetime | None:
    values: list[datetime] = []
    for match in _CREATED_RE.finditer(text or ""):
        year, month, day, hour, minute, second = match.groups()
        values.append(
            datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second or 0)
            )
        )
    return max(values) if values else None


async def _body_text(page: "Page") -> str:
    with suppress(Exception):
        return (await page.locator("body").inner_text(timeout=3_000)).strip()
    return ""


async def _wait_home_shell(page: "Page") -> None:
    """等待京麦首页应用壳完成，而不是只看 URL 已经切换。"""

    nav = page.get_by_role("link", name="订单列表", exact=True).last
    try:
        await nav.wait_for(state="visible", timeout=45_000)
        return
    except PlaywrightTimeout as exc:
        body = await _body_text(page)
        # The current shell may render the transaction submenu as collapsed
        # text-free controls even though the authenticated home app is ready.
        # The deep-link export page does not require the submenu to be open.
        shell_markers = ("交易", "财务", "MOCK饮品旗舰店")
        if "订单列表" not in body and not all(marker in body for marker in shell_markers):
            raise RuntimeError("京麦首页已打开但左侧导航尚未加载完成") from exc


async def _visible_short_text(page: "Page", pattern: re.Pattern[str], *, limit: int = 20) -> bool:
    """只扫描短的可见提示，不把帮助文案或历史正文误判为频控。"""

    nodes = _visible(
        page.locator(
            '[role="alert"], [aria-live], [class*="toast" i], '
            '[class*="message" i], [class*="notice" i], [class*="notification" i]'
        )
    )
    with suppress(Exception):
        for index in range(min(await nodes.count(), limit)):
            with suppress(Exception):
                text = (await nodes.nth(index).inner_text(timeout=500)).strip()
                if text and len(text) <= 300 and pattern.search(text):
                    print(f"[JD] 页面提示：{text[:160]}")
                    return True
    return False


@automation_component("jd.ensure_login", "京东 · 检查登录态", category="report")
async def ensure_login(page: "Page") -> None:
    """处理京麦登录失效；账号密码由 profile 保存，只点击立即登录。"""

    if page.url.startswith(JD_PREFIX):
        await _wait_home_shell(page)
        return
    if not page.url or page.url == "about:blank":
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    if page.url.startswith(JD_PREFIX):
        await _wait_home_shell(page)
        return
    if "passport.shop.jd.com" not in page.url:
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)

    login = page.get_by_role("button", name="立即登录", exact=True).last
    try:
        await login.wait_for(state="visible", timeout=15_000)
    except PlaywrightTimeout:
        login = page.get_by_text("立即登录", exact=True).last
        await login.wait_for(state="visible", timeout=15_000)
    await click_compat(login)

    deadline = asyncio.get_running_loop().time() + 45
    while asyncio.get_running_loop().time() < deadline:
        if page.url.startswith(JD_PREFIX):
            await _wait_home_shell(page)
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"点击京麦“立即登录”后未进入商家后台，当前页面：{page.url}")


async def new_authenticated_page(context: "BrowserContext") -> "Page":
    page = await context.new_page()
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await ensure_login(page)
    return page


async def _export_page_ready(page: "Page") -> bool:
    if not page.url.startswith(JD_PREFIX):
        return False
    button = page.get_by_role("button", name="新建导出任务", exact=True).last
    if not await button.count() or not await button.is_visible():
        return False
    # The button can render several polling ticks before the AG Grid rows.
    # Wait for rows (or an explicit empty-state marker) so a matching
    # historical task is not missed and a duplicate export is not created
    # during that short loading window.
    for selector in (
        ".ag-center-cols-container .ag-row.ag-row-level-0",
        ".ag-row.ag-row-level-0",
        "tr.jd-table__row",
        "table.jd-table tbody tr",
        ".ag-overlay-no-rows-center",
    ):
        candidate = page.locator(selector).last
        if await candidate.count() and await candidate.is_visible():
            return True
    return False


async def _page_from_new_window(context: "BrowserContext", before: set["Page"]) -> "Page | None":
    for _ in range(60):
        candidate = next(
            (
                page
                for page in context.pages
                if not page.is_closed() and page not in before and page.url != "about:blank"
            ),
            None,
        )
        if candidate is not None:
            return candidate
        await asyncio.sleep(0.25)
    return None


async def open_order_export_via_navigation(page: "Page") -> "Page":
    """深链会话异常时，从左侧交易菜单进入订单导出。"""

    context = page.context
    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await ensure_login(page)

    order_link = _visible(page.get_by_role("link", name="订单列表", exact=True)).last
    if not await order_link.count():
        order_link = _visible(page.get_by_text("订单列表", exact=True)).last
    if not await order_link.count():
        trade = _visible(page.get_by_text("交易", exact=True)).last
        if await trade.count():
            await click_compat(trade)
            order_link = _visible(page.get_by_role("link", name="订单列表", exact=True)).last
            if not await order_link.count():
                order_link = _visible(page.get_by_text("订单列表", exact=True)).last
    if not await order_link.count():
        raise RuntimeError("京麦左侧导航未找到“交易”下的“订单列表”")

    before = set(context.pages)
    if "/trade/tools/export/ExprotList" not in page.url:
        await click_compat(order_link)
    opened = await _page_from_new_window(context, before)
    if opened is not None:
        page = opened
    with suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=30_000)

    order_page_deadline = asyncio.get_running_loop().time() + 20
    while asyncio.get_running_loop().time() < order_page_deadline:
        if "/trade/tools/export/ExprotList" in page.url or await _visible(page.get_by_text("订单导出", exact=True)).count():
            break
        await asyncio.sleep(0.25)

    if "/trade/tools/export/ExprotList" not in page.url:
        export_link = _visible(page.get_by_role("link", name="订单导出", exact=True)).last
        if not await export_link.count():
            export_link = _visible(page.get_by_text("订单导出", exact=True)).last
        if not await export_link.count():
            raise RuntimeError("京东订单列表页未找到“订单导出”入口")
        before = set(context.pages)
        await click_compat(export_link)
        opened = await _page_from_new_window(context, before)
        if opened is not None:
            page = opened

    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        if await _export_page_ready(page):
            return page
        await asyncio.sleep(0.25)
    raise RuntimeError(f"通过京麦左侧导航未进入订单导出页，当前页面：{page.url}")


@automation_component("jd.order.open_export", "京东订单 · 打开导出页", category="report")
async def open_order_export_page(page: "Page") -> "Page":
    """优先深链，出现会话异常或页面不完整时使用左侧导航备用方案。"""

    try:
        await page.goto(ORDER_EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.locator("body").wait_for(state="visible", timeout=30_000)
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            if await _export_page_ready(page):
                return page
            await asyncio.sleep(0.25)
    except Exception as exc:
        print(f"[JD] 订单导出深链不可用，切换左侧导航：{exc}")
    return await open_order_export_via_navigation(page)


async def _new_task_dialog(page: "Page") -> "Locator":
    # Element Plus keeps the dialog in the DOM while it is closing.  Resolve the
    # last matching dialog first and let wait_for(state="visible") choose the
    # active instance; filtering the parent locator by visibility can make a
    # child locator miss the active form in a CDP-attached page.
    dialog = page.locator('.el-dialog.add-new-dialog[role="dialog"], .el-dialog.add-new-dialog').last
    await dialog.wait_for(state="visible", timeout=15_000)
    return dialog


async def _range_inputs(dialog: "Locator") -> tuple["Locator", "Locator"]:
    start = dialog.locator(
        'input.jd-range-input[placeholder="开始时间"], '
        'input.el-range-input[placeholder="开始时间"], input[placeholder="开始时间"]'
    ).first
    end = dialog.locator(
        'input.jd-range-input[placeholder="结束时间"], '
        'input.el-range-input[placeholder="结束时间"], input[placeholder="结束时间"]'
    ).first
    await start.wait_for(state="visible", timeout=15_000)
    await end.wait_for(state="visible", timeout=15_000)
    return start, end


async def _force_fill_readonly(locator: "Locator", value: str) -> None:
    try:
        await locator.fill(value, timeout=3_000)
    except Exception:
        await locator.evaluate(
            """(element, value) => {
                element.removeAttribute('readonly');
                element.value = value;
                element.dispatchEvent(new Event('input', {bubbles: true}));
                element.dispatchEvent(new Event('change', {bubbles: true}));
            }""",
            value,
        )


async def _input_values(dialog: "Locator") -> tuple[str, str]:
    start, end = await _range_inputs(dialog)
    return await start.input_value(), await end.input_value()


async def _visible_picker_confirm(page: "Page") -> "Locator | None":
    picker = page.locator(
        ".el-picker-panel, .el-date-picker, .el-date-range-picker, "
        ".jd-picker-panel, [class*='picker-panel' i]"
    ).last
    if not await picker.count():
        return None
    confirm = picker.get_by_role("button", name="确定", exact=True).last
    with suppress(Exception):
        await confirm.wait_for(state="visible", timeout=2_000)
    return confirm if await confirm.count() else None


@automation_component("report.date_range.set", "设置业务日期范围", category="report")
async def choose_recent_month(
    dialog: "Locator",
    page: "Page",
    start_date: str,
    end_date: str,
    *,
    use_preset: bool = True,
) -> tuple[str, str]:
    """优先点击页面快捷项；失败时按京东行为分别输入开始、结束时间。"""

    start, end = await _range_inputs(dialog)
    try:
        await start.click(timeout=8_000)
    except Exception:
        with suppress(Exception):
            await start.locator("xpath=ancestor::*[contains(@class,'range-editor')][1]").click()

    if use_preset:
        preset = page.locator(
            ".jd-picker-panel__shortcut, .el-picker-panel__shortcut, "
            "button"
        ).filter(has_text=_MONTH_PRESET_RE).last
        try:
            await preset.wait_for(state="visible", timeout=8_000)
            await click_compat(preset)
            confirm = await _visible_picker_confirm(page)
            if confirm is not None:
                await click_compat(confirm)
            for _ in range(40):
                values = await _input_values(dialog)
                if values[0] and values[1]:
                    print(f"[JD] 已选择“近1个月”：{values[0]} ~ {values[1]}")
                    return values
                await asyncio.sleep(0.15)
        except Exception:
            with suppress(Exception):
                await page.keyboard.press("Escape")

    # 京东两个输入框不会像快手那样在开始时间 Enter 后自动跳到结束框，
    # 所以显式重新点击结束框，再填入完整的日期时间。
    await _force_fill_readonly(start, f"{start_date} 00:00:00")
    await start.press("Enter")
    await end.click(timeout=8_000)
    await _force_fill_readonly(end, f"{end_date} 23:59:59")
    await end.press("Enter")
    actual = await _input_values(dialog)
    if _date_only(actual[0]) != start_date or _date_only(actual[1]) != end_date:
        raise RuntimeError(f"京东订单时间范围选择失败：期望 {start_date} ~ {end_date}，实际 {actual!r}")
    print(f"[JD] 已使用日期输入保底：{actual[0]} ~ {actual[1]}")
    return actual


async def ensure_order_type(dialog: "Locator", page: "Page") -> None:
    selector = _visible(dialog.locator('input.el-cascader input, .el-cascader input[placeholder="请选择"]')).first
    if not await selector.count():
        selector = _visible(dialog.locator('input[placeholder="请选择"]')).first
    if not await selector.count():
        raise RuntimeError("京东订单导出弹窗未找到导出类型")
    current = (await selector.input_value()).strip()
    if "订单" in current and ("明细" in current or "加密" in current):
        return
    await click_compat(selector)
    option = _visible(page.get_by_text("订单明细信息【加密】", exact=True)).last
    if not await option.count():
        option = _visible(page.get_by_text(re.compile(r"订单.*明细信息.*加密"), exact=False)).last
    if not await option.count():
        raise RuntimeError("京东导出类型下拉框未找到“订单明细信息【加密】”")
    await click_compat(option)
    current = (await selector.input_value()).strip()
    if "订单" not in current:
        raise RuntimeError(f"京东订单导出类型选择失败：{current!r}")


async def ensure_all_order_status(dialog: "Locator") -> None:
    labels = dialog.locator("label.el-checkbox")
    target = None
    for index in range(await labels.count()):
        label = labels.nth(index)
        text = re.sub(r"\s+", "", (await label.inner_text(timeout=1_000)).strip())
        if text.startswith("全部"):
            target = label
            break
    if target is None:
        raise RuntimeError("京东订单导出弹窗未找到订单状态“全部”")
    checkbox = target.locator('input[type="checkbox"]').first
    checked = await checkbox.is_checked()
    if not checked:
        await click_compat(target)
    if not await checkbox.is_checked():
        aria = await target.locator("[aria-checked]").first.get_attribute("aria-checked")
        if aria not in {"true", "1"}:
            raise RuntimeError("京东订单状态“全部”勾选失败")


async def _history_center_rows(page: "Page") -> list["Locator"]:
    rows = _visible(page.locator(".ag-center-cols-container .ag-row.ag-row-level-0"))
    if await rows.count():
        return [rows.nth(index) for index in range(await rows.count())]
    rows = _visible(page.locator("tr.jd-table__row"))
    if await rows.count():
        return [rows.nth(index) for index in range(await rows.count())]
    rows = _visible(page.locator(".ag-row.ag-row-level-0"))
    return [
        rows.nth(index)
        for index in range(await rows.count())
        if await rows.nth(index).locator('[col-id="taskTypeName"]').count()
    ]


async def _cell_text(row: "Locator", col_id: str) -> str:
    cell = row.locator(f'[col-id="{col_id}"]').first
    if await cell.count():
        with suppress(Exception):
            return (await cell.inner_text(timeout=1_000)).strip()
    return ""


async def _action_row(page: "Page", source_row: "Locator") -> "Locator | None":
    row_id = await source_row.get_attribute("row-id")
    if row_id is not None:
        pinned = _visible(page.locator(
            f'.ag-pinned-right-cols-container .ag-row.ag-row-level-0[row-id="{row_id}"]'
        )).first
        if await pinned.count():
            return pinned
    if await source_row.locator("button").count():
        return source_row
    return None


async def history_tasks(page: "Page") -> list[HistoryTask]:
    result: list[HistoryTask] = []
    for row in await _history_center_rows(page):
        type_text = await _cell_text(row, "taskTypeName")
        task_data = await _cell_text(row, "taskData")
        created_text = await _cell_text(row, "createDate")
        status = await _cell_text(row, "taskStatus")
        if not type_text:
            full_text = (await row.inner_text(timeout=1_000)).strip()
            type_text = full_text
            task_data = full_text
        start_date, end_date = _extract_order_range(task_data)
        if not start_date or not end_date:
            start_date, end_date = _extract_order_range((await row.inner_text(timeout=1_000)).strip())
        if not created_text:
            created_text = (await row.inner_text(timeout=1_000)).strip()
        action = await _action_row(page, row)
        result.append(
            HistoryTask(
                start_date=start_date,
                end_date=end_date,
                type_text=type_text,
                created_at=_parse_created(created_text),
                status=status,
                source_row=row,
                action_row=action,
            )
        )
    return result


def _task_sort_key(task: HistoryTask) -> datetime:
    return task.created_at or datetime.min


async def find_matching_task(
    page: "Page",
    start_date: str,
    end_date: str,
    *,
    require_download: bool = False,
    created_after: datetime | None = None,
    allow_rolling_drift: bool = True,
) -> HistoryTask | None:
    candidates: list[HistoryTask] = []
    for task in await history_tasks(page):
        if not _ORDER_TYPE_RE.search(task.type_text):
            continue
        if not _task_range_matches(
            f"订单时间：{task.start_date} - {task.end_date}",
            start_date,
            end_date,
            allow_rolling_drift=allow_rolling_drift,
        ):
            continue
        if created_after is not None:
            if task.created_at is None or task.created_at < created_after:
                continue
        if require_download:
            if "成功" not in task.status or task.action_row is None:
                continue
            button = _visible(task.action_row.get_by_role("button", name="下载文件", exact=True)).first
            password = _visible(task.action_row.get_by_role("button", name="获取密码", exact=True)).first
            if not await button.count() or not await password.count():
                continue
        candidates.append(task)
    candidates.sort(key=_task_sort_key, reverse=True)
    return candidates[0] if candidates else None


async def _wait_task_inserted(
    page: "Page",
    start_date: str,
    end_date: str,
    submitted_at: datetime,
    *,
    allow_rolling_drift: bool,
) -> HistoryTask | None:
    deadline = asyncio.get_running_loop().time() + 60
    latest: HistoryTask | None = None
    while asyncio.get_running_loop().time() < deadline:
        latest = await find_matching_task(
            page,
            start_date,
            end_date,
            allow_rolling_drift=allow_rolling_drift,
        )
        if latest is not None:
            if latest.created_at is not None and latest.created_at >= submitted_at - timedelta(minutes=5):
                return latest
        await asyncio.sleep(0.5)
    return latest


@automation_component("jd.order.create_export", "京东订单 · 创建导出任务", category="report")
async def create_export_once(
    page: "Page",
    *,
    start_date: str,
    end_date: str,
    state_path: Path,
    state: dict[str, Any],
    use_recent_preset: bool,
) -> HistoryTask:
    new_task = _visible(page.get_by_role("button", name="新建导出任务", exact=True)).last
    await new_task.wait_for(state="visible", timeout=15_000)
    await click_compat(new_task)
    dialog = await _new_task_dialog(page)
    await ensure_order_type(dialog, page)
    await choose_recent_month(
        dialog,
        page,
        start_date,
        end_date,
        use_preset=use_recent_preset,
    )
    await ensure_all_order_status(dialog)

    confirm = _visible(dialog.get_by_role("button", name=re.compile(r"^\s*确\s*认\s*$"))).last
    if not await confirm.count():
        confirm = _visible(dialog.locator("button").filter(has_text=re.compile(r"^\s*确\s*认\s*$"))).last
    if not await confirm.count():
        raise RuntimeError("京东订单导出弹窗未找到“确认”按钮")

    submitted_at = datetime.now()
    state["stage"] = "SUBMITTING"
    state["submitted_at"] = submitted_at.isoformat(timespec="seconds")
    _write_state(state_path, state)
    await click_compat(confirm)
    with suppress(Exception):
        await dialog.wait_for(state="hidden", timeout=15_000)

    task = await _wait_task_inserted(
        page,
        start_date,
        end_date,
        submitted_at,
        allow_rolling_drift=use_recent_preset,
    )
    if task is None or task.created_at is None or task.created_at < submitted_at - timedelta(minutes=5):
        if await _visible_short_text(page, _RATE_LIMIT_RE):
            raise RuntimeError("京东订单导出返回频控/重复提交提示，但未找到对应日期任务；保留 SUBMITTING 状态")
        raise RuntimeError("京东点击确认后未识别到新的订单导出任务；保留 SUBMITTING 状态")
    state["stage"] = "EXPORT_CREATED"
    state["creation_proof"] = "submitted"
    state["task_created_at"] = task.created_at.isoformat(sep=" ") if task.created_at else ""
    _write_state(state_path, state)
    print(f"[JD] 订单导出任务已创建：{start_date} ~ {end_date}")
    return task


async def ensure_export_created(
    page: "Page",
    *,
    start_date: str,
    end_date: str,
    state_path: Path,
    state: dict[str, Any],
    allow_rolling_drift: bool,
    use_recent_preset: bool,
) -> HistoryTask:
    if state.get("stage") == "SUBMITTING":
        submitted_at = _state_datetime(str(state.get("submitted_at") or ""))
        if submitted_at is not None:
            existing = await find_matching_task(
                page,
                start_date,
                end_date,
                created_after=submitted_at - timedelta(minutes=5),
                allow_rolling_drift=allow_rolling_drift,
            )
            if existing is not None:
                state["stage"] = "EXPORT_CREATED"
                state["creation_proof"] = "submitted"
                state["task_created_at"] = (
                    existing.created_at.isoformat(sep=" ") if existing.created_at else ""
                )
                _write_state(state_path, state)
                print(f"[JD] 已核对确认后的订单任务，恢复：{start_date} ~ {end_date}")
                return existing
        raise RuntimeError("上次确认后的京东订单任务尚未在列表中出现；保留 SUBMITTING 状态，未重复创建")
    existing = await find_matching_task(
        page,
        start_date,
        end_date,
        allow_rolling_drift=allow_rolling_drift,
    )
    if existing is not None:
        state["stage"] = "EXPORT_CREATED"
        state["creation_proof"] = "history_reused"
        state["task_created_at"] = existing.created_at.isoformat(sep=" ") if existing.created_at else ""
        _write_state(state_path, state)
        print(f"[JD] 已发现相同日期范围的历史订单任务，复用：{start_date} ~ {end_date}")
        return existing
    return await create_export_once(
        page,
        start_date=start_date,
        end_date=end_date,
        state_path=state_path,
        state=state,
        use_recent_preset=use_recent_preset,
    )


def _state_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@automation_component("report.wait_export_ready", "等待导出任务就绪", category="report")
async def wait_latest_report(
    page: "Page",
    *,
    start_date: str,
    end_date: str,
    created_after: datetime | None = None,
    allow_rolling_drift: bool = True,
    timeout_seconds: float = 900.0,
) -> HistoryTask:
    """每 5 秒刷新一次，直到匹配任务显示成功且有两个操作按钮。"""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_status = ""
    while asyncio.get_running_loop().time() < deadline:
        task = await find_matching_task(
            page,
            start_date,
            end_date,
            require_download=True,
            created_after=created_after,
            allow_rolling_drift=allow_rolling_drift,
        )
        if task is not None:
            print(f"[JD] 已找到可下载订单任务，提交时间：{task.created_at or '未知'}")
            return task
        for candidate in await history_tasks(page):
            if _task_range_matches(
                f"订单时间：{candidate.start_date} - {candidate.end_date}",
                start_date,
                end_date,
                allow_rolling_drift=allow_rolling_drift,
            ):
                last_status = candidate.status
                if _FAILURE_RE.search(candidate.status):
                    raise RuntimeError(f"京东订单报表生成失败：{candidate.status}")
        await asyncio.sleep(5)
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            continue
        if not await _export_page_ready(page):
            page = await open_order_export_page(page)
    raise TimeoutError(f"等待京东订单报表成功并可下载超时，最后状态：{last_status or '未找到匹配任务'}")


@automation_component("file.download", "下载报表文件", category="file")
async def download_task_file(
    page: "Page",
    task: HistoryTask,
    *,
    work_dir: Path,
    state_path: Path,
    state: dict[str, Any],
) -> Path:
    if task.action_row is None:
        raise RuntimeError("京东订单成功任务未找到操作列")
    button = _visible(task.action_row.get_by_role("button", name="下载文件", exact=True)).first
    if not await button.count():
        raise RuntimeError("京东订单成功任务未找到“下载文件”按钮")
    try:
        async with page.expect_download(timeout=120_000) as info:
            await click_compat(button)
        downloaded = await save_download(await info.value, work_dir, "jd_order.zip")
    except PlaywrightTimeout as exc:
        raise TimeoutError("京东订单 ZIP 下载超时") from exc
    if not zipfile.is_zipfile(downloaded):
        raise RuntimeError(f"京东订单下载文件不是有效 ZIP：{downloaded}")
    state["stage"] = "ZIP_DOWNLOADED"
    state["download_path"] = str(downloaded)
    _write_state(state_path, state)
    print(f"[JD] 订单 ZIP 已下载：{downloaded}")
    return downloaded


@automation_component("human.verification.wait", "等待飞书验证码 / 密码", category="human")
async def _request_stateful_answer(
    *,
    challenge_key: str,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
    page_url: str,
    state_path: Path,
    state: dict[str, Any],
    before_new_challenge=None,
    refresh_before_create: bool = False,
) -> str:
    """复用有效 Challenge；新请求登记完成后才让平台下发密码。"""

    existing_id = str(state.get(challenge_key) or "").strip()
    if existing_id:
        component_event("waiting_human", "复用已有 Challenge，等待自动接收或人工回复", detail={"challenge_id": existing_id})
        try:
            answer = await wait_answer(challenge_id=existing_id)
        except RuntimeError as exc:
            if "过期" not in str(exc) and "取消" not in str(exc):
                raise
            state.pop(challenge_key, None)
            _write_state(state_path, state)
            refresh_before_create = True
        else:
            state.pop(challenge_key, None)
            state[challenge_key + "_last_answered"] = existing_id
            _write_state(state_path, state)
            component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
            return answer

    await asyncio.to_thread(probe_relay)
    reference = re.search(r"(taskid-[0-9]+)-", Path(str(state.get("download_path") or "")).name)
    challenge = await create_challenge(
        challenge_type="archive_password",
        platform=platform,
        company=company,
        shop=shop,
        purpose=purpose,
        page_url=page_url,
        business_reference=reference.group(1) if reference else "",
    )
    challenge_id = str(challenge.get("challenge_id") or "").strip()
    if not challenge_id:
        raise RuntimeError("自动化验证码服务未返回 challenge_id")
    state[challenge_key] = challenge_id
    _write_state(state_path, state)
    component_event("waiting_human", "Challenge 已创建，等待自动接收或人工回复", detail={"challenge_id": challenge_id, "challenge_type": challenge_type if "challenge_type" in locals() else "archive_password"})
    try:
        if refresh_before_create and before_new_challenge:
            await before_new_challenge()
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


async def request_file_password(
    page: "Page",
    task: HistoryTask,
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> str:
    """点击“获取密码”一次，再等待 Feishu/自动化服务返回提取码。"""

    if task.action_row is None:
        raise RuntimeError("京东订单成功任务未找到操作列")
    send = _visible(
        task.action_row.get_by_role(
            "button", name=re.compile(r"^(?:获取密码|重新获取密码|重新发送(?:密码)?)$")
        )
    ).first
    if not await send.count():
        raise RuntimeError("京东订单成功任务未找到可用的获取或重新发送密码按钮")

    async def resend() -> None:
        # Never click the platform button without confirming relay readiness.
        await asyncio.to_thread(probe_relay)
        await click_compat(send)
        state["password_requested"] = True
        _write_state(state_path, state)
        print("[JD] 已向平台重新请求文件提取码；等待自动接收或人工回复")

    challenge_id = str(state.get("file_password_challenge_id") or "").strip()
    requested = bool(state.get("password_requested"))
    if requested and challenge_id:
        print("[JD] 复用尚未过期的文件提取码 Challenge；过期后自动触发重新发送")

    return await _request_stateful_answer(
        challenge_key="file_password_challenge_id",
        platform=platform,
        company=company,
        shop=shop,
        purpose=f"京东订单报表文件提取码（{task.start_date} ~ {task.end_date}）",
        page_url=page.url,
        state_path=state_path,
        state=state,
        before_new_challenge=resend,
        refresh_before_create=not requested or not challenge_id,
    )


def _safe_member_basename(info: zipfile.ZipInfo) -> str:
    repaired = repair_member_name(info.filename, info.flag_bits, "gbk")
    path = PurePosixPath(repaired.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"京东订单 ZIP 中存在不安全路径：{info.filename!r}")
    basename = path.name
    if not basename or basename in {".", ".."}:
        raise RuntimeError(f"京东订单 ZIP 成员名称不安全：{info.filename!r}")
    return basename


def extract_order_report(archive: Path, destination: Path) -> Path:
    """安全提取外层 ZIP 中唯一的订单报表文件。"""

    if not archive.is_file():
        raise FileNotFoundError(f"京东订单 ZIP 不存在：{archive}")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        files = [info for info in bundle.infolist() if not info.is_dir()]
        if any(info.flag_bits & 0x1 for info in files):
            raise RuntimeError("京东订单外层 ZIP 已加密，当前流程只支持 ZIP 内加密 XLSX")
        candidates = [
            (info, _safe_member_basename(info))
            for info in files
            if _safe_member_basename(info).lower().endswith(tuple(_ZIP_REPORT_SUFFIXES))
        ]
        if len(candidates) != 1:
            names = "、".join(name for _, name in candidates)
            raise RuntimeError(f"京东订单 ZIP 中未找到唯一报表文件：{names or '无 XLSX/CSV'}")
        info, basename = candidates[0]
        target = destination / basename
        with bundle.open(info) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"京东订单 ZIP 提取结果为空：{target}")
    return target


def decrypt_xlsx(source: Path, password: str, destination: Path) -> Path:
    """使用 msoffcrypto 解密内层 XLSX；未加密工作簿直接复制。"""

    if source.suffix.lower() != ".xlsx":
        raise RuntimeError(f"京东订单报表不是 XLSX：{source.name}")
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
        if "encrypted" not in locals() or encrypted:
            raise ValueError("京东订单文件提取码错误") from exc
        raise RuntimeError(f"京东订单 XLSX 解密失败：{exc}") from exc
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError("京东订单解密后的 XLSX 文件为空")
    return destination


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_xlsx(path: Path) -> None:
    try:
        from openpyxl import load_workbook
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 XLSX 校验依赖 openpyxl") from exc
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            if not workbook.sheetnames:
                raise RuntimeError("京东订单 XLSX 没有工作表")
        finally:
            workbook.close()
    except Exception as exc:
        raise RuntimeError(f"京东订单 XLSX 读取校验失败：{exc}") from exc


@automation_component("file.archive.extract", "解压 / 解密归档", category="file")
async def process_archive(
    page: "Page",
    archive: Path,
    password: str,
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
    task: HistoryTask,
    business_date: str,
    dest: Path,
) -> None:
    extraction_dir = archive.parent / "extracted"
    saved_extracted = str(state.get("extracted_path") or "").strip()
    extracted = Path(saved_extracted) if saved_extracted else extraction_dir / "订单明细信息.xlsx"
    if not extracted.is_file() or extracted.stat().st_size == 0:
        state["stage"] = "EXTRACTING"
        _write_state(state_path, state)
        extracted = await asyncio.to_thread(extract_order_report, archive, extraction_dir)
        state["extracted_path"] = str(extracted)
        _write_state(state_path, state)

    target = extracted.with_name(f"{extracted.stem}_decrypted.xlsx")
    for attempt in range(3):
        state["stage"] = "DECRYPTING"
        _write_state(state_path, state)
        with suppress(OSError):
            target.unlink(missing_ok=True)
        try:
            await asyncio.to_thread(decrypt_xlsx, extracted, password, target)
            await asyncio.to_thread(validate_xlsx, target)
            break
        except ValueError:
            if attempt >= 2:
                with suppress(OSError):
                    target.unlink(missing_ok=True)
                raise NeedsHumanError("连续三次京东订单文件提取码错误，保留 ZIP 供人工恢复")
            print("[JD] 文件提取码输入错误，正在申请重新输入；不重复下载订单 ZIP")
            await reopen_for_human(state, "file_password_challenge_id")
            state["stage"] = "PASSWORD_REQUIRED"
            _write_state(state_path, state)
            password = await request_file_password(
                page, task, platform=platform, company=company, shop=shop,
                state_path=state_path, state=state,
            )
    else:
        raise RuntimeError("京东订单 XLSX 解密失败")

    move_log = await asyncio.to_thread(
        move_report, target, platform, company, shop, REPORT_NAME, business_date, dest
    )
    print(move_log)
    state["stage"] = "COMPLETED"
    state["report_path"] = str(target)
    _write_state(state_path, state)
    with suppress(OSError):
        archive.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        extracted.unlink(missing_ok=True)
    with suppress(OSError):
        extraction_dir.rmdir()
        state_path.unlink(missing_ok=True)
    print("[JD] 订单 ZIP 解密、校验、归档完成")


@automation_component("jd.order.workflow", "京东订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    business_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    (start_date, end_date), use_recent_preset = resolve_order_range(start_date, end_date)
    business_date = business_date or end_date
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(work_dir)
    state = _read_state(state_path)
    if (
        state.get("start_date") != start_date
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

    session_lock = await asyncio.to_thread(acquire_download_lock)
    page: "Page | None" = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器没有可用上下文")
            context = browser.contexts[0]
            page = await new_authenticated_page(context)
            page = await open_order_export_page(page)

            if state.get("stage") in {"EXPORT_NOT_CREATED", "SUBMITTING"}:
                await ensure_export_created(
                    page,
                    start_date=start_date,
                    end_date=end_date,
                    state_path=state_path,
                    state=state,
                    allow_rolling_drift=use_recent_preset,
                    use_recent_preset=use_recent_preset,
                )

            created_after = None
            if state.get("creation_proof") == "submitted":
                submitted = _state_datetime(str(state.get("submitted_at") or ""))
                if submitted is not None:
                    created_after = submitted - timedelta(minutes=5)
            task = await wait_latest_report(
                page,
                start_date=start_date,
                end_date=end_date,
                created_after=created_after,
                allow_rolling_drift=use_recent_preset,
            )

            downloaded_value = str(state.get("download_path") or "").strip()
            downloaded = Path(downloaded_value) if downloaded_value else None
            if downloaded is None or not downloaded.is_file() or downloaded.stat().st_size == 0:
                downloaded = await download_task_file(
                    page, task, work_dir=work_dir, state_path=state_path, state=state
                )
            elif not zipfile.is_zipfile(downloaded):
                raise RuntimeError(f"状态中的京东订单下载文件不是有效 ZIP：{downloaded}")

            password = await request_file_password(
                page,
                task,
                platform=platform,
                company=company,
                shop=shop,
                state_path=state_path,
                state=state,
            )
            await process_archive(
                page,
                downloaded,
                password,
                platform=platform,
                company=company,
                shop=shop,
                state_path=state_path,
                state=state,
                task=task,
                business_date=business_date,
                dest=dest,
            )
    finally:
        if page is not None and not page.is_closed():
            with suppress(Exception):
                await page.close()
        await asyncio.to_thread(release_download_lock, session_lock)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="京东订单加密标准报表下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--platform", default=PLATFORM)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument(
        "--work-dir",
        default=None,
        help="可恢复状态、ZIP 和解密工作目录；默认 data\\.automation_cache\\jd_order\\<shop>",
    )
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="归档根目录")
    parser.add_argument("--business-date", default=None, help="归档日期前缀，默认查询结束日期")
    parser.add_argument("--start-date", default=None, help="自定义订单开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义订单结束日期 YYYY-MM-DD")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    work_dir = (
        Path(args.work_dir)
        if args.work_dir
        else Path(args.dest) / ".automation_cache" / "jd_order" / args.shop
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
                args.start_date,
                args.end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 2 if getattr(exc, 'requires_human', False) else 1


if __name__ == "__main__":
    sys.exit(main())
