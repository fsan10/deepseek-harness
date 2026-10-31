# -*- coding: utf-8 -*-
"""下载拼多多昨天的结算账单，解压 CSV 并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import csv
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Download, Page

from ..extract_report import extract_selected_report, repair_member_name, unique_path
from .report_validation import validate_report_columns

MMS_HOME_URL = "https://mms.pinduoduo.com/home"
RECONCILIATION_CENTER_LINK = 'a[href="/cashier/finance/payment-bills"]'
EXPORT_HISTORY_URL = (
    "https://cashier.pinduoduo.com/main/bills/export-history"
    "?tab=4001&__app_code=113"
)
REPORT_NAME = "结算"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
REQUIRED_COLUMNS = (
    "商户订单号",
    "发生时间",
    "收入金额（+元）",
    "支出金额（-元）",
    "账务类型",
    "备注",
    "业务描述",
)


def default_business_date() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def expected_range(start_date: str, end_date: str | None = None) -> str:
    end_date = end_date or start_date
    return f"{start_date} 00:00:00 ~ {end_date} 23:59:59"


def resolve_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    if start_date is None and end_date is None:
        business_date = default_business_date()
        return business_date, business_date
    if not start_date or not end_date:
        raise ValueError("--start-date 与 --end-date 必须同时提供")
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if start > end:
        raise ValueError("--start-date 不能晚于--end-date")
    return start.isoformat(), end.isoformat()


@automation_component("pinduoduo.session.ensure_login", "拼多多 · 检查登录态", category="browser")
def ensure_logged_in(page: "Page") -> None:
    if not page.url.startswith("https://cashier.pinduoduo.com/"):
        raise RuntimeError(f"拼多多 profile 未登录对账中心，当前页面：{page.url}")


@automation_component("pinduoduo.settlement.open", "拼多多结算 · 打开对账中心", category="report")
async def open_reconciliation_center(context) -> tuple["Page", bool]:
    """复用现有拼多多 tab 导航到对账中心，避免重复创建页面。"""

    async def close_home_modal(page: "Page") -> None:
        """关闭首页主动弹出的运营弹层，避免遮挡侧边导航。"""
        close_button = page.locator('div[class*="newCloseBtn"]').first
        try:
            await close_button.wait_for(state="visible", timeout=2_000)
        except Exception:
            close_button = page.locator(
                'div[data-testid="beast-core-modal"]:visible '
                '[data-testid="beast-core-modal-icon-close"]'
            ).last
            try:
                await close_button.wait_for(state="visible", timeout=2_000)
            except Exception:
                return
        await close_button.evaluate(
            """element => {
                if (typeof element.click === "function") element.click();
                else element.dispatchEvent(new MouseEvent("click", {
                    bubbles: true, cancelable: true, view: window
                }));
            }"""
        )

    picker = 'input[data-testid="beast-core-rangePicker-htmlInput"]'
    # 如果当前 tab 已经在对账中心，直接继续使用它；尤其是日期弹层
    # 已打开时不能用新 tab 替换掉用户正在观察的 DOM 状态。
    for candidate in context.pages:
        if candidate.is_closed() or not candidate.url.startswith(
            "https://cashier.pinduoduo.com/"
        ):
            continue
        if "/main/bills" not in candidate.url:
            continue
        try:
            await candidate.locator(picker).first.wait_for(
                state="visible", timeout=1_000
            )
        except Exception:
            continue
        await candidate.bring_to_front()
        ensure_logged_in(candidate)
        return candidate, False

    home = None
    home_created = False
    for candidate in context.pages:
        if candidate.is_closed() or "mms.pinduoduo.com" not in candidate.url:
            continue
        try:
            await candidate.locator(RECONCILIATION_CENTER_LINK).first.wait_for(
                state="visible", timeout=1_000
            )
        except Exception:
            continue
        home = candidate
        break
    if home is None:
        home = await context.new_page()
        home_created = True
        await home.goto(MMS_HOME_URL, wait_until="domcontentloaded", timeout=60_000)

    await home.bring_to_front()
    await close_home_modal(home)
    reconciliation_center = home.locator(RECONCILIATION_CENTER_LINK).first
    await reconciliation_center.wait_for(state="visible", timeout=60_000)
    known_pages = set(context.pages)
    await reconciliation_center.click()
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        candidates = [home]
        candidates.extend(
            candidate
            for candidate in context.pages
            if candidate not in known_pages
            and candidate.url.startswith("https://cashier.pinduoduo.com/")
        )
        for candidate in candidates:
            if candidate.is_closed() or not candidate.url.startswith(
                "https://cashier.pinduoduo.com/"
            ):
                continue
            try:
                await candidate.locator(picker).first.wait_for(
                    state="visible", timeout=1_000
                )
            except Exception:
                continue
            ensure_logged_in(candidate)
            return candidate, home_created and candidate is home or candidate not in known_pages
        await asyncio.sleep(0.25)
    raise RuntimeError("点击导航栏“对账中心”后未打开账单页面")


@automation_component("pinduoduo.settlement.set_date", "拼多多结算 · 设置日期", category="report")
async def choose_yesterday(page: "Page", business_date: str) -> None:
    picker = page.locator(
        'input[data-testid="beast-core-rangePicker-htmlInput"]'
    ).first
    await picker.wait_for(state="visible", timeout=30_000)
    await picker.click()
    await asyncio.sleep(1.5)
    yesterday = page.get_by_role("button", name="昨天", exact=True)
    await yesterday.wait_for(state="visible", timeout=10_000)
    await yesterday.click()
    expected = expected_range(business_date)
    deadline = asyncio.get_running_loop().time() + 10
    actual = ""
    while asyncio.get_running_loop().time() < deadline:
        actual = await picker.input_value()
        if actual == expected:
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"日期选择失败：期望 {expected!r}，实际 {actual!r}")


async def _click_compat(locator) -> None:
    try:
        await locator.click(timeout=5_000)
    except Exception:
        await locator.evaluate("element => element.click()")


async def _single_control_click(locator) -> None:
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
    raise RuntimeError("拼多多结算日期弹层未打开")


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
        raise RuntimeError("拼多多结算日历缺少月份切换按钮")


async def _open_range_picker(
    page: "Page", picker, *, existing_timeout: float = 0
):
    try:
        return await _visible_range_root(page, timeout=existing_timeout)
    except RuntimeError:
        pass
    # 页面有 document-level outside-click 处理器；Playwright 鼠标点击会在
    # 弹层刚创建后又把它收起。顶层输入也只触发一次 DOM click，避免重复事件。
    await _single_control_click(picker)
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
        f"拼多多结算日期弹层缺少时间输入：{input_testid}"
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
    await _single_control_click(time_input)
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
            f"拼多多结算时间设置失败：期望 {expected!r}，实际 {actual!r}"
        )


@automation_component("pinduoduo.settlement.set_date", "拼多多结算 · 设置日期范围", category="report")
async def choose_date_range(page: "Page", start_date: str, end_date: str) -> None:
    picker = page.locator(
        'input[data-testid="beast-core-rangePicker-htmlInput"]'
    ).first
    await picker.wait_for(state="visible", timeout=30_000)
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
        raise RuntimeError(f"拼多多结算日历未定位到目标月份：{start_date}")

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
    await _single_control_click(confirm)
    expected = expected_range(start_date, end_date)
    deadline = asyncio.get_running_loop().time() + 15
    actual = ""
    while asyncio.get_running_loop().time() < deadline:
        actual = await picker.input_value()
        if actual == expected:
            return
        await asyncio.sleep(0.2)
    raise RuntimeError(f"拼多多结算日期选择失败：期望 {expected!r}，实际 {actual!r}")


@automation_component("pinduoduo.settlement.create_export", "拼多多结算 · 创建导出", category="report")
async def create_export(page: "Page") -> "Page":
    query = page.get_by_role("button", name="查询", exact=True)
    export = page.get_by_role("button", name="导出", exact=True)
    await query.click()
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await export.wait_for(state="visible", timeout=30_000)
    known_pages = set(page.context.pages)
    await export.click()
    deadline = asyncio.get_running_loop().time() + 30
    history_path = "/main/bills/export-history"
    while asyncio.get_running_loop().time() < deadline:
        if history_path in page.url:
            return page
        new_history_pages = [
            candidate
            for candidate in page.context.pages
            if candidate not in known_pages and history_path in candidate.url
        ]
        if new_history_pages:
            history = new_history_pages[-1]
            await history.wait_for_load_state("domcontentloaded", timeout=30_000)
            await page.close()
            return history
        await asyncio.sleep(0.25)
    await page.goto(EXPORT_HISTORY_URL, wait_until="domcontentloaded", timeout=60_000)
    return page


@automation_component("pinduoduo.settlement.wait_ready", "拼多多结算 · 等待导出就绪", category="report")
async def find_export_card(page: "Page", start_date: str, end_date: str):
    start_text = f"{start_date} 00:00:00"
    end_text = f"{end_date} 23:59:59"
    deadline = asyncio.get_running_loop().time() + 90
    while asyncio.get_running_loop().time() < deadline:
        card = (
            page.locator("div.export-history-bills-card")
            .filter(has_text=start_text)
            .filter(has_text=end_text)
            .first
        )
        try:
            await card.wait_for(state="visible", timeout=10_000)
            download = card.get_by_role("button", name="下载账单", exact=True)
            await download.wait_for(state="visible", timeout=10_000)
            return card
        except Exception:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
    raise RuntimeError(f"拼多多导出记录未生成：{start_date} 至 {end_date}")


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download: "Download", directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(
        directory, download.suggested_filename or "pinduoduo_settlement.zip"
    )
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"拼多多下载文件为空：{target}")
    return target


@automation_component("file.archive.extract", "解压 / 提取报表文件", category="file")
def extract_pdd_report(archive: Path, dest: Path) -> Path:
    if not zipfile.is_zipfile(archive):
        raise RuntimeError(f"下载文件不是有效 ZIP：{archive}")
    csv_members: list[str] = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            repaired = repair_member_name(info.filename, info.flag_bits, "gbk")
            if Path(repaired).suffix.lower() == ".csv":
                csv_members.append(repaired)
    if len(csv_members) != 1:
        raise RuntimeError(
            f"拼多多 ZIP 中未找到唯一 CSV：{'、'.join(csv_members) or '无'}"
        )
    return extract_selected_report(
        archive=archive,
        dest=dest,
        include_text=".csv",
        exclude_text="",
        filename_encoding="gbk",
        delete_archive=True,
    )


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_report(report: Path) -> None:
    raw = report.read_bytes()
    if not raw:
        raise RuntimeError(f"拼多多 CSV 为空：{report}")
    decoded = None
    for encoding in ("gb18030", "utf-8-sig"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise RuntimeError(f"拼多多 CSV 编码无法识别：{report}")
    header_line = next(
        (line for line in decoded.splitlines() if line.startswith("商户订单号,")), ""
    )
    header = next(csv.reader([header_line])) if header_line else []
    validate_report_columns(
        header,
        REQUIRED_COLUMNS,
        report_name="拼多多 CSV",
        missing_error_prefix="拼多多 CSV 表头不匹配，缺少：",
    )


@automation_component("report.archive", "归档标准报表", category="file")
def move_report(
    source: Path,
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


@automation_component("pinduoduo.settlement.workflow", "拼多多结算 · 下载流程", category="workflow")
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

    temporary = (
        tempfile.TemporaryDirectory(prefix="pdd_settlement_")
        if work_dir is None
        else None
    )
    actual_work_dir = work_dir or Path(temporary.name)
    start_date, end_date = resolve_date_range(start_date, end_date)
    page = None
    created = False
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            context = browser.contexts[0]
            page, created = await open_reconciliation_center(context)
            await choose_date_range(page, start_date, end_date)
            if date_only:
                print(
                    f"日期设置校验成功：{start_date} 00:00:00 ~ {end_date} 23:59:59"
                )
                if created and not page.is_closed():
                    await page.close()
                page = None
                return 0
            page = await create_export(page)
            if not page.url.startswith(EXPORT_HISTORY_URL.split("?")[0]):
                await page.goto(
                    EXPORT_HISTORY_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            card = await find_export_card(page, start_date, end_date)
            print(f"目标结算日期范围：{start_date} 至 {end_date}")
            async with page.expect_download(timeout=120_000) as download_info:
                await card.get_by_role(
                    "button", name="下载账单", exact=True
                ).click()
            downloaded = await save_download(await download_info.value, actual_work_dir)
            print(f"已下载临时文件：{downloaded}")
            source = await asyncio.to_thread(
                extract_pdd_report, downloaded, actual_work_dir
            )
            print(f"已提取结算明细：{source}")
            await asyncio.to_thread(validate_report, source)
            print("拼多多结算明细结构校验通过")
            move_log = await asyncio.to_thread(
                move_report,
                source,
                platform,
                company,
                shop,
                end_date,
                dest,
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
    parser = argparse.ArgumentParser(description="拼多多结算账单下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    parser.add_argument("--start-date", default=None, help="结算发生时间起始日期，YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结算发生时间结束日期，YYYY-MM-DD")
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
