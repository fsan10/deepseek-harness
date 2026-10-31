# -*- coding: utf-8 -*-
"""登录天猫并下载、归档聚合账户资金日汇总或月汇总明细。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
from pathlib import Path

from playwright.async_api import Page, async_playwright

from .login_extensions.tmall_finance_login import ensure_tmall_login
from .tmall_alipay_fund_download import find_work_page, run_project_module, unique_download_path

AGGREGATE_FUND_URL = (
    "https://myseller.taobao.com/home.htm/whale-accountant/pay/capital/home?active=fund_day"
)
REPORT_NAME = "聚合账户资金"
DEFAULT_USERNAME = "mock旗舰店:IT"
DEFAULT_PASSWORD_ENV = "TMALL_IT_LOGIN_PASSWORD"
DAY_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
MONTH_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(?!\d)")


def extract_business_date(text: str, mode: str) -> str:
    pattern = MONTH_RE if mode == "month" else DAY_RE
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"最新{mode}汇总日期格式无法识别：{text!r}")
    return "-".join(match.groups())


@automation_component("tmall.aggregate_fund.select_mode", "天猫聚合资金 · 选择日月模式", category="report")
async def select_mode(page: Page, mode: str) -> None:
    if mode == "month":
        tab = page.locator(".next-tabs-tab-inner").filter(has_text="月汇总").first
        await tab.wait_for(state="visible", timeout=30000)
        await tab.click()
        await page.wait_for_url("**active=fund_month", timeout=30000)
    await page.locator("tr").nth(1).wait_for(state="visible", timeout=30000)


@automation_component("tmall.aggregate_fund.locate", "天猫聚合资金 · 定位最新账单", category="report")
async def latest_downloadable_row(
    page: Page,
    mode: str,
    target_date: str | None = None,
) -> tuple[object, str]:
    deadline = asyncio.get_running_loop().time() + 30
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        rows = page.locator("tr")
        for index in range(1, await rows.count()):
            row = rows.nth(index)
            cells = row.locator("td")
            if not await cells.count():
                continue
            date_text = (await cells.first.inner_text()).strip()
            last_text = date_text
            try:
                business_date = extract_business_date(date_text, mode)
            except RuntimeError:
                continue
            if target_date is not None and business_date != target_date:
                continue
            link = row.get_by_text("下载明细", exact=True)
            if await link.count() and await link.first.is_visible():
                return row, business_date
        await asyncio.sleep(0.5)
    raise RuntimeError(f"等待最新可下载{mode}汇总超时，最后读取日期：{last_text!r}")


@automation_component("file.download", "下载报表文件", category="file")
async def download_report(page: Page, row: object, work_dir: Path) -> Path:
    link = row.get_by_text("下载明细", exact=True)
    async with page.expect_download(timeout=120000) as download_info:
        await link.first.click()
    download = await download_info.value
    filename = download.suggested_filename or "tmall_aggregate_fund.xlsx"
    target = unique_download_path(work_dir, filename)
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"聚合账户资金下载文件为空：{target}")
    return target


@automation_component("tmall.aggregate_fund.workflow", "天猫聚合资金 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    mode: str,
    target_date: str | None,
    work_dir: Path | None,
    dest: Path,
    username: str,
    password_env: str,
) -> int:
    temporary = tempfile.TemporaryDirectory(prefix="tmall_aggregate_fund_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await find_work_page(browser)
            await ensure_tmall_login(page, username, password_env)
            await page.goto(AGGREGATE_FUND_URL, wait_until="domcontentloaded")
            await select_mode(page, mode)
            row, business_date = await latest_downloadable_row(page, mode, target_date)
            print(f"目标汇总：{business_date}（{'月汇总' if mode == 'month' else '日汇总'}）")
            downloaded = await download_report(page, row, actual_work_dir)
            print(f"已下载临时文件：{downloaded}")

            move_log = await asyncio.to_thread(
                run_project_module,
                [
                    "scripts.auto_download.move_report",
                    "--platform", platform,
                    "--company", company,
                    "--shop", shop,
                    "--report", REPORT_NAME,
                    "--date", business_date,
                    "--src", str(downloaded.parent),
                    "--dest", str(dest),
                    "--pattern", downloaded.name,
                    "--within", "10",
                ],
            )
            print(move_log)
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫聚合账户资金明细下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login profile 的 wsEndpoint")
    parser.add_argument("--platform", required=True, help="profile note 中的平台")
    parser.add_argument("--company", required=True, help="profile note 中的公司")
    parser.add_argument("--shop", required=True, help="profile note 中的店铺")
    parser.add_argument("--mode", choices=("day", "month"), default="day")
    parser.add_argument("--date", default=None, help="指定日汇总日期 YYYY-MM-DD；仅支持 --mode day")
    parser.add_argument(
        "--work-dir", "--src", dest="work_dir", default=None,
        help="下载临时目录；默认使用系统临时目录，--src 作为兼容别名",
    )
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data", help="归档根目录")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    args = parser.parse_args()

    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if args.date is not None:
        if args.mode != "day":
            print("--date 仅支持与 --mode day 一起使用", file=sys.stderr)
            return 2
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            print("--date 必须为 YYYY-MM-DD", file=sys.stderr)
            return 2
    try:
        return asyncio.run(
            run(
                args.cdp,
                args.platform,
                args.company,
                args.shop,
                args.mode,
                args.date,
                Path(args.work_dir) if args.work_dir else None,
                Path(args.dest),
                args.username,
                args.password_env,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
