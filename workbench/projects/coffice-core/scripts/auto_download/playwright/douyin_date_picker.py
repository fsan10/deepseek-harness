# -*- coding: utf-8 -*-
"""抖店订单管理页 日期区间选择（Playwright 通过 CDP 驱动 Cloak Login 已启动的 profile）。

用法（仓库根目录）：
    # 先启动 Cloak Login profile 并进入抖店订单管理页
    # --cdp 来自 start_profile 返回的 wsEndpoint
    python -m scripts.auto_download.playwright.douyin_date_picker --cdp ws://127.0.0.1:63055/devtools/browser/xxx --start 2026-06-01 --end 2026-06-02
    # 可选 --url 指定订单管理页地址（默认 https://fxg.jinritemai.com/ffa/morder/order/list）

流程（与 .codex/skills/douyin-order-date-range 一致）：
    同月区间只用左面板点起始/结束日期；跨月区间左面板点起始、右面板切到结束月点结束；
    随后点确定、点查询，输出"共N条"。

退出码：0=成功；1=执行失败；2=参数/连接错误。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from .douyin_order_common import (
    END_SEL,
    PANEL_SEL as COMMON_PANEL_SEL,
    START_SEL,
    click_query_and_wait,
    fill_date_range,
)

ORDER_LIST_URL = "https://fxg.jinritemai.com/ffa/morder/order/list"
# 保留旧的独立调试函数，但与正式脚本共用新旧页面选择器；实际运行的
# fill_date_range/open_date_picker 来自 douyin_order_common。
PANEL_SEL = COMMON_PANEL_SEL
HEADER_SEL = ".auxo-picker-header-view"
PREV_BTN = ".auxo-picker-header-prev-btn"
NEXT_BTN = ".auxo-picker-header-next-btn"
CELL_SEL = 'td.auxo-picker-cell[title="{date}"]'
OK_BTN = ".auxo-picker-dropdown button.sp-picker-range-ok-btn"
QUERY_BTN = "#order-list-submit-btn"
TOTAL_SEL = ".index_selectedPrompt__si2uH"


def parse_ym(text: str) -> tuple[int, int]:
    m = re.match(r"(\d{4})年(\d{1,2})月", text)
    if not m:
        raise RuntimeError(f"无法解析面板月份文本：{text!r}")
    return (int(m.group(1)), int(m.group(2)))


async def panel_headers(page) -> list[str]:
    loc = page.locator(PANEL_SEL)
    return [await loc.nth(i).locator(HEADER_SEL).inner_text() for i in range(await loc.count())]


async def wait_panel_ready(page, timeout: float = 10.0) -> list[str]:
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        headers = await panel_headers(page)
        if len(headers) >= 2:
            return headers
        await asyncio.sleep(0.15)
    raise RuntimeError("日期弹层未打开或面板不足两个")


async def open_picker(page) -> None:
    try:
        await page.click(START_SEL, timeout=4000)
    except PlaywrightTimeout:
        await page.locator(START_SEL).focus()
        await page.keyboard.press("Space")
    await wait_panel_ready(page)


async def switch_panel_month(page, idx: int, target_ym: tuple[int, int], max_steps: int = 24) -> None:
    for _ in range(max_steps):
        headers = await panel_headers(page)
        cur = parse_ym(headers[idx].strip())
        if cur == target_ym:
            return
        btn = PREV_BTN if cur > target_ym else NEXT_BTN
        before = headers[idx]
        panel = page.locator(PANEL_SEL).nth(idx)
        await panel.locator(btn).evaluate("el => el.click()")
        for _ in range(40):
            await asyncio.sleep(0.1)
            headers = await panel_headers(page)
            if len(headers) > idx and headers[idx].strip() != before:
                break
    raise RuntimeError(f"面板{idx}无法切换到 {target_ym[0]}年{target_ym[1]}月")


async def click_date(page, idx: int, date_str: str) -> None:
    cell = page.locator(PANEL_SEL).nth(idx).locator(CELL_SEL.format(date=date_str))
    await cell.click(timeout=5000)


async def click_ok(page) -> None:
    await page.locator(OK_BTN).click(timeout=5000)
    try:
        await page.locator(".auxo-picker-dropdown").wait_for(state="hidden", timeout=8000)
    except PlaywrightTimeout:
        await asyncio.sleep(0.5)
        if await page.locator(".auxo-picker-dropdown .auxo-picker-panel").count():
            raise RuntimeError("点击确定后日期弹层未关闭")


async def fill_and_query(page, start_date: str, end_date: str) -> str:
    start_ym = tuple(int(x) for x in start_date.split("-")[:2])
    end_ym = tuple(int(x) for x in end_date.split("-")[:2])

    await open_picker(page)
    headers = await wait_panel_ready(page)
    print(f"面板月份：左={headers[0].strip()} 右={headers[1].strip()}")

    if start_ym == end_ym:
        await switch_panel_month(page, 0, start_ym)
        await click_date(page, 0, start_date)
        await click_date(page, 0, end_date)
    else:
        await switch_panel_month(page, 0, start_ym)
        await click_date(page, 0, start_date)
        await switch_panel_month(page, 1, end_ym)
        await click_date(page, 1, end_date)

    await click_ok(page)

    start_val = await page.locator(START_SEL).input_value()
    end_val = await page.locator(END_SEL).filter(visible=True).first.input_value()
    expected_start = start_date.replace("-", "/") + " 00:00:00"
    expected_end = end_date.replace("-", "/") + " 23:59:59"
    if start_val != expected_start or end_val != expected_end:
        raise RuntimeError(f"提交值不符：开始={start_val!r} 结束={end_val!r}")
    print(f"日期已提交：{start_val} ~ {end_val}")

    el = page.locator(TOTAL_SEL)
    old = (await el.inner_text()).strip() if await el.count() and await el.is_visible() else ""
    await page.click(QUERY_BTN)
    end = asyncio.get_event_loop().time() + 30
    total = ""
    while asyncio.get_event_loop().time() < end:
        if await el.count() and await el.is_visible():
            text = (await el.inner_text()).strip()
            if text.startswith("共") and "条" in text and text != old:
                total = text
                break
        await asyncio.sleep(0.5)
    if not total:
        raise RuntimeError("查询后未读到结果条数（总数文本未变化）")
    return total


async def run(cdp_url: str, start_date: str, end_date: str, url: str | None) -> int:
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "/ffa/morder/order/list" in pg.url:
                    page = pg
                    break
            if page:
                break
        if page is None:
            ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await ctx.new_page()
            await page.goto(url or ORDER_LIST_URL)
            await page.wait_for_selector(START_SEL, timeout=30000)
        else:
            await page.bring_to_front()
        print(f"页面：{await page.title()} | {page.url}")
        # 订单下载脚本和本调试脚本共用同一日期组件实现；本命令仍保留
        # 自定义起止日期参数，方便回归同月/跨月面板联动行为。
        await fill_date_range(page, start_date, end_date)
        await click_query_and_wait(page)
        total_locator = page.locator(TOTAL_SEL)
        total = (await total_locator.inner_text()).strip() if await total_locator.count() else "查询完成"
        print(f"查询结果：{total}")
        await browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="抖店订单管理页日期区间选择（Playwright + Cloak Login CDP）")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--url", default=None, help="订单管理页地址（默认官方地址）")
    args = parser.parse_args()

    for name, value in (("--start", args.start), ("--end", args.end)):
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            print(f"{name} 日期格式错误：{value}（要求 YYYY-MM-DD）", file=sys.stderr)
            return 2
    try:
        return asyncio.run(run(args.cdp, args.start, args.end, args.url))
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
