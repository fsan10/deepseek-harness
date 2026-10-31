# -*- coding: utf-8 -*-
"""下载快手指定日期范围（默认昨天）的结算单，解压并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

from .kuaishou_download_common import (
    ensure_logged_in,
    move_report,
    new_page,
    prepare_report_file,
    save_download,
)

SETTLEMENT_URL = "https://s.kwaixiaodian.com/zone/fund/accounting/payment-bill"
EXPORT_URL = (
    "https://s.kwaixiaodian.com/zone/fund/accounting/export-list"
    "?type=SELLER_SETTLED_ORDER_V2"
)
REPORT_NAME = "结算"
QUERY_RE = re.compile(r"^\s*查\s*询\s*$")
EXPORT_RE = re.compile(r"^\s*导\s*出\s*$")
DOWNLOAD_RE = re.compile(r"^\s*下\s*载\s*$")
KNOW_RE = re.compile(r"^\s*(?:我\s*)?知\s*道\s*了\s*$")
RECORD_COUNT_RE = re.compile(r"共\s*计\s*([0-9０-９,，]+)\s*条")
QUERY_API_FRAGMENT = "/financial/bill/pcpageorder/list"


def default_business_date() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def validate_business_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


@automation_component("kuaishou.settlement.set_date", "快手结算 · 设置日期范围", category="report")
async def choose_range(page: "Page", start_date: str, end_date: str) -> tuple[str, str]:
    start_value = f"{start_date} 00:00:00"
    end_value = f"{end_date} 23:59:59"
    start = page.locator('input[placeholder="开始日期"]').first
    end = page.locator('input[placeholder="结束日期"]').first
    await start.wait_for(state="visible", timeout=30000)
    await start.click()
    await start.fill(start_value)
    await start.press("Enter")
    await end.fill(end_value)
    await end.press("Enter")
    actual = (await start.input_value(), await end.input_value())
    if actual != (start_value, end_value):
        raise RuntimeError(f"结算时间选择失败：{actual[0]!r} - {actual[1]!r}")
    return actual


def parse_record_count(text: str) -> int | None:
    match = RECORD_COUNT_RE.search(text or "")
    if not match:
        return None
    digits = match.group(1).translate(str.maketrans("０１２３４５６７８９，", "0123456789,"))
    return int(digits.replace(",", ""))


async def result_area_text(page: "Page") -> str:
    result_area = page.locator("div.zone-fund-accounting-pro-list:visible").first
    if not await result_area.count():
        return ""
    return (await result_area.inner_text()).strip()


async def read_record_count(
    page: "Page",
    *,
    previous_result: str = "",
    query_response: dict[str, object] | None = None,
) -> int:
    """读取查询结果工具栏的可见“共计N条”，不依赖导出按钮状态。"""

    count_locator = page.locator(
        'div[class*="pro-toolbar-total-content"]:visible'
    )
    deadline = asyncio.get_running_loop().time() + 30
    response_seen = False
    while asyncio.get_running_loop().time() < deadline:
        current_result = await result_area_text(page)
        for index in range(await count_locator.count()):
            text = (await count_locator.nth(index).inner_text()).strip()
            count = parse_record_count(text)
            if count is not None:
                # 查询前已有旧结果时，必须等结果区域文本刷新；否则会把旧的
                # “共计2条”当成当前筛选结果。接口响应仅用于确认刷新已经完成，
                # 最终数量仍读取页面上的可见“共计N条”。
                if not previous_result or current_result != previous_result:
                    return count
                if (query_response or {}).get("seen") and not response_seen:
                    response_seen = True
                    # response 事件表示本次查询已返回；再给 React 一小段
                    # 时间完成 DOM 提交，最终仍只采信页面可见的记录数。
                    await asyncio.sleep(0.3)
                    continue
                if response_seen:
                    # 查询前后都可能是 0 条；接口响应已完成时，当前可见的
                    # “共计N条”就是本次查询结果，不能再要求结果区文本变化。
                    return count
        await asyncio.sleep(0.25)
    raise RuntimeError("查询后未识别快手结算结果记录数")


@automation_component("kuaishou.settlement.create_export", "快手结算 · 创建导出", category="report")
async def create_export(page: "Page") -> bool:
    previous_result = await result_area_text(page)
    query_response: dict[str, object] = {}

    def capture_query_response(response) -> None:
        if QUERY_API_FRAGMENT in response.url and 200 <= response.status < 300:
            query_response["seen"] = True

    page.on("response", capture_query_response)
    try:
        await page.get_by_role("button", name=QUERY_RE).click()
        record_count = await read_record_count(
            page,
            previous_result=previous_result,
            query_response=query_response,
        )
    finally:
        page.remove_listener("response", capture_query_response)
    print(f"结算查询记录数：{record_count}")
    if record_count == 0:
        print("结算查询无记录，跳过导出")
        return False

    export = page.get_by_role("button", name=EXPORT_RE)
    await export.wait_for(state="visible", timeout=30000)
    enabled_deadline = asyncio.get_running_loop().time() + 30
    while not await export.is_enabled() and asyncio.get_running_loop().time() < enabled_deadline:
        await asyncio.sleep(0.25)
    if not await export.is_enabled():
        raise RuntimeError("结算查询有记录，但导出按钮仍不可用")
    await export.click()
    success = page.get_by_text("导出成功", exact=False)
    await success.last.wait_for(state="visible", timeout=30000)
    know = page.get_by_role("button", name=KNOW_RE)
    if await know.count():
        await know.last.click()
    return True


@automation_component("kuaishou.settlement.wait_ready", "快手结算 · 等待导出记录", category="report")
async def find_export_record(page: "Page", start_value: str, end_value: str):
    target_range = f"{start_value} - {end_value}"
    deadline = asyncio.get_running_loop().time() + 90
    while asyncio.get_running_loop().time() < deadline:
        cards = page.locator("div.zone-fund-accounting-descriptions").filter(
            has_text=target_range
        )
        try:
            await cards.first.wait_for(state="visible", timeout=15000)
            card = cards.first
            download = card.get_by_role("button", name=DOWNLOAD_RE)
            await download.first.wait_for(state="visible", timeout=10000)
            return card
        except Exception:
            pass
        await page.reload(wait_until="domcontentloaded")
    raise RuntimeError(f"结算导出记录未生成：{target_range}")


@automation_component("kuaishou.settlement.workflow", "快手结算 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    business_date: str,
    work_dir: Path | None,
    dest: Path,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="ks_settlement_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    page = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await new_page(browser)
            await page.goto(SETTLEMENT_URL, wait_until="domcontentloaded", timeout=60000)
            ensure_logged_in(page)
            start_date = start_date or business_date
            end_date = end_date or business_date
            start_value, end_value = await choose_range(page, start_date, end_date)
            has_records = await create_export(page)
            print(f"目标结算日期范围：{start_date} ~ {end_date}")
            if not has_records:
                await page.close()
                page = None
                return 0
            await page.goto(EXPORT_URL, wait_until="domcontentloaded", timeout=60000)
            card = await find_export_record(page, start_value, end_value)
            async with page.expect_download(timeout=120000) as download_info:
                await card.get_by_role("button", name=DOWNLOAD_RE).click()
            downloaded = await save_download(
                await download_info.value, actual_work_dir, "kuaishou_settlement.zip"
            )
            print(f"已下载临时文件：{downloaded}")
            source = await asyncio.to_thread(
                prepare_report_file, downloaded, actual_work_dir, (".xlsx", ".csv")
            )
            print(f"已提取结算明细：{source}")
            move_log = await asyncio.to_thread(
                move_report, source, platform, company, shop, REPORT_NAME, end_date, dest
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
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="快手结算单下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--date", default=None, help="单日结算业务日期，格式 YYYY-MM-DD")
    parser.add_argument("--start-date", default=None, help="结算查询起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结算查询结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if args.date and (args.start_date or args.end_date):
        print("--date 不能与 --start-date/--end-date 同时提供", file=sys.stderr)
        return 2
    if bool(args.start_date) != bool(args.end_date):
        print("--start-date 和 --end-date 必须同时提供", file=sys.stderr)
        return 2
    try:
        if args.start_date and args.end_date:
            start_date = validate_business_date(args.start_date)
            end_date = validate_business_date(args.end_date)
            if start_date > end_date:
                print("--start-date 不能晚于 --end-date", file=sys.stderr)
                return 2
            business_date = end_date
        else:
            business_date = validate_business_date(args.date or default_business_date())
            start_date = end_date = business_date
    except ValueError:
        print("日期参数必须为 YYYY-MM-DD", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            run(
                args.cdp, args.platform, args.company, args.shop, business_date,
                Path(args.work_dir) if args.work_dir else None, Path(args.dest),
                start_date=start_date, end_date=end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
