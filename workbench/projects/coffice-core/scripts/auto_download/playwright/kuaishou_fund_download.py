# -*- coding: utf-8 -*-
"""下载快手最新日/月资金账单并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse

if TYPE_CHECKING:
    from playwright.async_api import Page

from .kuaishou_download_common import (
    ensure_logged_in,
    move_report,
    new_page,
    prepare_report_file,
    save_download,
)

FUND_BASE_URL = "https://s.kwaixiaodian.com/zone/fund/accounting/account-bill"
REPORT_NAME = "资金"
QUERY_RE = re.compile(r"^\s*查\s*询\s*$")
EXPORT_BILL_RE = re.compile(r"^\s*导\s*出\s*账\s*单\s*$")
DOWNLOAD_RE = re.compile(r"^\s*下\s*载\s*$")
DAY_RE = re.compile(r"^(\d{8})(?:\s|$)")
MONTH_RE = re.compile(r"^(\d{6})(?:\s|$)")
EXPORT_RECORD_DATE_RE = re.compile(
    r"账单日期\s*[:：]\s*(\d{4}(?:(?:\s*[/.-]\s*)?\d{2}){1,2})"
)


def extract_business_date(text: str, mode: str) -> str:
    match = (MONTH_RE if mode == "month" else DAY_RE).search(text.strip())
    if not match:
        raise RuntimeError(f"无法识别最新{mode}资金账单日期：{text!r}")
    return match.group(1)


def extract_export_record_business_date(text: str) -> str | None:
    match = EXPORT_RECORD_DATE_RE.search(text)
    if not match:
        return None
    return re.sub(r"\D", "", match.group(1))


def extract_sub_mch_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc != "s.kwaixiaodian.com" or not parsed.path.startswith("/zone/"):
        return None
    values = parse_qs(parsed.query).get("subMchId", [])
    if not values or not re.fullmatch(r"\d+", values[0]):
        return None
    return values[0]


def infer_sub_mch_id(browser) -> str | None:
    for context in browser.contexts:
        for candidate in context.pages:
            sub_mch_id = extract_sub_mch_id_from_url(candidate.url)
            if sub_mch_id:
                return sub_mch_id
    return None


async def find_page_for_sub_mch_id(browser, sub_mch_id: str):
    candidates = [
        candidate
        for context in browser.contexts
        for candidate in context.pages
        if not candidate.is_closed()
        and extract_sub_mch_id_from_url(candidate.url) == sub_mch_id
    ]
    for candidate in candidates:
        if await candidate.locator("div.container___mBlUU").count():
            return candidate
    return candidates[-1] if candidates else None


@automation_component("kuaishou.fund.locate_bill", "快手资金 · 定位最新账单", category="report")
async def latest_bill_row(page: "Page", mode: str, target_date: str | None = None):
    if target_date:
        from .historical_bill import locate_bill
        # The recent-month query already includes yesterday's bill. Match that
        # exact row before changing the range: today is disabled as an end date.
        rows = page.locator("tr.zone-fund-accounting-table-row:visible")
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        try:
            await rows.first.wait_for(state="visible", timeout=30000)
        except PlaywrightTimeoutError:
            # An empty recent window still permits a historical-range query.
            pass
        for index, row_text in enumerate(await rows.all_inner_texts()):
            try:
                business_date = extract_business_date(row_text, mode)
            except RuntimeError:
                continue
            if business_date == target_date.replace("-", ""):
                row = rows.nth(index)
                if await row.get_by_role("button", name=EXPORT_BILL_RE).count():
                    return row, business_date
                raise RuntimeError(f"REPORT_NOT_READY：目标资金账单 {target_date} 尚未开放下载")
        if mode == "day":
            # The live calendar disables an end date equal to the start date.
            # Query a two-day window, then download only the exact target row.
            query_end = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
            # Clear the old recent-month range so its end-date constraints do
            # not disable dates in the newly selected historical month.
            await page.locator('.zone-fund-accounting-picker-range').hover()
            await page.locator('.zone-fund-accounting-picker-clear').click(force=True)
            panel = page.locator('.zone-fund-accounting-picker-dropdown:visible')
            for field in ("开始日期", "结束日期"):
                selected_date = target_date if field == "开始日期" else query_end
                if field == "结束日期":
                    await page.get_by_placeholder(field, exact=True).focus()
                if field == "开始日期" or not await panel.count():
                    await page.get_by_placeholder(field, exact=True).click()
                await panel.wait_for(state="visible", timeout=10000)
                for _ in range(120):
                    cell = panel.locator(f'td.zone-fund-accounting-picker-cell-in-view:not(.zone-fund-accounting-picker-cell-disabled)[title="{selected_date}"]').first
                    if await cell.count():
                        await cell.evaluate('element=>element.click()')
                        break
                    header = await panel.locator('.zone-fund-accounting-picker-header-view').first.inner_text()
                    values = re.findall(r'\d+', header)
                    if len(values) < 2:
                        raise RuntimeError("无法识别快手账单日期面板月份")
                    current = f'{int(values[0]):04d}-{int(values[1]):02d}'
                    if current == selected_date[:7]:
                        raise RuntimeError(f"快手账单日历禁用{field} {selected_date}，未导出其他日期")
                    direction = 'prev' if current > selected_date[:7] else 'next'
                    await panel.locator(f'button.zone-fund-accounting-picker-header-{direction}-btn:visible').first.click()
                else:
                    raise RuntimeError("快手账单日历未能定位目标月份")
            if await page.get_by_placeholder("开始日期", exact=True).input_value() != target_date or await page.get_by_placeholder("结束日期", exact=True).input_value() != query_end:
                raise RuntimeError(f"快手目标账单日期未生效：{await page.get_by_placeholder('开始日期', exact=True).input_value()} ~ {await page.get_by_placeholder('结束日期', exact=True).input_value()}；已停止导出")
            await page.get_by_role("button", name=QUERY_RE).click()
            try:
                await page.wait_for_function("target=>[...document.querySelectorAll('tr.zone-fund-accounting-table-row')].some(e=>e.textContent.includes(target))",arg=target_date.replace('-',''),timeout=30000)
            except Exception as exc:
                raise RuntimeError(f"REPORT_NOT_READY：快手查询未返回 {target_date} 资金账单") from exc
        return await locate_bill(page, "tr.zone-fund-accounting-table-row:visible", target_date, mode,
                                 extract_business_date, lambda row: row.get_by_role("button", name=EXPORT_BILL_RE))
    rows = page.locator("tr.zone-fund-accounting-table-row:visible")
    deadline = asyncio.get_running_loop().time() + 30
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        for index in range(await rows.count()):
            row = rows.nth(index)
            last_text = (await row.inner_text()).strip()
            export = row.get_by_role("button", name=EXPORT_BILL_RE)
            if await export.count():
                return row, extract_business_date(last_text, mode)
        await asyncio.sleep(0.5)
    raise RuntimeError(f"等待快手最新资金账单超时：{last_text!r}")


@automation_component("kuaishou.fund.wait_ready", "快手资金 · 等待导出记录", category="report")
async def find_export_record(browser, page: "Page", business_date: str):
    deadline = asyncio.get_running_loop().time() + 90
    next_reload_at = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        await page.bring_to_front()
        for context in list(browser.contexts):
            for candidate in list(context.pages):
                if candidate.is_closed():
                    continue
                await candidate.bring_to_front()
                cards = candidate.locator("div.container___mBlUU")
                card_count = await cards.count()
                for index in range(card_count):
                    card = cards.nth(index)
                    card_text = (await card.inner_text()).strip()
                    observed_date = extract_export_record_business_date(card_text)
                    if observed_date != business_date:
                        continue
                    download = card.get_by_role("button", name=DOWNLOAD_RE)
                    if not await download.count():
                        continue
                    if not await download.first.is_visible():
                        continue
                    return candidate, card
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        now = asyncio.get_running_loop().time()
        if now >= next_reload_at:
            await page.reload(wait_until="domcontentloaded")
            next_reload_at = asyncio.get_running_loop().time() + 15
            continue
        await page.wait_for_timeout(min(1000, int(remaining * 1000)))
    raise RuntimeError(f"资金导出记录未生成：{business_date}")


@automation_component("kuaishou.fund.workflow", "快手资金 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    mode: str,
    sub_mch_id: str,
    work_dir: Path | None,
    dest: Path,
    target_date: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="ks_fund_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    page = None
    page_created = False
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not sub_mch_id:
                sub_mch_id = infer_sub_mch_id(browser)
                if sub_mch_id:
                    print("已从当前 profile 页面取得资金账户二级商户号")
            if sub_mch_id:
                page = await find_page_for_sub_mch_id(browser, sub_mch_id)
            if page is None:
                page = await new_page(browser)
                page_created = True
            url = FUND_BASE_URL
            if sub_mch_id:
                url = f"{url}?{urlencode({'subMchId': sub_mch_id})}"
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            ensure_logged_in(page)
            if mode == "month":
                await page.get_by_role("tab", name="月账单", exact=True).click()
            await page.get_by_role("button", name=QUERY_RE).click()
            row, business_date = await latest_bill_row(page, mode, target_date)
            print(f"目标资金日期：{business_date}（{'月账单' if mode == 'month' else '日账单'}）")
            await row.get_by_role("button", name=EXPORT_BILL_RE).click()
            try:
                await page.get_by_text("账单导出成功", exact=True).wait_for(
                    state="visible", timeout=10000
                )
            except Exception:
                pass
            await page.get_by_role("button", name="导出记录", exact=True).click()
            await page.wait_for_url("**/zone/fund/accounting/export-list**", timeout=30000)
            export_page, card = await find_export_record(browser, page, business_date)
            async with export_page.expect_download(timeout=120000) as download_info:
                await card.get_by_role("button", name=DOWNLOAD_RE).click()
            downloaded = await save_download(
                await download_info.value, actual_work_dir, "kuaishou_fund.csv"
            )
            print(f"已下载临时文件：{downloaded}")
            source = await asyncio.to_thread(
                prepare_report_file, downloaded, actual_work_dir, (".csv", ".xlsx")
            )
            move_log = await asyncio.to_thread(
                move_report, source, platform, company, shop, REPORT_NAME, business_date, dest
            )
            print(move_log)
            if page_created:
                await page.close()
                page = None
    finally:
        if page_created and page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="快手资金账单下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--mode", choices=("day", "month"), default="day")
    parser.add_argument("--date", help="指定日账单YYYY-MM-DD")
    parser.add_argument("--month", help="指定月账单YYYY-MM")
    parser.add_argument(
        "--sub-mch-id",
        default=None,
        help="可选：显式指定资金账户二级商户号；默认使用当前 profile 登录店铺",
    )
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
                args.sub_mch_id, Path(args.work_dir) if args.work_dir else None,
                Path(args.dest), target,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
