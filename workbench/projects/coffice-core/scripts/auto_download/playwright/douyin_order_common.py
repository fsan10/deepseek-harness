# -*- coding: utf-8 -*-
"""抖店订单页的共享日期与查询操作。

订单页存在新版/旧版 A/B 组件。这里只保留与日期范围和查询有关的
Playwright 操作，订单导出及下载验证由具体脚本负责。
"""

from __future__ import annotations

import asyncio
import random
import re
from datetime import date, timedelta

from playwright.async_api import TimeoutError as PlaywrightTimeout

ORDER_LIST_URL = "https://fxg.jinritemai.com/ffa/morder/order/list"
START_SEL = 'input[placeholder="开始时间"], input[placeholder="开始范围"]'
END_SEL = 'input[placeholder="结束时间"], input[placeholder="结束范围"]'
# 新页面会额外渲染一个可见的无 header 容器；只把真正包含月份 header
# 的两个日历面板纳入操作，避免读取不存在的第三个 header 超时。
PANEL_SEL = ".auxo-picker-dropdown .auxo-picker-panel:visible:has(.auxo-picker-header-view)"
HEADER_SEL = ".auxo-picker-header-view"
PREV_BTN = ".auxo-picker-header-prev-btn"
NEXT_BTN = ".auxo-picker-header-next-btn"
CELL_SEL = 'td.auxo-picker-cell[title="{date}"]'
OK_BTN = ".auxo-picker-dropdown button.sp-picker-range-ok-btn"
SHORTCUT_LABELS = (
    "近一个月", "近1个月", "最近一个月", "近30日", "近30天", "最近30天", "近30天内", "近三十天",
)


async def _visible_date_input(page, *, end: bool = False):
    """返回当前筛选区真正可见的日期输入框。

    新版订单页使用「开始范围/结束范围」，旧版仍使用「开始时间/结束时间」。
    优先选择新版节点，避免页面同时保留旧版隐藏或不可交互节点。
    """

    placeholders = ("结束范围", "结束时间") if end else ("开始范围", "开始时间")
    for placeholder in placeholders:
        locator = page.locator(f'input[placeholder="{placeholder}"]').filter(visible=True)
        if await locator.count():
            return locator.first
    return None


def near_thirty_days(*, today: date | None = None) -> tuple[str, str]:
    """返回抖店“近30日”的日期范围。

    抖店快捷项的实际口径是结束日往前 30 天（含结束日共 31 个日期），
    例如 2026-08-25 对应 2026-07-26 ~ 2026-08-25；这里必须与页面快捷项
    保持一致，不能按普通“含今天共 30 天”使用 29 天偏移。
    """

    end = today or date.today()
    start = end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


def parse_ym(text: str) -> tuple[int, int]:
    match = re.search(r"(\d{4})年(\d{1,2})月", text)
    if not match:
        raise RuntimeError(f"无法解析日期面板月份：{text!r}")
    return int(match.group(1)), int(match.group(2))


async def _panel_headers(page) -> list[str]:
    panels = page.locator(PANEL_SEL)
    return [
        (await panels.nth(index).locator(HEADER_SEL).inner_text()).strip()
        for index in range(await panels.count())
    ]


async def _wait_panels(page, timeout: float = 10.0) -> list[str]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        headers = await _panel_headers(page)
        if len(headers) >= 2:
            return headers
        await asyncio.sleep(0.15)
    raise RuntimeError("抖店日期弹层未打开或面板不足两个")


async def _switch_panel_month(page, index: int, target: tuple[int, int]) -> None:
    for _ in range(24):
        headers = await _panel_headers(page)
        if len(headers) <= index:
            raise RuntimeError("抖店日期弹层面板数量发生变化")
        current = parse_ym(headers[index])
        if current == target:
            return
        button = PREV_BTN if current > target else NEXT_BTN
        before = headers[index]
        panel = page.locator(PANEL_SEL).nth(index)
        await panel.locator(button).evaluate("element => element.click()")
        for _ in range(40):
            await asyncio.sleep(0.1)
            after = await _panel_headers(page)
            if len(after) > index and after[index] != before:
                break
    raise RuntimeError(f"日期面板无法切换到 {target[0]}年{target[1]}月")


async def _click_date(page, index: int, value: str) -> None:
    cell = page.locator(PANEL_SEL).nth(index).locator(CELL_SEL.format(date=value))
    await cell.click(timeout=5_000)


async def open_date_picker(page) -> None:
    # 展开筛选区后必须点击真实的「开始范围」输入框（旧版回退为
    # 「开始时间」），点击外层标签或仅等待输入框不会打开 auxo 弹层。
    start = await _visible_date_input(page)
    if start is None:
        raise RuntimeError("抖店订单页未找到可见的开始范围/开始时间输入框；请先展开筛选区")
    try:
        await start.click(timeout=4_000)
    except PlaywrightTimeout:
        await start.focus()
        await page.keyboard.press("Space")
    await _wait_panels(page)


async def _click_ok(page) -> None:
    ok = page.locator(OK_BTN).filter(visible=True).last
    try:
        await ok.click(timeout=5_000)
    except PlaywrightTimeout:
        # The current picker can report the button as visible/stable while its
        # transformed layer intercepts the final pointer step.  The button's
        # normal DOM click handler still closes the picker and preserves the
        # selected range, so use it only after the real click path times out.
        await ok.evaluate("el => el.click()")
    try:
        await page.locator(".auxo-picker-dropdown").wait_for(state="hidden", timeout=8_000)
    except PlaywrightTimeout:
        if await page.locator(PANEL_SEL).count():
            raise RuntimeError("抖店日期弹层点击确定后仍可见")


async def _try_relative_shortcut(page) -> bool:
    """新版/部分旧版有快捷项；只点击可见且精确匹配的项。"""

    for label in SHORTCUT_LABELS:
        options = page.get_by_text(label, exact=True).filter(visible=True)
        if await options.count():
            await options.last.click()
            if await page.locator(PANEL_SEL).count():
                await _click_ok(page)
            return True
    return False


async def _shortcut_selector(page):
    """定位旧版日期框右侧的快捷日期下拉选择器。

    旧版结构是“下单时间”日期范围 wrapper 的同级第二个
    `.auxo-label-wrapper.auxo-label-wrapper-small`，宽度约 125px；
    不要把日期范围自己的“下单时间”选择器误当成快捷下拉框。
    """

    start = await _visible_date_input(page)
    if start is None:
        return None
    date_wrapper = start.locator("xpath=ancestor::div[contains(@class,'auxo-label-wrapper')][1]")
    parent = date_wrapper.locator("xpath=..")
    sibling = parent.locator(
        ':scope > div.auxo-label-wrapper.auxo-label-wrapper-small:not([class*="styles_label-wrapper"]) '
        '.auxo-select-selector'
    ).filter(visible=True).first
    if await sibling.count():
        return sibling
    # 页面哈希类名变化时保留宽度特征作为回退，但仍只选择可见下拉框。
    fallback = page.locator(
        'div.auxo-label-wrapper.auxo-label-wrapper-small[style*="width: 125px"] '
        '.auxo-select-selector'
    ).filter(visible=True).first
    return fallback if await fallback.count() else None


async def _try_external_shortcut(page) -> bool:
    """优先使用旧版日期框旁的快捷下拉框。"""

    selector = await _shortcut_selector(page)
    if selector is None:
        return False
    await selector.click(timeout=8_000)
    for label in SHORTCUT_LABELS:
        options = page.get_by_text(label, exact=True).filter(visible=True)
        if not await options.count():
            continue
        await options.last.click(timeout=8_000)
        for _ in range(20):
            start_value, end_value = await date_values(page)
            if start_value and end_value:
                return True
            await asyncio.sleep(0.1)
        return False
    return False


async def fill_date_range(
    page, start_date: str, end_date: str, *, prefer_shortcut: bool = False
) -> None:
    """设置日期范围；按需优先使用近30日快捷项，否则按 title 精确点日历。

    自定义日期调试脚本必须保留日历选择能力，因此只有订单下载的近30日
    调用显式传入 ``prefer_shortcut=True`` 时才点击日期框旁的快捷下拉。
    """

    # 旧版快捷项在日期弹层外，必须先打开右侧“请选择”下拉框；
    # 只有找不到快捷控件时才打开日期弹层并使用新版快捷项/日历保底。
    if prefer_shortcut and await _try_external_shortcut(page):
        return
    await open_date_picker(page)
    if prefer_shortcut and await _try_relative_shortcut(page):
        return

    start_ym = tuple(int(value) for value in start_date.split("-")[:2])
    end_ym = tuple(int(value) for value in end_date.split("-")[:2])
    headers = await _wait_panels(page)
    print(f"抖店日期面板：左={headers[0]} 右={headers[1]}")
    if start_ym == end_ym:
        await _switch_panel_month(page, 0, start_ym)
        await _click_date(page, 0, start_date)
        await _click_date(page, 0, end_date)
    else:
        await _switch_panel_month(page, 0, start_ym)
        await _click_date(page, 0, start_date)
        await _switch_panel_month(page, 1, end_ym)
        await _click_date(page, 1, end_date)
    await _click_ok(page)


async def date_values(page) -> tuple[str, str]:
    start = await _visible_date_input(page)
    end = await _visible_date_input(page, end=True)
    if start is None or end is None:
        raise RuntimeError("抖店订单页未找到可见的开始/结束日期输入框")
    return await start.input_value(), await end.input_value()


async def set_near_thirty_days(page, *, today: date | None = None) -> tuple[str, str]:
    start_date, end_date = near_thirty_days(today=today)
    await fill_date_range(page, start_date, end_date, prefer_shortcut=True)
    start_value, end_value = await date_values(page)
    expected_start = start_date.replace("-", "/") + " 00:00:00"
    expected_end = end_date.replace("-", "/") + " 23:59:59"
    # 快捷项可能使用短日期格式，只要求起止日期被提交且不再为空。
    if not start_value or not end_value:
        raise RuntimeError(f"抖店近30日日期未提交：{start_value!r} ~ {end_value!r}")
    if expected_start not in start_value or expected_end not in end_value:
        print(f"抖店页面日期值：{start_value} ~ {end_value}")
    return start_date, end_date


async def click_query_and_wait(page, *, timeout_ms: int = 30_000) -> None:
    """点击查询并等待列表更新，避免固定长时间空等或重复提交。

    监听响应而不是把整个函数阻塞在 ``expect_response`` 上；页面正文一旦
    更新即可结束，未命中接口时也只等待一个 8--20 秒的随机上限。
    """

    query = page.get_by_role("button", name="查询", exact=True).filter(visible=True).last
    before = await page.locator("body").inner_text(timeout=5_000)
    response_seen = False
    clicked = False

    def is_query_response(response) -> bool:
        return response.status == 200 and any(
            fragment in response.url
            for fragment in (
                "/order/torder/",
                "/order/query",
                "/order/list",
                "recentOrderList",
                "searchConfig",
            )
        )

    def on_response(response) -> None:
        nonlocal response_seen
        try:
            if is_query_response(response):
                response_seen = True
        except Exception:
            # Response objects may be disposed while the page navigates; the
            # body-change fallback remains sufficient in that case.
            pass

    page.on("response", on_response)
    try:
        try:
            await query.click(timeout=8_000)
            clicked = True
        except PlaywrightTimeout:
            print("抖店查询按钮点击超时，继续观察页面结果")

        # 接口响应时间和 React 重绘时间都可能变化；随机化短等待上限，
        # 避免旧版接口 URL 不匹配时固定空等 45 秒。
        max_wait = max(2.0, min(timeout_ms / 1000, 20.0))
        min_wait = min(8.0, max_wait * 0.6)
        deadline = asyncio.get_running_loop().time() + random.uniform(min_wait, max_wait)
        while asyncio.get_running_loop().time() < deadline:
            text = await page.locator("body").inner_text(timeout=2_000)
            if text != before:
                return
            if response_seen:
                await asyncio.sleep(random.uniform(0.2, 0.6))
                return
            await asyncio.sleep(random.uniform(0.2, 0.45))
        if response_seen:
            return
        if clicked:
            raise TimeoutError("抖店订单查询在随机等待窗口内未完成")
        raise TimeoutError("抖店订单查询按钮点击失败")
    finally:
        page.remove_listener("response", on_response)
