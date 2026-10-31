# -*- coding: utf-8 -*-
"""下载天猫淘宝联盟最新日或月推广费报表并归档。"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import re
import sys
import tempfile
from pathlib import Path

from .tmall_promotion_download_common import (
    DEFAULT_PASSWORD_ENV,
    DEFAULT_USERNAME,
    move_report,
    open_alimama_page,
    period_label,
    report_period,
    save_download,
)

PROMOTION_REPORT_URL = "https://ad.alimama.com/portal/v2/report/promotionDataPage.htm"
REPORT_NAME = "淘宝联盟推广费"


@automation_component("tmall.union.select_period", "淘宝联盟推广费 · 选择周期", category="report")
async def select_period(page, mode: str, start_date: str | None = None, end_date: str | None = None, month: str | None = None) -> str:
    start, end = report_period(mode, start_date=start_date, end_date=end_date, month=month)
    if mode == "day" and not start_date:
        history_dialog = page.locator(".mux-modal.union-async-down-load-dialog")
        if await history_dialog.count() and await history_dialog.is_visible():
            close_button = history_dialog.get_by_role("button", name="Close")
            await close_button.wait_for(state="visible", timeout=5_000)
            await close_button.evaluate("element => element.click()")
            await history_dialog.wait_for(state="hidden", timeout=5_000)

        yesterday = page.get_by_role("button", name="昨日", exact=True)
        await yesterday.wait_for(state="visible", timeout=30_000)
        # The account profile can have a narrow viewport where this visible
        # toolbar button remains outside the viewport after Playwright scrolls.
        # Dispatch the exact button's click event, then verify the date summary.
        await yesterday.evaluate("element => element.click()")
        await page.wait_for_function(
            """([start, end]) => {
                const text = document.querySelector('.union-top-date-picker-block-date-overview')?.textContent || '';
                return text.includes(start) && text.includes(end);
            }""", arg=[start.isoformat(), end.isoformat()], timeout=30_000,
        )
        return period_label(start, end, mode)
    if mode == "day":
        custom = page.get_by_role("button", name="自定义", exact=True)
        # Re-enter the hover control even when a prior confirmation closed it
        # while the pointer stayed on the same button.
        await page.get_by_role("button", name="昨日", exact=True).hover()
        await custom.hover()
        begin = page.get_by_placeholder("开始日期", exact=True)
        finish = page.get_by_placeholder("结束日期", exact=True)
        # The live range inputs become editable only after focus. Keep the
        # pointer on the trigger so moving across the calendar cannot dismiss it.
        await begin.focus()
        await begin.fill(start.isoformat()); await begin.press("Enter")
        await finish.focus()
        await finish.fill(end.isoformat()); await finish.press("Enter")
        await page.get_by_role("button", name="确定", exact=True).evaluate("element => element.click()")
        overview = page.locator(".union-top-date-picker-block-date-overview")
        await page.wait_for_function(
            """([start, end]) => {
                const text = document.querySelector('.union-top-date-picker-block-date-overview')?.textContent || '';
                return text.includes(start) && text.includes(end);
            }""", arg=[start.isoformat(), end.isoformat()], timeout=30_000,
        )
        text = await overview.inner_text()
        if start.isoformat() not in text or end.isoformat() not in text:
            raise RuntimeError("联盟目标日期范围未生效；已停止导出")
        return period_label(start, end, mode)

    month_button = page.get_by_role("button", name="月", exact=True)
    await month_button.wait_for(state="visible", timeout=30_000)
    await month_button.hover()

    # 悬浮“月”会打开按年分组的月份弹窗。逐年校准后按 title 选中目标月份，
    # 与页面的月份单元格对应（例如 2026-09 即“9月”），避免日历日期格拦截点击。
    month_panel = page.locator(".mux-picker-month-panel")
    await month_panel.wait_for(state="visible", timeout=30_000)
    year_button = month_panel.locator(".mux-picker-year-btn")
    for _ in range(12):
        year_text = await year_button.inner_text()
        year_match = re.search(r"20\d{2}", year_text)
        if year_match is None:
            raise RuntimeError(f"无法识别淘宝联盟月份选择器年份：{year_text}")
        visible_year = int(year_match.group())
        if visible_year == start.year:
            break
        direction = "prev" if visible_year > start.year else "next"
        year_nav = month_panel.locator(f".mux-picker-header-super-{direction}-btn")
        await year_nav.click()
    else:
        raise RuntimeError(f"淘宝联盟月份选择器未能切换到 {start.year} 年")

    month_cell = month_panel.locator(f'td[title="{start:%Y-%m}"]')
    await month_cell.wait_for(state="visible", timeout=10_000)
    await month_cell.click()

    expected_start, expected_end = start.isoformat(), end.isoformat()
    await page.wait_for_function(
        """([start, end]) => {
            const text = document.querySelector(
                '.union-top-date-picker-block-date-overview'
            )?.textContent || '';
            return text.includes(start) && text.includes(end);
        }""",
        arg=[expected_start, expected_end],
        timeout=30_000,
    )
    return period_label(start, end, mode)


async def _first_download_button(page):
    buttons = page.get_by_text("下载报表", exact=True)
    for index in range(await buttons.count()):
        candidate = buttons.nth(index)
        if await candidate.is_visible():
            return candidate
    raise RuntimeError(
        f"未找到可见的“下载报表”按钮：url={page.url}，匹配数量={await buttons.count()}，"
        f"页面文本={((await page.locator('body').inner_text())[:500]).replace(chr(10), ' ')}"
    )


async def _confirm_download_dialog(page) -> None:
    label = page.locator("label.mux-radio-container").filter(has_text="按店铺整体").first
    await label.wait_for(state="visible", timeout=30_000)
    radio = label.locator('input[type="radio"][value="96"]')
    if not await radio.is_checked():
        await label.click()
    dialog = label.locator("xpath=ancestor::*[@role='dialog' or contains(@class,'dialog')][1]")
    confirm = dialog.get_by_role("button", name=re.compile("^(确认|确定)$")).last
    if not await confirm.count():
        confirm = page.get_by_role("button", name=re.compile("^(确认|确定)$")).last
    await confirm.wait_for(state="visible", timeout=30_000)
    await confirm.click()


async def _duplicate_submission_detected(page) -> bool:
    deadline = asyncio.get_running_loop().time() + 8
    while asyncio.get_running_loop().time() < deadline:
        text = await page.locator("body").inner_text()
        if "重复提交任务" in text:
            return True
        await asyncio.sleep(0.25)
    return False


def history_row_matches(text: str, start: str, end: str) -> bool:
    """Require the requested interval, never the first downloadable task."""
    dates = re.findall(r"(?<!\d)(20\d{2})[-/.](\d{2})[-/.](\d{2})(?!\d)", text)
    normalized = ["-".join(value) for value in dates]
    return any(pair == [start, end] for pair in (normalized[i:i + 2] for i in range(len(normalized) - 1)))


def confirmed_period_from_overview(overview: str, start: str, end: str) -> tuple[str, str]:
    dates = re.findall(r"20\d{2}-\d{2}-\d{2}", overview)
    if start == end:
        confirmed = bool(dates) and set(dates) == {start}
    else:
        confirmed = dates == [start, end]
    if not confirmed:
        raise RuntimeError("无法确认淘宝联盟导出期间，已停止下载")
    return start, end


async def _open_history_and_download(page, work_dir: Path, start: str, end: str) -> Path:
    record = page.get_by_text("下载记录", exact=True).last
    await record.wait_for(state="visible", timeout=30_000)
    await record.click()
    rows = page.locator("tr")
    deadline = asyncio.get_running_loop().time() + 120
    while asyncio.get_running_loop().time() < deadline:
        for index in range(1, await rows.count()):
            row = rows.nth(index)
            if not history_row_matches(await row.inner_text(), start, end):
                continue
            download = row.get_by_text("下载", exact=True).last
            if await download.count() and await download.is_visible():
                async with page.expect_download(timeout=60_000) as download_info:
                    await download.click()
                return await save_download(await download_info.value, work_dir, "taobao_union.xlsx")
        await asyncio.sleep(2)
    raise RuntimeError(f"REPORT_NOT_READY：下载记录中未找到可下载的 {start} 至 {end} 报表；未下载其他日期")


@automation_component("tmall.union.download", "淘宝联盟推广费 · 下载报表", category="report")
async def download_report(page, work_dir: Path, expected_start: str, expected_end: str) -> Path:
    overview = await page.locator(".union-top-date-picker-block-date-overview").inner_text()
    start, end = confirmed_period_from_overview(overview, expected_start, expected_end)
    await (await _first_download_button(page)).click()
    download_task = asyncio.create_task(page.wait_for_event("download", timeout=130_000))
    await _confirm_download_dialog(page)
    if await _duplicate_submission_detected(page):
        download_task.cancel()
        try:
            await download_task
        except asyncio.CancelledError:
            pass
        return await _open_history_and_download(page, work_dir, start, end)
    try:
        download = await download_task
    except Exception as exc:
        raise RuntimeError(f"联盟报表等待生成或自动下载超时：{exc}") from exc
    return await save_download(download, work_dir, "taobao_union.xlsx")


@automation_component("tmall.union.workflow", "淘宝联盟推广费 · 下载流程", category="workflow")
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

    temporary = tempfile.TemporaryDirectory(prefix="tmall_taobao_union_") if work_dir is None else None
    actual_work_dir = work_dir or Path(temporary.name)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            page = await open_alimama_page(browser, PROMOTION_REPORT_URL, username, password_env)
            start, end = report_period(mode, start_date=start_date, end_date=end_date, month=month)
            bill_date = await select_period(page, mode, start_date, end_date, month)
            source = await download_report(page, actual_work_dir, start.isoformat(), end.isoformat())
            print(f"已下载淘宝联盟推广费：{source}")
            print(
                await asyncio.to_thread(
                    move_report, source, platform, company, shop, REPORT_NAME, bill_date, dest
                )
            )
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="天猫淘宝联盟推广费下载")
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
