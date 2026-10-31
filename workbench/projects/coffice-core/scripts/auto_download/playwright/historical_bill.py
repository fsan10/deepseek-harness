"""Exact-date bill lookup. Never substitute a newer downloadable bill."""
from __future__ import annotations

import asyncio
import re
from datetime import date

from scripts.auto_download.move_report import parse_date


def bill_target(mode: str, day: str | None = None, month: str | None = None) -> str | None:
    if day and month or day and mode != "day" or month and mode != "month":
        raise ValueError("--date仅用于日账单，--month仅用于月账单，不能同时传入")
    value = day or month
    if value:
        compact = parse_date(value)
        if len(compact) != (8 if mode == "day" else 6):
            raise ValueError("目标账单日期粒度与day/month不一致")
        if compact > date.today().strftime("%Y%m%d" if mode == "day" else "%Y%m"):
            raise ValueError("不能获取未来账单")
    return value


async def locate_bill(page, row_selector: str, target: str, mode: str, extract, action, *, date_cell_selector: str | None = None):
    expected = parse_date(target)
    rows = page.locator(row_selector)
    try:
        await rows.first.wait_for(state="visible", timeout=30_000)
    except Exception as exc:
        raise RuntimeError(f"REPORT_NOT_READY：查询后未出现 {target} 账单；未下载其他日期") from exc
    visited = set()
    async def row_texts():
        if date_cell_selector:
            return [await rows.nth(index).locator(date_cell_selector).inner_text() for index in range(await rows.count())]
        return await rows.all_inner_texts()

    for _ in range(120):
        texts = await row_texts()
        signature = tuple(texts)
        if signature in visited:
            break
        visited.add(signature)
        for index, text in enumerate(texts):
            try:
                actual = parse_date(extract(text, mode))
            except (ValueError, RuntimeError):
                continue
            if actual != expected:
                continue
            row = rows.nth(index)
            if await action(row).count():
                return row, extract(text, mode)
            raise RuntimeError(f"REPORT_NOT_READY：目标账单 {target} 尚未开放下载")
        # Use visible controls, checking disabled state and actual page changes.
        next_button = page.get_by_role("button", name=re.compile(r"^(下一页|下页|Next(?: Page)?)$", re.I)).locator("visible=true")
        if not await next_button.count():
            next_button = page.locator('.ag-paging-button-wrapper[ref="btNext"] button:visible, .el-pagination .btn-next:visible, .ant-pagination-next:visible, .d-pagination-next:visible')
        if not await next_button.count():
            next_button = page.locator('.d-pagination > .d-space > .d-space > .d-pagination-page:has(svg):visible').last
        if not await next_button.count():
            break
        button = next_button.first
        if await button.is_disabled() or await button.get_attribute("aria-disabled") == "true" or "disabled" in (await button.get_attribute("class") or ""):
            break
        try:
            await button.click(timeout=3000)
        except Exception:
            await button.evaluate("element => element.click()")
        for _ in range(60):
            if tuple(await row_texts()) != signature:
                break
            await asyncio.sleep(0.25)
        else:
            break
    raise RuntimeError(f"REPORT_NOT_READY：当前可查询账单中未找到 {target}；未下载其他日期")
