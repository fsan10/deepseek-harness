# -*- coding: utf-8 -*-
"""下载天猫万相台最新日或月推广费明细并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from .tmall_promotion_download_common import (
    DEFAULT_PASSWORD_ENV,
    DEFAULT_USERNAME,
    click_and_capture_download,
    ensure_wanxiangtai_booking_time,
    move_report,
    open_alimama_page,
    period_label,
    report_period,
    save_download,
    wanxiangtai_url,
)

REPORT_NAME = "万相台推广费"


@automation_component("tmall.wanxiangtai.download", "万相台推广费 · 下载报表", category="report")
async def download_report(page, work_dir: Path) -> Path:
    await ensure_wanxiangtai_booking_time(page)
    button = page.get_by_text("下载数据", exact=True).last
    await button.wait_for(state="visible", timeout=60_000)
    download = await click_and_capture_download(page, button.click)
    return await save_download(download, work_dir, "wanxiangtai_promotion.xlsx")


@automation_component("tmall.wanxiangtai.workflow", "万相台推广费 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    mode: str,
    work_dir: Path | None,
    dest: Path,
    username: str,
    password_env: str,
    start_date: str | None = None,
    end_date: str | None = None,
    month: str | None = None,
) -> int:
    from playwright.async_api import async_playwright

    temporary = tempfile.TemporaryDirectory(prefix="tmall_wanxiangtai_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    try:
        start, end = report_period(mode, start_date=start_date, end_date=end_date, month=month)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await open_alimama_page(browser, wanxiangtai_url(start, end), username, password_env)
            source = await download_report(page, actual_work_dir)
            print(f"已下载万相台推广费：{source}")
            print(
                await asyncio.to_thread(
                    move_report,
                    source,
                    platform,
                    company,
                    shop,
                    REPORT_NAME,
                    period_label(start, end, mode),
                    dest,
                )
            )
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫万相台推广费下载")
    parser.add_argument("--cdp", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--mode", choices=("day", "month"), default="day")
    parser.add_argument("--start-date", help="指定开始业务日期YYYY-MM-DD")
    parser.add_argument("--end-date", help="指定结束业务日期YYYY-MM-DD")
    parser.add_argument("--month", help="指定完整业务月份YYYY-MM，配合--mode month")
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    try:
        return asyncio.run(
            run(
                args.cdp, args.platform, args.company, args.shop, args.mode,
                Path(args.work_dir) if args.work_dir else None, Path(args.dest),
                args.username, args.password_env, args.start_date, args.end_date, args.month,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 2 if getattr(exc, 'requires_human', False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
