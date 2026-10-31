# -*- coding: utf-8 -*-
"""下载京东最新日/月结算账单，递归提取 CSV 并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
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

SETTLEMENT_URL = "https://shop.jd.com/jdm/fin/billManage/DailyBill"
REPORT_NAME = "结算"
DAY_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
MONTH_RE = re.compile(r"(?<!\d)(\d{4}-\d{2})(?!-\d{2})")


def extract_business_date(text: str, mode: str) -> str:
    match = (MONTH_RE if mode == "month" else DAY_RE).search(text)
    if not match:
        raise RuntimeError(f"最新{mode}账单日期无法识别：{text!r}")
    return match.group(1)


@automation_component("jd.settlement.select_mode", "京东结算 · 选择日月模式", category="report")
async def select_mode(page: "Page", mode: str) -> None:
    await page.goto(SETTLEMENT_URL, wait_until="domcontentloaded")
    if mode == "month":
        await page.get_by_text("月账单", exact=True).first.click()
        await page.wait_for_url("**/MonthlyBill", timeout=30000)
    await page.locator(".ag-row.ag-row-level-0:visible").first.wait_for(
        state="visible", timeout=30000
    )


@automation_component("jd.settlement.locate", "京东结算 · 定位最新账单", category="report")
async def latest_row(page: "Page", mode: str, target_date: str | None = None) -> tuple[object, str]:
    if target_date:
        from .historical_bill import locate_bill
        if mode == "day":
            # The live page defaults to a recent-month query. Pagination alone
            # cannot reach an August bill until the query range is changed.
            start = page.get_by_placeholder("开始日期", exact=True)
            end = page.get_by_placeholder("结束日期", exact=True)
            # This live control needs focus before click; an unfocused DOM click
            # opens a panel that immediately collapses. NPS covers the hit target.
            await start.focus()
            await start.evaluate("element => element.click()")
            panel = page.locator('.el-date-range-picker:visible')
            await panel.wait_for(state='visible', timeout=10000)
            header = panel.locator('.el-date-range-picker__header').first
            for _ in range(120):
                parts = re.findall(r'\d+', await header.inner_text())
                if len(parts) < 2:
                    raise RuntimeError('无法识别京东账单日历月份')
                current = f'{int(parts[0]):04d}-{int(parts[1]):02d}'
                if current == target_date[:7]:
                    cell = header.locator('..').locator('td.available').filter(has_text=re.compile(rf'^\s*{int(target_date[-2:])}\s*$')).first
                    await cell.evaluate('element=>element.click()')
                    await cell.evaluate('element=>element.click()')
                    break
                direction = 'left' if current > target_date[:7] else 'right'
                await panel.locator(f'button.arrow-{direction}').first.evaluate('element=>element.click()')
            else:
                raise RuntimeError('京东账单日历未能定位目标月份')
            if await start.input_value() != target_date or await end.input_value() != target_date:
                raise RuntimeError(f"京东结算目标日期未生效：{await start.input_value()} ~ {await end.input_value()}；已停止下载")
            # The live NPS overlay covers the button even with force=True.
            # Dispatch through this observed DOM button, never a hidden API.
            await page.get_by_role("button", name="查询", exact=True).evaluate("element => element.click()")
            # Consecutive queries can briefly overlap their loading masks.
            await page.wait_for_function(
                "() => ![...document.querySelectorAll('.el-loading-mask')].some(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden')",
                timeout=30000,
            )
            try:
                await page.wait_for_function("target => [...document.querySelectorAll('.ag-row.ag-row-level-0')].some(e=>e.textContent.includes(target))", arg=target_date, timeout=30000)
            except Exception as exc:
                raise RuntimeError(f"REPORT_NOT_READY：查询未返回 {target_date} 账单；未下载其他日期") from exc
        return await locate_bill(page, ".ag-row.ag-row-level-0:visible", target_date, mode,
                                 extract_business_date, lambda row: row.locator("button:visible").filter(has_text="下载明细"),
                                 date_cell_selector='[col-id="setDate"]')
    rows = page.locator(".ag-row.ag-row-level-0:visible")
    deadline = asyncio.get_running_loop().time() + 30
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        for index in range(await rows.count()):
            row = rows.nth(index)
            last_text = (await row.locator('[col-id="setDate"]').inner_text()).strip()
            try:
                business_date = extract_business_date(last_text, mode)
            except RuntimeError:
                continue
            button = row.locator("button:visible").filter(has_text="下载明细")
            if await button.count():
                return row, business_date
        await asyncio.sleep(0.5)
    raise RuntimeError(f"等待最新可下载{mode}账单超时：{last_text!r}")


@automation_component("jd.settlement.workflow", "京东结算 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    mode: str,
    work_dir: Path | None,
    dest: Path,
    target_date: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="jd_settlement_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    page = None
    session_lock = await asyncio.to_thread(acquire_download_lock)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await new_authenticated_page(browser)
            await select_mode(page, mode)
            row, business_date = await latest_row(page, mode, target_date)
            print(f"目标账单：{business_date}（{'月账单' if mode == 'month' else '日账单'}）")
            button = row.locator("button:visible").filter(has_text="下载明细").first
            async with page.expect_download(timeout=120000) as download_info:
                # The observed NPS web component covers the grid's native hit
                # target. Invoke this exact verified row's download button.
                await button.evaluate("element => element.click()")
            downloaded = await save_download(
                await download_info.value, actual_work_dir, "jd_settlement.zip"
            )
            print(f"已下载临时 ZIP：{downloaded}")
            csv_file = await asyncio.to_thread(prepare_report_file, downloaded, actual_work_dir)
            print(f"已提取 CSV：{csv_file}")
            move_log = await asyncio.to_thread(
                move_report, csv_file, platform, company, shop, REPORT_NAME, business_date, dest
            )
            print(move_log)
            await page.close()
            page = None
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if temporary is not None:
            temporary.cleanup()
        await asyncio.to_thread(release_download_lock, session_lock)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="京东结算账单下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--mode", choices=("day", "month"), default="day")
    parser.add_argument("--date", help="指定日账单YYYY-MM-DD")
    parser.add_argument("--month", help="指定月账单YYYY-MM")
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    try:
        from .historical_bill import bill_target
        target = bill_target(args.mode, args.date, args.month)
        return asyncio.run(
            run(
                args.cdp, args.platform, args.company, args.shop, args.mode,
                Path(args.work_dir) if args.work_dir else None, Path(args.dest), target,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
