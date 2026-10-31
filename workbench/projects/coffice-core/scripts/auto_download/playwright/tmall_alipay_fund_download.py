# -*- coding: utf-8 -*-
"""登录天猫财务账号并下载、解压、归档支付宝账户资金账单。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, timedelta
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout, async_playwright

from ..move_report import parse_date
from ..extract_report import extract_selected_report, repair_member_name
from .login_extensions.tmall_finance_login import (
    DEFAULT_PASSWORD_ENV,
    DEFAULT_USERNAME,
    ensure_tmall_login,
)

ACCOUNT_INFO_URL = "https://myseller.taobao.com/home.htm/merchant-user-info"
ALIPAY_BIND_URL = "https://passport.taobao.com/ac/alipay_management.htm?fromSite=0&bizcode=taobao"
ALIPAY_BILL_URL = "https://b.alipay.com/page/mbillexprod/bill/download/fundBill"
REPORT_NAME = "支付宝账户资金"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DAY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
MONTH_RE = re.compile(r"(\d{4}-\d{2})(?!-\d{2})")


def extract_business_date(text: str, mode: str) -> str:
    pattern = MONTH_RE if mode == "month" else DAY_RE
    match = pattern.search(text)
    if not match:
        raise RuntimeError(f"首行日期格式无法识别：{text!r}")
    return match.group(1)


def unique_download_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    source = Path(filename)
    for sequence in range(2, 1000):
        candidate = directory / f"{source.stem}_{sequence:03d}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"{directory} 下同名下载文件过多")


@automation_component("file.archive.extract", "解压 / 提取报表文件", category="file")
def run_project_module(arguments: list[str]) -> str:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, "-m", *arguments],
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


def extracted_path_from_log(log: str) -> Path:
    for line in log.splitlines():
        if line.startswith("已提取："):
            return Path(line.split("：", 1)[1].strip())
    raise RuntimeError(f"解压工具未返回目标文件路径：{log}")


@automation_component("tmall.session.open", "天猫 · 获取业务页面", category="browser")
async def find_work_page(browser) -> Page:
    for context in browser.contexts:
        for page in context.pages:
            if page.url.startswith(("https://myseller.taobao.com", "https://loginmyseller.taobao.com")):
                return page
    if not browser.contexts:
        raise RuntimeError("CDP 浏览器中没有可用的上下文")
    return await browser.contexts[0].new_page()


@automation_component("tmall.alipay.open_account", "天猫支付宝资金 · 打开账户信息", category="report")
async def open_account_info(page: Page, shop: str) -> None:
    if "merchant-user-info" in page.url:
        return
    try:
        shop_name = page.locator('div[class*="shopName--"]').filter(has_text=shop).first
        await shop_name.wait_for(state="visible", timeout=30000)
        container = shop_name.locator("xpath=ancestor::div[contains(@class,'container--')][1]")
        await container.hover()
        await page.get_by_text("账号信息", exact=True).click(timeout=10000)
        await page.wait_for_url("**/merchant-user-info", timeout=20000)
    except Exception:
        await page.goto(ACCOUNT_INFO_URL, wait_until="domcontentloaded")
    await page.get_by_text("绑定支付宝", exact=True).wait_for(state="visible", timeout=30000)


@automation_component("tmall.alipay.open_page", "天猫支付宝资金 · 打开支付宝", category="report")
async def open_alipay_page(page: Page) -> tuple[Page, bool]:
    context = page.context
    item = page.locator("div.info-item").filter(has_text="绑定支付宝")
    detail = item.get_by_role("button", name="查看详情", exact=True)
    await detail.wait_for(state="visible", timeout=30000)
    before = set(context.pages)
    created_new_page = False
    try:
        async with context.expect_page(timeout=15000) as page_info:
            await detail.click()
        alipay_page = await page_info.value
        created_new_page = True
    except PlaywrightTimeout:
        new_pages = [candidate for candidate in context.pages if candidate not in before]
        alipay_page = new_pages[-1] if new_pages else page

    if "alipay_management" not in alipay_page.url:
        await alipay_page.goto(ALIPAY_BIND_URL, wait_until="domcontentloaded")
    enter = alipay_page.get_by_text("进入支付宝", exact=True)
    await enter.wait_for(state="visible", timeout=30000)
    await enter.click()
    await alipay_page.wait_for_url(re.compile(r"^https://b\.alipay\.com/"), timeout=60000)
    await alipay_page.wait_for_load_state("domcontentloaded")
    return alipay_page, created_new_page


@automation_component("tmall.alipay.open_bill", "天猫支付宝资金 · 打开账单下载", category="report")
async def open_bill_download(page: Page) -> None:
    if "/bill/download/fundBill" in page.url:
        return
    try:
        await page.get_by_role("link", name="对账中心", exact=True).first.click(timeout=20000)
        await page.wait_for_url("**/mbillexprod/main/index", timeout=30000)
        await page.get_by_role("link", name="账单下载", exact=True).first.click(timeout=20000)
        await page.wait_for_url("**/bill/download/fundBill", timeout=30000)
    except Exception:
        await page.goto(ALIPAY_BILL_URL, wait_until="domcontentloaded")


async def ensure_list_mode(page: Page) -> None:
    rows = page.locator("tr.ant-table-row.ant-table-row-level-0")
    if await rows.count() and await rows.first.is_visible():
        return
    current = page.locator('div[class*="currentBtn"]').filter(has_text="列表模式")
    if await current.count() and await current.first.is_visible():
        return
    controls = page.locator('div[class*="tabRight"]').filter(has_text="列表模式").last
    await controls.wait_for(state="visible", timeout=30000)
    switch = controls.locator('div[class*="defaultBtn"]').filter(has_text="列表模式").first
    if not await switch.count():
        switch = controls.get_by_text("列表模式", exact=False).first
    await switch.wait_for(state="visible", timeout=30000)
    await switch.click()
    await rows.first.wait_for(state="visible", timeout=30000)


@automation_component("tmall.alipay.select_mode", "天猫支付宝资金 · 选择日月模式", category="report")
async def select_bill_mode(page: Page, mode: str) -> None:
    value = "month" if mode == "month" else "day"
    radio = page.locator(f'input[type="radio"][value="{value}"]')
    await radio.wait_for(state="attached", timeout=30000)
    if not await radio.is_checked():
        await radio.check(force=True)


@automation_component("tmall.alipay.wait_ready", "天猫支付宝资金 · 等待账单", category="report")
async def wait_first_downloadable_bill_row(
    page: Page,
    mode: str,
    target_date: str | None = None,
) -> tuple[object, str]:
    if target_date is not None and mode == "day":
        # The live list defaults to only the latest seven days. An exact-date
        # row search must first expand that query through the observed inputs.
        await select_bill_period(page, target_date, target_date)
    deadline = asyncio.get_running_loop().time() + 30
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        rows = page.locator("tr.ant-table-row.ant-table-row-level-0")
        for index in range(await rows.count()):
            row = rows.nth(index)
            date_text = (await row.locator("td").first.inner_text()).strip()
            last_text = date_text
            try:
                business_date = extract_business_date(date_text, mode)
            except RuntimeError:
                continue
            if target_date is not None and business_date != target_date:
                continue
            download_link = row.get_by_text("账单下载", exact=True)
            if await download_link.count() and await download_link.first.is_visible():
                return row, business_date
        await asyncio.sleep(0.5)
    raise RuntimeError(f"等待最新可下载{mode}账单超时，最后读取日期：{last_text!r}")


def bill_days(start_date: str, end_date: str) -> list[str]:
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if start > end or end > date.today():
        raise ValueError("账单日期范围无效或包含未来日期")
    return [(start + timedelta(days=n)).isoformat() for n in range((end-start).days+1)]


async def select_bill_period(page: Page, start_date: str, end_date: str) -> None:
    days = bill_days(start_date, end_date)
    fields = page.locator('input[placeholder="请选择日期"]:visible')
    if await fields.count() != 2:
        raise RuntimeError("无法定位支付宝账单起止日期，未下载其他日期")
    for index, target_date in enumerate((start_date, end_date)):
        await fields.nth(index).fill(target_date)
        await fields.nth(index).press("Enter")
    if [await fields.nth(index).input_value() for index in range(2)] != [start_date, end_date]:
        raise RuntimeError("支付宝账单目标日期未生效，未下载其他日期")
    await page.get_by_role("button", name=re.compile(r"^查\s*询$")).click()
    try:
        await page.wait_for_function(
            "days => { const dates = [...document.querySelectorAll('tr.ant-table-row.ant-table-row-level-0 td:first-child')].map(e => (e.textContent.match(/\\d{4}-\\d{2}-\\d{2}/)||[])[0]); return dates.length > 0 && dates.every(d=>days.includes(d)) && (days.length>10 || days.every(d=>dates.includes(d))); }",
            arg=days, timeout=30000,
        )
    except Exception as exc:
        raise RuntimeError(f"REPORT_NOT_READY：支付宝查询未返回 {start_date} ~ {end_date} 账单") from exc


def extract_batch_reports(archive: Path, destination: Path, start_date: str, end_date: str) -> list[tuple[str, Path]]:
    expected = {day.replace('-', ''): day for day in bill_days(start_date, end_date)}
    members, accounts = {}, set()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = Path(repair_member_name(info.filename, info.flag_bits, 'gbk').replace('\\', '/')).name
            if info.is_dir() or '账务明细' not in name or '(汇总)' in name:
                continue
            match = re.fullmatch(r'(\d+)_(\d{8})_账务明细(?:_\d+)?\.csv', name)
            if not match or match[2] not in expected or match[2] in members or info.file_size <= 0 or info.flag_bits & 1:
                raise RuntimeError('批量包存在日期不符、重复、空或加密明细，已停止归档')
            members[match[2]] = name
            accounts.add(match[1])
    if set(members) != set(expected) or len(accounts) != 1:
        raise RuntimeError('批量包未完整覆盖请求日期或包含多个账户，已停止归档')
    reports = [(expected[day], extract_selected_report(archive, destination, name, '(汇总)', 'gbk'))
               for day, name in sorted(members.items())]
    archive.unlink()
    return reports


@automation_component("file.download", "下载报表文件", category="file")
async def download_zip(page: Page, row, src: Path, *, batch: bool = False) -> Path:
    link = page.get_by_role("button", name="批量下载", exact=True) if batch else row.get_by_text("账单下载", exact=True)
    async with page.expect_download(timeout=120000) as download_info:
        await link.click()
    download = await download_info.value
    filename = download.suggested_filename or "alipay_fund_bill.zip"
    if not filename.lower().endswith(".zip"):
        raise RuntimeError(f"支付宝账单下载文件不是 ZIP：{filename}")
    archive = unique_download_path(src, filename)
    await download.save_as(str(archive))
    return archive


@automation_component("tmall.alipay.workflow", "天猫支付宝资金 · 下载流程", category="workflow")
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
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    temporary = tempfile.TemporaryDirectory(prefix="tmall_alipay_fund_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            seller_page = await find_work_page(browser)
            await ensure_tmall_login(seller_page, username, password_env)
            await open_account_info(seller_page, shop)
            alipay_page, created_new_page = await open_alipay_page(seller_page)
            await open_bill_download(alipay_page)
            await ensure_list_mode(alipay_page)
            await select_bill_mode(alipay_page, mode)
            if start_date and end_date:
                await select_bill_period(alipay_page, start_date, end_date)
                archive = await download_zip(alipay_page, None, actual_work_dir, batch=True)
                reports = await asyncio.to_thread(extract_batch_reports, archive, actual_work_dir, start_date, end_date)
                from ..move_report import archive_report
                for business_date, extracted in reports:
                    target = await asyncio.to_thread(archive_report, extracted, platform, company, shop, REPORT_NAME, business_date, dest)
                    print(f"已批量归档 {business_date}：{target}")
                if created_new_page:
                    await alipay_page.close()
                return 0
            row, business_date = await wait_first_downloadable_bill_row(
                alipay_page, mode, target_date
            )
            parse_date(business_date)
            print(f"目标账单：{business_date}（{'月账单' if mode == 'month' else '日账单'}）")
            archive = await download_zip(alipay_page, row, actual_work_dir)
            print(f"已下载临时 ZIP：{archive}")

            extract_log = await asyncio.to_thread(
                run_project_module,
                [
                    "scripts.auto_download.extract_report",
                    "--archive", str(archive),
                    "--dest", str(actual_work_dir),
                    "--include", "账务明细",
                    "--exclude", "(汇总)",
                    "--filename-encoding", "gbk",
                    "--delete-archive",
                ],
            )
            extracted = extracted_path_from_log(extract_log)
            print(extract_log)

            move_log = await asyncio.to_thread(
                run_project_module,
                [
                    "scripts.auto_download.move_report",
                    "--platform", platform,
                    "--company", company,
                    "--shop", shop,
                    "--report", REPORT_NAME,
                    "--date", business_date,
                    "--src", str(extracted.parent),
                    "--dest", str(dest),
                    "--pattern", extracted.name,
                    "--within", "10",
                ],
            )
            print(move_log)
            if created_new_page:
                await alipay_page.close()
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫支付宝账户资金账单下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login profile 的 wsEndpoint")
    parser.add_argument("--platform", required=True, help="profile note 中的平台")
    parser.add_argument("--company", required=True, help="profile note 中的公司")
    parser.add_argument("--shop", required=True, help="profile note 中的店铺")
    parser.add_argument("--mode", choices=["day", "month"], default="day")
    parser.add_argument("--date", default=None, help="指定日账单日期 YYYY-MM-DD；仅支持 --mode day")
    parser.add_argument("--start-date", help="批量日账单开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", help="批量日账单结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--work-dir", "--src", dest="work_dir", default=None,
        help="ZIP 下载与解压临时目录；默认使用系统临时目录，--src 作为兼容别名",
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
        try:
            parse_date(args.date)
        except ValueError as exc:
            print(f"--date 日期格式错误：{exc}", file=sys.stderr)
            return 2
    try:
        if bool(args.start_date) != bool(args.end_date) or args.start_date and (args.date or args.mode != 'day'):
            raise ValueError("批量日期必须成对指定，且仅支持 --mode day，不能与 --date 同用")
        if args.start_date:
            bill_days(args.start_date, args.end_date)
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
                args.start_date, args.end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
