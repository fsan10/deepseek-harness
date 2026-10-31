# -*- coding: utf-8 -*-
"""导出京东资金流水账单并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from .jd_download_common import (
    acquire_download_lock,
    move_report,
    new_authenticated_page,
    prepare_report_file,
    release_download_lock,
    save_download,
)

FUND_URL = "https://shop.jd.com/jdm/finance/billManage/foundFlow?formCeconciiFlag=true"
REPORT_NAME = "资金"
TASK_TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


async def _click_compat(locator: object) -> None:
    try:
        await locator.click(timeout=8_000)
    except Exception:
        await locator.evaluate("element => element.click()")


@automation_component("jd.fund.set_date", "京东资金 · 选择日期", category="report")
async def select_yesterday(page: "Page") -> str:
    return await select_date_range(page)


async def _force_fill_readonly(locator: object, value: str) -> None:
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


@automation_component("jd.fund.set_date", "京东资金 · 设置日期范围", category="report")
async def select_date_range(
    page: "Page",
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Select an explicit natural-date range, or yesterday when omitted."""

    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date 和 --end-date 必须同时提供")
    await page.goto(FUND_URL, wait_until="domcontentloaded")
    start_input = page.locator('input[placeholder="开始时间"]').first
    end_input = page.locator('input[placeholder="结束时间"]').first
    await start_input.wait_for(state="visible", timeout=30000)
    if start_date is None and end_date is None:
        await _click_compat(start_input)
        yesterday = page.get_by_role("button", name="昨天", exact=True).last
        await yesterday.wait_for(state="visible", timeout=10000)
        await _click_compat(yesterday)
    else:
        for label, value in (("开始", start_date), ("结束", end_date)):
            try:
                datetime.strptime(value or "", "%Y-%m-%d")
            except ValueError as exc:
                raise ValueError(f"{label}日期必须是 YYYY-MM-DD") from exc
        if start_date > end_date:
            raise ValueError("资金开始日期不能晚于结束日期")
        await _click_compat(start_input)
        await _force_fill_readonly(start_input, f"{start_date} 00:00:00")
        await start_input.press("Enter")
        await _click_compat(end_input)
        await _force_fill_readonly(end_input, f"{end_date} 23:59:59")
        await end_input.press("Enter")
    business_date = (await start_input.input_value())[:10]
    actual_end_date = (await end_input.input_value())[:10]
    if not business_date or not actual_end_date:
        raise RuntimeError(f"资金日期选择失败：{business_date!r} - {actual_end_date!r}")
    if start_date is None and business_date != actual_end_date:
        raise RuntimeError(f"昨天日期选择失败：{business_date!r} - {actual_end_date!r}")
    if start_date is not None and (business_date != start_date or actual_end_date != end_date):
        raise RuntimeError(
            f"资金日期范围选择失败：期望 {start_date} ~ {end_date}，"
            f"实际 {business_date} ~ {actual_end_date}"
        )
    await _click_compat(page.get_by_role("button", name="查询", exact=True).last)
    await asyncio.sleep(1.5)
    return actual_end_date


@automation_component("jd.fund.create_export", "京东资金 · 创建导出任务", category="report")
async def create_export_task(page: "Page") -> object:
    feedback = page.locator(".el-dialog.user-voice:visible").filter(
        has_text="请您对[资金流水账单]整体感受打分"
    )
    if await feedback.count():
        await feedback.get_by_text("我不愿作答", exact=True).click()
        await feedback.wait_for(state="hidden", timeout=10000)
    export = page.locator("span.actions-down:visible").filter(has_text="导出").first
    await export.wait_for(state="visible", timeout=30000)
    await export.click(force=True)
    # The current drawer can retain a hidden confirmation button from a
    # previous render; selecting the visible primary button avoids waiting on
    # that stale locator.
    confirm = page.locator("button.jd-button--primary:visible").filter(
        has_text="确认导出"
    ).last
    # JD may open a satisfaction survey instead of the export drawer. Dismiss
    # that exact dialog before trying the drawer opener again; no export task
    # is submitted until the single confirmation click below.
    await confirm.or_(feedback).first.wait_for(state="visible", timeout=60000)
    if await feedback.count():
        await feedback.get_by_text("我不愿作答", exact=True).click()
        await feedback.wait_for(state="hidden", timeout=10000)
        if not await confirm.is_visible():
            await export.click(force=True)
    await confirm.wait_for(state="visible", timeout=10000)
    rows = page.locator("tr.jd-table__row:visible").filter(
        has_text="账单查询-资金流水账单"
    )
    previous_first = ""
    try:
        await rows.first.wait_for(state="visible", timeout=5000)
        previous_first = (await rows.first.inner_text()).strip()
    except Exception:
        pass
    submitted_after = datetime.now() - timedelta(seconds=5)
    await confirm.click()
    deadline = asyncio.get_running_loop().time() + 60
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        if await rows.count():
            last_text = (await rows.first.inner_text()).strip()
            time_match = TASK_TIME_RE.search(last_text)
            is_recent = bool(
                time_match
                and datetime.strptime(time_match.group(), "%Y-%m-%d %H:%M:%S") >= submitted_after
            )
            if last_text != previous_first and is_recent:
                loading = page.locator(".jd-loading-mask.is-fullscreen:visible")
                if await loading.count():
                    await loading.first.wait_for(state="hidden", timeout=30000)
                return rows.first
        await asyncio.sleep(0.5)
    raise RuntimeError(f"确认导出后未识别到新资金任务，首行状态：{last_text!r}")


@automation_component("jd.fund.wait_download", "京东资金 · 等待并下载", category="report")
async def wait_and_download(page: "Page", row: object, work_dir: Path) -> Path:
    deadline = asyncio.get_running_loop().time() + 180
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        last_text = (await row.inner_text()).strip()
        download = row.get_by_text("下载", exact=True)
        if await download.count() and await download.first.is_visible():
            async with page.expect_download(timeout=120000) as download_info:
                await download.first.click(force=True)
            return await save_download(
                await download_info.value, work_dir, "jd_fund.xlsx"
            )
        refresh = row.get_by_text("刷新", exact=True)
        if await refresh.count() and await refresh.first.is_visible():
            await refresh.first.click(force=True)
        else:
            refresh_list = page.get_by_text("刷新列表", exact=True)
            if await refresh_list.count() and await refresh_list.first.is_visible():
                await refresh_list.first.click(force=True)
        await asyncio.sleep(2)
    raise RuntimeError(f"等待资金导出任务可下载超时，最后状态：{last_text!r}")


@automation_component("jd.fund.workflow", "京东资金 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path | None,
    dest: Path,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = (
        tempfile.TemporaryDirectory(prefix="jd_fund_", delete=False)
        if work_dir is None else None
    )
    actual_work_dir = work_dir or Path(temporary.name)
    page = None
    completed = False
    session_lock = await asyncio.to_thread(acquire_download_lock)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await new_authenticated_page(browser)
            business_date = await select_date_range(page, start_date, end_date)
            if start_date and end_date:
                print(f"目标资金日期范围：{start_date} ~ {end_date}")
            else:
                print(f"目标资金日期：{business_date}")
            row = await create_export_task(page)
            downloaded = await wait_and_download(page, row, actual_work_dir)
            print(f"已下载临时文件：{downloaded}")
            source = await asyncio.to_thread(prepare_report_file, downloaded, actual_work_dir)
            move_log = await asyncio.to_thread(
                move_report, source, platform, company, shop, REPORT_NAME, business_date, dest
            )
            print(move_log)
            await page.close()
            page = None
            completed = True
    finally:
        if temporary is not None and completed:
            temporary.cleanup()
        if not completed:
            print(f"京东资金步骤未完成，保留页面和临时下载目录：{actual_work_dir}")
        await asyncio.to_thread(release_download_lock, session_lock)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="京东资金流水账单下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    parser.add_argument("--start-date", default=None, help="自定义资金开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义资金结束日期 YYYY-MM-DD")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if (args.start_date is None) != (args.end_date is None):
        print("--start-date 和 --end-date 必须同时提供", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            run(
                args.cdp, args.platform, args.company, args.shop,
                Path(args.work_dir) if args.work_dir else None,
                Path(args.dest), args.start_date, args.end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
