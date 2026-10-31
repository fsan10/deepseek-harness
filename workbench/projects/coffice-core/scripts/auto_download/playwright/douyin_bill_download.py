# -*- coding: utf-8 -*-
"""抖店账单报表下载脚本（Playwright + Cloak Login CDP）。

流程：账单管理 -> 结算账单/资金账单 -> 日汇总/月汇总 -> 按日期行或指定范围批量生成报表
-> 弹窗生成 -> 跳转历史报表 -> 第一张卡可下载后点下载 -> 剪切重命名到 data 目录。

参数（platform/company/shop 取自 profile note 键值对）：
    --cdp        Cloak Login start_profile 返回的 wsEndpoint（必填）
    --platform   平台中文名（如 抖音）
    --company    公司全称（半角括号，与 note 一致）
    --shop       店铺名
    --report     报表类型：结算/资金（默认结算），同时决定目标子目录
    --mode       汇总模式：day（日汇总，默认）/ month（月汇总）
    --start-date/--end-date  指定日汇总日期范围，查询后批量生成一份区间报表
    --src        浏览器下载目录，默认 C:\\Users\\win\\Downloads
    --dest       目标根目录，默认 C:\\Users\\win\\Desktop\\data
    --pattern    源文件匹配模式，默认 DL*

报表类型目标子目录始终使用注册表标准名称“结算/资金”；日/月粒度仅由日期前缀区分。
文件命名：YYYYMMDD_平台_公司_店铺_报表类型.ext（日）或 YYYYMM_...（月）。

示例：
    python -m scripts.auto_download.playwright.douyin_bill_download \
        --cdp ws://127.0.0.1:xxxx/devtools/browser/xxx \
        --platform 抖音 --company "墨客咖时(南京)生物科技有限公司" --shop "MOCK官方旗舰店" \
        --report 结算 --mode day

退出码：0=成功；1=执行失败；2=参数错误。
"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import sys
import tempfile
from datetime import date
from pathlib import Path

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from ..move_report import archive_report, parse_date
from .douyin_login import find_or_create_douyin_page, goto_with_douyin_login

BILL_URL = "https://fxg.jinritemai.com/ffa/fxg-bill/fund-detail-bill"
HISTORY_URL = "https://fxg.jinritemai.com/ffa/fxg-bill/history-report"
REPORT_START_SEL = 'input[placeholder="开始日期"], input[placeholder="开始时间"]'
REPORT_END_SEL = 'input[placeholder="结束日期"], input[placeholder="结束时间"]'


async def archive_download(download, dest: Path, platform: str, company: str, shop: str,
                           report: str, business_date: str, *, period_start=None, period_end=None) -> Path:
    """Use the shared validated receipt path for Playwright-managed downloads."""
    suffix = Path(download.suggested_filename).suffix or '.csv'
    cache = dest / '.automation_cache' / 'douyin_bill'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        source = Path(directory) / ('download' + suffix)
        await download.save_as(str(source))
        return await asyncio.to_thread(
            archive_report, source, platform, company, shop, report, business_date, dest,
            period_start=period_start, period_end=period_end,
        )

async def click_tab(page, text: str) -> None:
    await page.get_by_role("tab", name=text, exact=True).click(timeout=10000)


async def _visible_report_date_input(page, *, end: bool = False):
    locator = page.locator(REPORT_END_SEL if end else REPORT_START_SEL).filter(visible=True)
    return locator.first if await locator.count() else None


@automation_component("douyin.bill.set_date", "抖音账单 · 设置日期范围", category="report")
async def set_report_date_range(page, start_date: str, end_date: str) -> None:
    """Fill the bill page's editable date range and submit the filter."""

    async def replace_value(value: str, *, end: bool) -> None:
        field = await _visible_report_date_input(page, end=end)
        if field is None:
            raise RuntimeError("抖店账单页未找到可见的开始/结束日期输入框")
        # The date component is controlled and re-renders while editing.  A
        # Playwright fill can be immediately overwritten by that re-render;
        # use the same focused keyboard path as the live DOM interaction.
        await field.click(timeout=10_000)
        await field.press("Control+A")
        await field.press("Backspace")
        await field.type(value, delay=35)

    await replace_value(start_date, end=False)
    await replace_value(end_date, end=True)
    start = await _visible_report_date_input(page)
    end = await _visible_report_date_input(page, end=True)
    if start is None or end is None:
        raise RuntimeError("抖店账单页日期输入框在重渲染后消失")
    start_value = await start.input_value()
    end_value = await end.input_value()
    if start_value != start_date or end_value != end_date:
        raise RuntimeError(
            f"抖店账单日期填写失败：{start_value!r} ~ {end_value!r}"
        )
    query = page.get_by_role("button", name="查询", exact=True).filter(visible=True).last
    await query.click(timeout=10_000)
    await asyncio.sleep(1.0)


@automation_component("douyin.bill.generate", "抖音账单 · 生成批量报表", category="report")
async def click_batch_download_and_generate(page) -> None:
    """Generate one report for the already-submitted custom date range."""
    batch = page.get_by_role("button", name="批量下载", exact=True).last
    await batch.wait_for(state="visible", timeout=10_000)
    await batch.click()

    popover = page.locator(".aurora-popover-container:visible").filter(has_text="生成报表").last
    generate = popover.get_by_role("button", name="生成", exact=True)
    if await generate.count() == 0:
        generate = page.get_by_role("button", name="生成", exact=True).last
    await generate.wait_for(state="visible", timeout=10_000)
    await generate.click()


async def wait_first_row(page) -> None:
    await page.locator(".aurora-table-row:visible").first.wait_for(state="visible", timeout=30000)


async def first_row_date(page) -> str:
    cell = await page.locator(".aurora-table-row:visible").first.locator("td").first.inner_text()
    return cell.strip()


async def row_for_date(page, target_date: str):
    """Find the visible daily-summary row whose first cell is target_date."""

    expected = parse_date(target_date)
    rows = page.locator(".aurora-table-row:visible")
    for index in range(await rows.count()):
        row = rows.nth(index)
        value = (await row.locator("td").first.inner_text()).strip()
        try:
            if parse_date(value) == expected:
                return row, value
        except ValueError:
            continue
    raise RuntimeError(f"日汇总中未找到目标日期：{target_date}")


async def click_row_download(row) -> None:
    btn = row.get_by_role("button", name="下载明细", exact=True)
    if await btn.count() == 0:
        btn = row.get_by_role("button", name="生成报表", exact=True)
    await btn.first.click(timeout=10000)


async def click_first_row_download(page) -> None:
    await click_row_download(page.locator(".aurora-table-row:visible").first)


@automation_component("douyin.bill.wait_ready", "抖音账单 · 等待报表就绪", category="report")
async def wait_report_ready(page, timeout: float = 900.0, refresh_interval: float = 30.0) -> None:
    end = asyncio.get_event_loop().time() + timeout
    next_refresh = asyncio.get_event_loop().time() + refresh_interval
    while asyncio.get_event_loop().time() < end:
        card = page.locator(".reportCard-GbHGPv:visible").first
        if await card.count() == 0:
            await page.reload()
            await page.wait_for_selector(".reportCard-GbHGPv", timeout=30000)
            next_refresh = asyncio.get_event_loop().time() + refresh_interval
            continue
        tag = card.locator(".aurora-tag")
        text = (await tag.inner_text()).strip() if await tag.count() else ""
        if text == "可下载":
            return
        now = asyncio.get_event_loop().time()
        if now >= next_refresh:
            await page.reload()
            await page.wait_for_selector(".reportCard-GbHGPv", timeout=30000)
            next_refresh = asyncio.get_event_loop().time() + refresh_interval
        else:
            await asyncio.sleep(5)
    raise RuntimeError("报表生成超时，未变为可下载状态")


async def existing_names(src: Path, pattern: str) -> set[str]:
    return {p.name for p in src.glob(pattern) if p.is_file()}


async def wait_download_file(src: Path, pattern: str, baseline: set[str],
                             timeout: float = 180.0) -> Path:
    end = asyncio.get_event_loop().time() + timeout
    last_size = -1
    stable = 0
    while asyncio.get_event_loop().time() < end:
        candidates = [p for p in src.glob(pattern) if p.is_file() and p.name not in baseline]
        if not candidates:
            await asyncio.sleep(2)
            continue
        source = max(candidates, key=lambda p: p.stat().st_mtime)
        size = source.stat().st_size
        if size == last_size and size > 0:
            stable += 1
        else:
            stable = 0
        last_size = size
        if stable >= 3:
            return source
        await asyncio.sleep(2)
    raise RuntimeError("等待下载文件完成超时")


@automation_component("douyin.bill.download", "抖音账单 · 下载报表", category="report")
async def download_one(
    page,
    platform: str,
    company: str,
    shop: str,
    report: str,
    mode: str,
    src: Path,
    dest: Path,
    pattern: str,
    target_date: str | None = None,
    filter_start_date: str | None = None,
    filter_end_date: str | None = None,
) -> None:
    """Generate, wait for, download and archive one daily/monthly report."""

    await goto_with_douyin_login(
        page,
        BILL_URL,
        shop,
        platform=platform,
        company=company,
    )
    await page.wait_for_selector(".auxo-tabs-nav", timeout=30000)

    report_tab = "结算账单" if report == "结算" else "资金账单"
    bill_path = (
        "/ffa/fxg-bill/settlement-detail-bill"
        if report == "结算"
        else "/ffa/fxg-bill/fund-detail-bill"
    )
    # BILL_URL opens the default funds page.  When the requested report is
    # already selected, clicking the active tab does not navigate, so waiting
    # for a URL event would time out even though the page is ready.
    if bill_path not in page.url.split("?", 1)[0]:
        await click_tab(page, report_tab)
        try:
            await page.wait_for_url(
                f"**{bill_path}", wait_until="commit", timeout=15000
            )
        except PlaywrightTimeout:
            # The platform can reach the target URL while delaying the load
            # event.  Trust the concrete URL only after confirming navigation
            # reached the requested bill page; otherwise preserve the failure.
            if bill_path not in page.url.split("?", 1)[0]:
                raise

    sub_tab = "月汇总" if mode == "month" else "日汇总"
    await click_tab(page, sub_tab)
    if filter_start_date is not None:
        if filter_end_date is None:
            raise ValueError("账单日期范围缺少结束日期")
        await set_report_date_range(page, filter_start_date, filter_end_date)
        date_compact = parse_date(filter_end_date)
        print(f"目标范围：{filter_start_date} ~ {filter_end_date}（{report}{mode}汇总）")
        await click_batch_download_and_generate(page)
    else:
        await wait_first_row(page)
        if target_date is None:
            row = page.locator(".aurora-table-row:visible").first
            date_text = await first_row_date(page)
        else:
            row, date_text = await row_for_date(page, target_date)
        date_compact = parse_date(date_text)
        print(f"目标行：{date_text}（{report}{mode}）")

        await click_row_download(row)
        gen = page.get_by_role("button", name="生成", exact=True)
        await gen.wait_for(state="visible", timeout=10_000)
        await gen.click()

    try:
        await page.wait_for_url("**/ffa/fxg-bill/history-report", timeout=30000)
    except PlaywrightTimeout:
        pass
    if "history-report" not in page.url:
        await page.goto(HISTORY_URL)
        await page.wait_for_selector(".reportCard-GbHGPv", timeout=30000)

    print("等待报表生成（可下载）...")
    await wait_report_ready(page)

    card = page.locator(".reportCard-GbHGPv:visible").first
    dl_btn = card.get_by_role("button", name="下载", exact=True).first
    try:
        async with page.expect_download(timeout=180000) as dl_info:
            await dl_btn.evaluate("el => el.click()")
        download = await dl_info.value
        # Save the Playwright download before using the shared archive/receipt
        # path, exactly as the other report modules do.
        target = await archive_download(download, dest, platform, company, shop, report, date_compact,
                                        period_start=filter_start_date, period_end=filter_end_date)
    except PlaywrightTimeout:
        baseline = await existing_names(src, pattern)
        await dl_btn.evaluate("el => el.click()")
        source = await wait_download_file(src, pattern, baseline)
        target = await asyncio.to_thread(
            archive_report, source, platform, company, shop, report, date_compact, dest,
            period_start=filter_start_date, period_end=filter_end_date,
        )
    print(f"已下载：{target}")


@automation_component("douyin.bill.workflow", "抖音账单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    report: str,
    mode: str,
    src: Path,
    dest: Path,
    pattern: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    if (start_date is None) != (end_date is None):
        raise ValueError("--start-date 与 --end-date 必须同时提供")
    if start_date is None:
        start_target = end_target = None
    else:
        start_target = date.fromisoformat(start_date)
        end_target = date.fromisoformat(end_date or "")
        if start_target > end_target:
            raise ValueError("--start-date 不能晚于 --end-date")
        if mode != "day":
            raise ValueError("自定义日期范围只支持 --mode day")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        page, _ = await find_or_create_douyin_page(browser)
        await download_one(
            page, platform, company, shop, report, mode, src, dest, pattern,
            None,
            start_target.isoformat() if start_target else None,
            end_target.isoformat() if end_target else None,
        )
        await browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="抖店账单报表下载（Playwright + Cloak Login CDP）")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--platform", required=True, help="平台中文名")
    parser.add_argument("--company", required=True, help="公司全称")
    parser.add_argument("--shop", required=True, help="店铺名")
    parser.add_argument("--report", default="结算", choices=["结算", "资金"], help="报表类型")
    parser.add_argument("--mode", default="day", choices=["day", "month"], help="day=日汇总 / month=月汇总")
    parser.add_argument("--src", default=r"C:\Users\win\Downloads", help="浏览器下载目录")
    parser.add_argument("--dest", default=r"C:\Users\win\Desktop\data", help="目标根目录")
    parser.add_argument("--pattern", default="DL*", help="源文件匹配模式")
    parser.add_argument("--start-date", default=None, help="自定义日汇总开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义日汇总结束日期，格式 YYYY-MM-DD")
    args = parser.parse_args()

    if not any(args.cdp.startswith(prefix) for prefix in ("ws://", "wss://")):
        print(f"--cdp 格式错误：{args.cdp}（应为 ws:// 开头的 wsEndpoint）", file=sys.stderr)
        return 2
    if (args.start_date is None) != (args.end_date is None):
        print("--start-date 与 --end-date 必须同时提供", file=sys.stderr)
        return 2
    if args.start_date is not None and args.end_date is not None:
        try:
            start_target = date.fromisoformat(args.start_date)
            end_target = date.fromisoformat(args.end_date)
        except ValueError as exc:
            print(f"自定义日期格式错误：{exc}", file=sys.stderr)
            return 2
        if start_target > end_target:
            print("--start-date 不能晚于 --end-date", file=sys.stderr)
            return 2
        if args.mode != "day":
            print("自定义日期范围只支持 --mode day", file=sys.stderr)
            return 2
    try:
        return asyncio.run(
            run(
                args.cdp, args.platform, args.company, args.shop,
                args.report, args.mode, Path(args.src), Path(args.dest), args.pattern,
                args.start_date, args.end_date,
            )
        )
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
