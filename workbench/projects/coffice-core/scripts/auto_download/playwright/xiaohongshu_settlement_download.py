# -*- coding: utf-8 -*-
"""下载小红书最新日/月结算账单并归档为单份结算文件。"""

from __future__ import annotations

from scripts.auto_download.move_report import archive_report

from .component_runtime import automation_component

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from .xiaohongshu_download_common import (
    click_compat,
    latest_bill_row,
    open_report_page,
    save_download,
    select_bill_mode,
    validate_settlement_report,
)

SETTLEMENT_URL = "https://ark.xiaohongshu.com/app-finance/bill/settle/daily"
SETTLEMENT_REPORT_NAME = "结算"


@automation_component("xhs.settlement.workflow", "小红书结算 · 下载流程", category="workflow")
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

    temporary = tempfile.TemporaryDirectory(prefix="xhs_settlement_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    page = None
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            page = await open_report_page(browser.contexts[0], SETTLEMENT_URL)
            await select_bill_mode(page, mode)
            row, business_date = await latest_bill_row(page, mode, target_date)
            print(f"目标结算日期：{business_date}（{'月度汇总单' if mode == 'month' else '日账单'}）")
            async with page.expect_download(timeout=120_000) as download_info:
                await click_compat(row.get_by_text("下载账单", exact=True))
            source = await save_download(
                await download_info.value, actual_work_dir, "xiaohongshu_settlement.xlsx"
            )
            await asyncio.to_thread(validate_settlement_report, source)
            print(f"已下载结算账单：{source}")
            print(
                await asyncio.to_thread(
                    archive_report,
                    source,
                    platform,
                    company,
                    shop,
                    SETTLEMENT_REPORT_NAME,
                    business_date,
                    dest,
                )
            )
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
    parser = argparse.ArgumentParser(description="小红书结算账单下载")
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
