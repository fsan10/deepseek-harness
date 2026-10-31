# -*- coding: utf-8 -*-
"""下载千川流水对账最新日结报表，并通过 move_report.py 增量归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import csv
import datetime as dt
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from playwright.async_api import FrameLocator, async_playwright

from ..move_report import parse_date
from .douyin_login import goto_with_douyin_login
from .qianchuan_login import (
    QIANCHUAN_HOST,
    QianchuanAccount,
    existing_qianchuan_aavids,
    open_qianchuan_account,
    open_workbench_page,
    parse_aavid_from_url,
    resolve_account,
)

FINANCE_URL = "https://qianchuan.jinritemai.com/finance?aavid={aavid}"
REPORT_NAME = "千川推广费"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEMP_FILE_NAME = ".qianchuan_promotion_fee_latest.csv"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def select_latest_daily_record(tables: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """从实时 DOM 表格中找到日结表的首条日期记录。"""
    headers, rows = select_daily_table(tables)
    if rows:
        return headers, rows[0]
    raise RuntimeError("未找到包含“日期”的千川日结报表或有效业务日期行")


def select_daily_table(tables: list[dict[str, Any]]) -> tuple[list[str], list[list[str]]]:
    """提取日结表表头和当前页日期记录，跳过总计行。"""
    for table in tables:
        headers = [normalize_text(str(value)) for value in table.get("headers", [])]
        if not headers or "日期" not in headers:
            continue
        rows: list[list[str]] = []
        for row in table.get("rows", []):
            values = [normalize_text(str(value)) for value in row]
            if values and DATE_PATTERN.fullmatch(values[0]):
                if len(headers) != len(values):
                    raise RuntimeError(
                        f"千川表头列数与数据列数不一致：表头 {len(headers)} 列，数据 {len(values)} 列"
                    )
                rows.append(values)
        return headers, rows
    raise RuntimeError("未找到千川日结报表表格")


def month_ordinal(year: int, month: int) -> int:
    return year * 12 + month - 1


def calendar_month(title: str) -> tuple[int, int] | None:
    compact = re.sub(r"\s+", "", title)
    match = re.search(r"(\d{4})年(\d{1,2})月", compact)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


async def select_calendar_day(frame: FrameLocator, target: dt.date) -> None:
    """在真实日期选择器中选择指定日期；不修改页面状态或绕开页面接口。"""
    popper = frame.locator(".byted-finance-date-picker-popper")
    for _ in range(36):
        views = popper.locator(".byted-finance-date-view")
        view_count = await views.count()
        if view_count < 2:
            raise RuntimeError("千川日期选择器未显示双月日历")
        months: list[tuple[int, int] | None] = []
        for index in range(view_count):
            title = await views.nth(index).locator(".byted-finance-date-title").inner_text()
            months.append(calendar_month(title))
        if any(month is None for month in months):
            raise RuntimeError(f"无法读取千川日期选择器月份：{months}")

        target_month = (target.year, target.month)
        target_ordinal = month_ordinal(*target_month)
        first_ordinal = month_ordinal(*months[0])  # type: ignore[arg-type]
        last_ordinal = month_ordinal(*months[-1])  # type: ignore[arg-type]
        if target_ordinal < first_ordinal:
            arrow = views.first.locator(".byted-finance-date-nav-prev .byted-finance-icon-left")
            if await arrow.count() != 1:
                raise RuntimeError("千川日期选择器缺少上一月按钮")
            await arrow.click()
            await asyncio.sleep(0.15)
            continue
        if target_ordinal > last_ordinal:
            arrow = views.last.locator(".byted-finance-date-nav-next .byted-finance-icon-right")
            if await arrow.count() != 1:
                raise RuntimeError("千川日期选择器缺少下一月按钮")
            await arrow.click()
            await asyncio.sleep(0.15)
            continue

        target_view = next(
            views.nth(index)
            for index, month in enumerate(months)
            if month == target_month
        )
        items = target_view.locator(".byted-finance-date-item")
        candidates = []
        for index in range(await items.count()):
            item = items.nth(index)
            classes = await item.get_attribute("class") or ""
            if (
                normalize_text(await item.inner_text()) == str(target.day)
                and "byted-finance-date-grid-prev" not in classes
                and "byted-finance-date-grid-next" not in classes
                and "byted-finance-date-disabled" not in classes
            ):
                candidates.append(item)
        if len(candidates) != 1:
            raise RuntimeError(
                f"千川日期选择器中 {target.isoformat()} 匹配到 {len(candidates)} 个日期单元格"
            )
        await candidates[0].locator("xpath=..").click(timeout=10000)
        return
    raise RuntimeError(f"千川日期选择器无法定位到 {target.isoformat()}")


@automation_component("qianchuan.daily.set_range", "千川 · 设置日结日期范围", category="report")
async def set_daily_date_range(frame: FrameLocator, start_date: str, end_date: str) -> None:
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    if end < start:
        raise ValueError("--end-date 不能早于 --start-date")

    date_input = frame.locator('input[placeholder="开始时间 ~ 结束时间"]').first
    await date_input.wait_for(state="visible", timeout=15000)
    date_trigger = (
        date_input.locator("xpath=..")
        .locator("xpath=..")
        .locator("xpath=..")
    )
    # 若 profile 上次留下了弹出的其他日期框，先关闭，再打开日结报表自己的第一个日期框。
    await frame.locator("body").press("Escape")
    await date_trigger.click(timeout=10000)
    popper = frame.locator(".byted-finance-date-picker-popper")
    await popper.wait_for(state="visible", timeout=10000)
    await select_calendar_day(frame, start)
    if not await popper.is_visible():
        await date_trigger.click(timeout=10000)
        await popper.wait_for(state="visible", timeout=10000)
    await select_calendar_day(frame, end)

    expected = f"{start.isoformat()} ~ {end.isoformat()}"
    for _ in range(20):
        if await date_input.input_value() == expected:
            print(f"千川日结日期范围已提交：{expected}")
            return
        await asyncio.sleep(0.25)
    actual = await date_input.input_value()
    raise RuntimeError(f"千川日结日期范围未生效：期望 {expected}，实际 {actual}")


async def wait_daily_range_records(
    frame: FrameLocator, start_date: str, end_date: str, timeout_seconds: float = 60.0
) -> tuple[list[str], list[list[str]]]:
    """等待日结表换成目标日期范围的记录。"""
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_dates: list[str] = []
    while asyncio.get_running_loop().time() < deadline:
        try:
            headers, rows = select_daily_table(await read_live_daily_tables(frame))
            last_dates = [row[0] for row in rows]
            parsed = [dt.date.fromisoformat(value) for value in last_dates]
            if parsed and all(start <= value <= end for value in parsed):
                return headers, rows
            pager_text = await frame.locator(
                ".byted-finance-pager-record"
            ).first.inner_text()
            if not parsed and re.search(r"共\s*0\s*条记录", pager_text):
                return headers, rows
        except (RuntimeError, ValueError):
            pass
        await asyncio.sleep(1)
    raise RuntimeError(
        f"等待千川日结日期范围超时：{start_date} ~ {end_date}；当前页日期={last_dates}"
    )


@automation_component("qianchuan.daily.read_range", "千川 · 读取日期范围内记录", category="report")
async def read_daily_range_records(
    frame: FrameLocator, start_date: str, end_date: str
) -> tuple[list[str], list[list[str]]]:
    """读取日期区间内所有分页日结行并校验总条数和日期范围。"""
    headers, first_rows = await wait_daily_range_records(frame, start_date, end_date)
    all_rows: dict[str, list[str]] = {row[0]: row for row in first_rows}
    pager = frame.locator(".byted-finance-pager").first
    record_label = pager.locator(".byted-finance-pager-record")
    total_match = re.search(r"共\s*(\d+)\s*条记录", await record_label.inner_text())
    if not total_match:
        raise RuntimeError("无法读取千川日结报表记录总数")
    total_count = int(total_match.group(1))
    if total_count == 0:
        return headers, []

    pages = frame.locator(".byted-finance-pager-item-group").first
    current_page = await pages.locator(".byted-finance-pager-item-checked").inner_text()
    if current_page != "1":
        page_one = None
        for index in range(await pages.locator("li").count()):
            item = pages.locator("li").nth(index)
            if normalize_text(await item.inner_text()) == "1":
                page_one = item
                break
        if page_one is None:
            raise RuntimeError("无法在千川日结分页中定位第 1 页")
        previous_first = next(iter(all_rows), "")
        await page_one.click(timeout=10000)
        for _ in range(120):
            current_page = await pages.locator(".byted-finance-pager-item-checked").inner_text()
            _, page_rows = select_daily_table(await read_live_daily_tables(frame))
            if current_page == "1" and page_rows and page_rows[0][0] != previous_first:
                for row in page_rows:
                    all_rows[row[0]] = row
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError("切换至千川日结第 1 页超时")

    for _ in range(100):
        if len(all_rows) >= total_count:
            break
        current_page = await pages.locator(".byted-finance-pager-item-checked").inner_text()
        _, current_rows = select_daily_table(await read_live_daily_tables(frame))
        previous_first = current_rows[0][0] if current_rows else ""
        next_button = pages.locator("li").last
        button_classes = await next_button.get_attribute("class") or ""
        if "byted-finance-pager-item-disabled" in button_classes:
            break
        await next_button.click(timeout=10000)
        for _ in range(120):
            new_page = await pages.locator(".byted-finance-pager-item-checked").inner_text()
            page_headers, rows = select_daily_table(await read_live_daily_tables(frame))
            first_date = rows[0][0] if rows else ""
            if new_page != current_page and first_date and first_date != previous_first:
                break
            await asyncio.sleep(0.25)
        else:
            raise RuntimeError("翻页后千川日结报表页面未切换")
        if page_headers != headers:
            raise RuntimeError("千川日结分页表头发生变化，停止归档")
        for row in rows:
            old = all_rows.get(row[0])
            if old is not None and old != row:
                raise RuntimeError(f"千川日结分页出现冲突日期：{row[0]}")
            all_rows[row[0]] = row

    if len(all_rows) != total_count:
        raise RuntimeError(
            f"千川日结分页记录数量不完整：平台显示 {total_count} 条，读取到 {len(all_rows)} 条"
        )
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    out_of_range = [
        date for date in all_rows
        if not start <= dt.date.fromisoformat(date) <= end
    ]
    if out_of_range:
        raise RuntimeError(f"千川日结报表包含区间外日期：{out_of_range}")
    return headers, [all_rows[key] for key in sorted(all_rows)]


async def find_qianchuan_page(browser, aavid: str = "") -> Any:
    for context in browser.contexts:
        for page in context.pages:
            if QIANCHUAN_HOST not in page.url:
                continue
            if not aavid or parse_aavid_from_url(page.url) == aavid:
                return page
    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用的浏览器上下文")
    return await browser.contexts[0].new_page()


@automation_component("qianchuan.finance.open", "千川 · 打开财务页面", category="report")
async def open_qianchuan_finance_page(
    browser,
    requested_aavid: str,
    *,
    platform: str,
    company: str,
    shop: str,
) -> tuple[Any, QianchuanAccount]:
    """确保进入指定千川账户，再打开财务页。

    ``auto`` 不再要求 profile 启动时已经打开带 aavid 的深链：没有现成千川
    标签时会走升级版工作台登录和账户卡片选择流程。
    """

    account = resolve_account(
        requested_aavid,
        company,
        shop,
        existing_aavids=existing_qianchuan_aavids(browser),
    )
    page = await find_qianchuan_page(browser, account.aavid)
    if QIANCHUAN_HOST not in page.url or parse_aavid_from_url(page.url) != account.aavid:
        workbench = await open_workbench_page(
            browser, platform=platform, company=company, shop=shop
        )
        page = await open_qianchuan_account(workbench, account)
    target_url = FINANCE_URL.format(aavid=account.aavid)
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    if "fxg.jinritemai.com/login" in page.url:
        # 老版本千川深链仍可能回到抖店统一登录页；保留现有共享登录
        # 恢复作为兼容分支，登录后再由同一目标 URL 进入千川财务页。
        await goto_with_douyin_login(
            page,
            target_url,
            shop,
            platform=platform,
            company=company,
            login_alert_purpose="巨量千川登录态失效，请在已启动的 profile 中检查并重新登录",
        )
    if "business.oceanengine.com/login" in page.url:
        # 千川深链可能在独立会话过期时把页面送回巨量引擎登录页；重新走
        # 工作台恢复和账户访问，不把旧登录页误当成财务空表。
        workbench = await open_workbench_page(
            browser, platform=platform, company=company, shop=shop
        )
        page = await open_qianchuan_account(workbench, account)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    if QIANCHUAN_HOST not in page.url:
        raise RuntimeError(f"打开千川财务页后仍不在千川域名：{page.url.split('?')[0]}")
    print(f"已进入千川账户：{account.aavid}")
    return page, account


async def finance_frame(
    page,
    aavid: str,
    shop: str,
    *,
    platform: str = "抖音",
    company: str = "",
) -> FrameLocator:
    actual_aavid = aavid.strip()
    if actual_aavid.lower() == "auto":
        actual_aavid = parse_aavid_from_url(page.url)
        if not actual_aavid:
            raise RuntimeError(
                "finance_frame 收到 --aavid auto，但当前页面没有 aavid；"
                "请先调用 open_qianchuan_finance_page"
            )
    target_url = FINANCE_URL.format(aavid=actual_aavid)
    if page.url != target_url:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    iframe = page.locator("iframe.auth-iframe")
    await iframe.wait_for(state="attached", timeout=30000)
    frame = page.frame_locator("iframe.auth-iframe")
    await frame.get_by_text("流水对账", exact=True).first.wait_for(state="visible", timeout=30000)
    return frame


@automation_component("qianchuan.daily.open", "千川 · 打开日结报表", category="report")
async def open_daily_report(frame: FrameLocator) -> None:
    menu = frame.get_by_text("流水对账", exact=True).first
    try:
        await menu.click(timeout=10000)
    except Exception:
        await menu.evaluate("element => element.click()")
    await frame.get_by_text("日结报表", exact=True).first.wait_for(state="visible", timeout=30000)


async def read_live_daily_tables(frame: FrameLocator) -> list[dict[str, Any]]:
    """读取 iframe 内全部表格；只在 Python 侧选择目标表，绝不固定列定义。"""
    return await frame.locator("table").evaluate_all(
        """tables => tables.map(table => ({
            headers: Array.from(table.querySelectorAll('thead th')).map(cell => cell.innerText),
            rows: Array.from(table.querySelectorAll('tbody tr')).map(row =>
                Array.from(row.querySelectorAll('td')).map(cell => cell.innerText)
            ),
        }))"""
    )


@automation_component("qianchuan.daily.wait", "千川 · 等待最新日结", category="report")
async def wait_latest_daily_record(
    frame: FrameLocator, timeout_seconds: float = 30.0
) -> tuple[list[str], list[str]]:
    """等待千川异步表格填充完成，避免只等到空表骨架。"""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error: RuntimeError | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            return select_latest_daily_record(await read_live_daily_tables(frame))
        except RuntimeError as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"日结表加载超时：{last_error}")


def write_csv(path: Path, headers: list[str], row: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerow(row)


def report_archive_exists(
    dest: Path, platform: str, company: str, shop: str, business_date: str
) -> bool:
    from scripts.auto_download.move_report import archive_filename, report_directory
    report_dir = report_directory(dest, platform, REPORT_NAME, business_date)
    name_prefix = archive_filename(platform, company, shop, REPORT_NAME, business_date, ".csv")[:-4]
    # Read both layouts during the migration; all new files use monthly folders.
    return any(path.is_file() and path.stat().st_size > 0
               for directory in (report_dir, dest / platform / REPORT_NAME)
               for path in directory.glob(f"{name_prefix}*.csv"))


@automation_component("report.archive", "归档标准报表", category="file")
def archive_with_move_report(
    source_dir: Path,
    platform: str,
    company: str,
    shop: str,
    business_date: str,
    dest: Path,
) -> str:
    """调用项目统一 move_report.py 完成命名、目录校验和同名递增。"""
    command = [
        sys.executable, "-m", "scripts.auto_download.move_report",
        "--platform", platform, "--company", company, "--shop", shop,
        "--report", REPORT_NAME, "--date", business_date,
        "--src", str(source_dir), "--dest", str(dest),
        "--pattern", TEMP_FILE_NAME, "--within", "10",
    ]
    completed = subprocess.run(
        command, cwd=PROJECT_ROOT, check=False, capture_output=True, text=True, encoding="utf-8"
    )
    if completed.returncode:
        raise RuntimeError(f"move_report.py 归档失败：{completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout.strip()


@automation_component("qianchuan.promotion.workflow", "千川推广费 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    aavid: str,
    platform: str,
    company: str,
    shop: str,
    dest: Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        page, account = await open_qianchuan_finance_page(
            browser,
            aavid,
            platform=platform,
            company=company,
            shop=shop,
        )
        frame = await finance_frame(
            page,
            account.aavid,
            shop,
            platform=platform,
            company=company,
        )
        await open_daily_report(frame)
        if start_date and end_date:
            await set_daily_date_range(frame, start_date, end_date)
            headers, rows = await read_daily_range_records(frame, start_date, end_date)
            print(
                f"网页实时表头：{len(headers)} 列；区间记录：{len(rows)} 条；"
                f"日期：{start_date} ~ {end_date}"
            )
            skipped = 0
            archived = 0
            with tempfile.TemporaryDirectory(prefix="qianchuan_promotion_fee_") as directory:
                source_dir = Path(directory)
                source_file = source_dir / TEMP_FILE_NAME
                for row in rows:
                    business_date = row[0]
                    parse_date(business_date)
                    # Explicit historical ranges are planned after verified
                    # coverage is removed upstream. Re-fetch every selected day
                    # so refresh also repairs legacy or missing receipts.
                    write_csv(source_file, headers, row)
                    archive_log = await asyncio.to_thread(
                        archive_with_move_report,
                        source_dir,
                        platform,
                        company,
                        shop,
                        business_date,
                        dest,
                    )
                    archived += 1
                    print(archive_log)
            print(f"千川日结区间处理完成：新增归档 {archived} 条，已有记录跳过 {skipped} 条")
        else:
            headers, row = await wait_latest_daily_record(frame)
            business_date = row[0]
            parse_date(business_date)
            print(f"网页实时表头：{len(headers)} 列；目标日期：{business_date}")

            with tempfile.TemporaryDirectory(prefix="qianchuan_promotion_fee_") as directory:
                source_dir = Path(directory)
                write_csv(source_dir / TEMP_FILE_NAME, headers, row)
                archive_log = await asyncio.to_thread(
                    archive_with_move_report, source_dir, platform, company, shop, business_date, dest
                )
            print(archive_log)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="千川推广费日结表下载（Playwright + Cloak Login CDP）")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument(
        "--aavid",
        required=True,
        help=(
            "千川广告账户 ID；传 auto 时优先复用当前千川标签，"
            "否则按 profile 的公司/店铺备注选择默认账户并从升级版工作台访问"
        ),
    )
    parser.add_argument("--platform", required=True, help="平台中文名，取 profile note")
    parser.add_argument("--company", required=True, help="公司全称，取 profile note")
    parser.add_argument("--shop", required=True, help="店铺名，取 profile note")
    parser.add_argument("--dest", default=r"C:\\Users\\win\\Desktop\\data", help="归档根目录")
    parser.add_argument("--start-date", help="逐日导出起始日期，格式 YYYY-MM-DD；需与 --end-date 同时传入")
    parser.add_argument("--end-date", help="逐日导出结束日期，格式 YYYY-MM-DD；需与 --start-date 同时传入")
    args = parser.parse_args()

    if not args.cdp.startswith(("ws://", "wss://")):
        print(f"--cdp 格式错误：{args.cdp}（应为 ws:// 或 wss://）", file=sys.stderr)
        return 2
    if bool(args.start_date) != bool(args.end_date):
        parser.error("--start-date 和 --end-date 必须同时传入")
    if args.start_date and args.end_date:
        try:
            start = dt.date.fromisoformat(args.start_date)
            end = dt.date.fromisoformat(args.end_date)
        except ValueError as exc:
            parser.error(f"日期格式错误：{exc}（要求 YYYY-MM-DD）")
        if end < start:
            parser.error("--end-date 不能早于 --start-date")
    try:
        return asyncio.run(
            run(
                args.cdp,
                args.aavid,
                args.platform,
                args.company,
                args.shop,
                Path(args.dest),
                args.start_date,
                args.end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
