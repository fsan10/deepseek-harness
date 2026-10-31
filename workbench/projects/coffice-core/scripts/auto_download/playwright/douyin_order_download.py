# -*- coding: utf-8 -*-
"""抖店近30日或自定义日期范围订单标准报表下载。

脚本将导出任务创建、历史报表下载、短信验证码和 ZIP 解压密码分开管理。
任务状态与下载的 ZIP 保存在工作目录中；在 5 分钟导出限制或进程中断后，
再次运行只会从已有导出记录/ZIP 继续，不会重复点击“导出”。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
import tempfile
import zipfile
from contextlib import suppress
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from .automation_challenge import (
    cancel_challenge, create_challenge, probe_relay, reopen_for_human, resume_challenge, wait_answer,
)
from .component_runtime import automation_component, component_event
from .douyin_order_common import (
    ORDER_LIST_URL,
    click_query_and_wait,
    date_values,
    fill_date_range,
    near_thirty_days,
    set_near_thirty_days,
)
from .douyin_login import goto_with_douyin_login
from ..move_report import archive_report

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Download, Locator, Page

REPORT_NAME = "订单"
PLATFORM = "抖音"
ORDER_EXPORT_STATUS_FRAGMENT = "/order/torder/queryDownloadStatus"
ORDER_EXPORT_URL = "https://fxg.jinritemai.com/ffa/morder/order/export"
MAX_VERIFICATION_SERVICE_RETRIES = 3
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")


def _visible(locator: "Locator") -> "Locator":
    return locator.filter(visible=True)


async def click_compat(locator: "Locator") -> None:
    try:
        await locator.click(timeout=8_000)
    except Exception:
        await locator.evaluate("element => element.click()")


def _state_path(work_dir: Path) -> Path:
    return work_dir / "douyin_order_task.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _same_task(state: dict[str, Any], start_date: str, end_date: str) -> bool:
    return state.get("start_date") == start_date and state.get("end_date") == end_date


@automation_component("douyin.order.open_page", "抖音订单 · 打开页面", category="report")
async def open_order_page(
    context: "BrowserContext",
    shop: str,
    *,
    platform: str = "抖音",
    company: str = "",
) -> tuple["Page", bool]:
    page = next(
        (
            candidate
            for candidate in context.pages
            if not candidate.is_closed() and "fxg.jinritemai.com" in candidate.url
        ),
        None,
    )
    created = page is None
    if page is None:
        page = await context.new_page()
    else:
        await page.bring_to_front()

    # A deep link can redirect to the login page.  The shared helper reuses the
    # profile's persisted credentials, handles the optional human CAPTCHA
    # handoff, and selects the shop before the order flow continues.
    await goto_with_douyin_login(
        page,
        ORDER_LIST_URL,
        shop=shop,
        platform=platform,
        company=company,
    )
    # 新版首页会把深链重定向回首页；通过首页的订单管理导航建立
    # 应用上下文后，订单筛选页才会加载完整的 A/B 组件。
    if "/ffa/morder/order/list" not in page.url:
        nav = _visible(page.locator('a[href*="/ffa/morder/order/list"]'))
        if await nav.count():
            await click_compat(nav.first)
            try:
                await page.wait_for_url(re.compile(r"/ffa/morder/order/list"), timeout=30_000)
            except PlaywrightTimeout as exc:
                raise RuntimeError("从抖店首页点击订单管理后未进入订单列表") from exc
        else:
            await page.goto(ORDER_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.get_by_role("button", name="查询", exact=True).filter(visible=True).last.wait_for(
        state="visible", timeout=60_000
    )
    return page, created


@automation_component("douyin.order.prepare_filters", "抖音订单 · 设置筛选", category="report")
async def prepare_order_filters(page: "Page") -> None:
    """兼容新版“展开”和旧版直接显示筛选项。"""

    start = _visible(page.locator(
        'input[placeholder="开始时间"], input[placeholder="开始范围"]'
    )).first
    if await start.count():
        return
    expand = _visible(page.get_by_role("button", name="展开", exact=True))
    if await expand.count():
        await click_compat(expand.last)
    else:
        more = _visible(page.get_by_role("button", name="更多筛选", exact=True))
        if await more.count():
            await click_compat(more.last)
    await start.wait_for(state="visible", timeout=15_000)


@automation_component("douyin.order.query", "抖音订单 · 查询", category="report")
async def query_orders(
    page: "Page", start_date: str, end_date: str, *, custom_range: bool = False
) -> int | None:
    await prepare_order_filters(page)
    if custom_range:
        await fill_date_range(page, start_date, end_date)
    else:
        await set_near_thirty_days(page)
    current_start, current_end = await date_values(page)
    print(f"[DOUYIN] 日期范围已提交：{current_start} ~ {current_end}")
    previous_total = await _read_order_total(page)
    await click_query_and_wait(page)
    print(f"[DOUYIN] 订单查询完成：{start_date} ~ {end_date}")
    total = await wait_order_total(page, previous_total=previous_total)
    if total is not None:
        print(f"[DOUYIN] 指定范围订单数：{total}")
    return total


async def _read_order_total(page: "Page") -> int | None:
    """Read the visible post-query order total without using the whole body."""
    selectors = (
        ".aurora-pagination-total-text:visible",
        '[class*="paginationTotal"]:visible',
        '[class*="pagination-total"]:visible',
    )
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(await locator.count(), 10)):
            try:
                text = (await locator.nth(index).inner_text(timeout=800)).strip()
            except Exception:
                continue
            match = re.search(r"共\s*([\d,]+)\s*条(?:订单)?", text)
            if match:
                return int(match.group(1).replace(",", ""))

    empty = _visible(page.locator(
        '[class*="empty" i], [class*="no-data" i], [class*="nodata" i]'
    ))
    for index in range(min(await empty.count(), 10)):
        try:
            text = (await empty.nth(index).inner_text(timeout=800)).strip()
        except Exception:
            continue
        if re.search(r"暂无数据|无数据|没有订单|暂无订单", text):
            return 0
    return None


async def wait_order_total(
    page: "Page", previous_total: int | None = None, timeout: float = 15.0
) -> int | None:
    """Wait briefly for the refreshed total, including the explicit zero case."""
    deadline = asyncio.get_running_loop().time() + timeout
    last_total: int | None = None
    while asyncio.get_running_loop().time() < deadline:
        last_total = await _read_order_total(page)
        if last_total is not None and (previous_total is None or last_total != previous_total):
            return last_total
        if last_total == 0:
            return 0
        await asyncio.sleep(0.25)
    return last_total


def _visible_text(page: "Page", text: str) -> "Locator":
    return _visible(page.get_by_text(text, exact=True))


async def _wait_export_panel(page: "Page") -> None:
    await page.get_by_text("导出查询订单", exact=True).filter(visible=True).wait_for(
        state="visible", timeout=15_000
    )


async def open_export_panel(page: "Page") -> None:
    buttons = _visible(page.get_by_role("button", name="导出订单", exact=True))
    if await buttons.count():
        await click_compat(buttons.last)
    else:
        direct = _visible(page.get_by_text("导出订单", exact=True))
        if await direct.count():
            await click_compat(direct.last)
        else:
            # 新版订单页将“导出订单/导出记录”放在“导出”按钮的菜单中。
            trigger = _visible(page.get_by_role("button", name="导出", exact=True))
            if not await trigger.count():
                raise RuntimeError("订单页未找到导出入口")
            await click_compat(trigger.last)
            menu_item = _visible(page.get_by_role("menuitem", name="导出订单", exact=True))
            if not await menu_item.count():
                menu_item = _visible(page.get_by_text("导出订单", exact=True))
            await menu_item.last.wait_for(state="visible", timeout=10_000)
            await click_compat(menu_item.last)
    await _wait_export_panel(page)


async def _find_attention_modal(page: "Page") -> "Locator | None":
    """Find the current sensitive-information confirmation modal.

    The order page has two live implementations.  The old page uses an
    ``auxo-modal-confirm``/``role=document`` node, while the current page uses
    ``aurora-modal aurora-modal-confirm``/``role=dialog``.  There are also
    hidden legacy nodes in the DOM, so every candidate is filtered by both
    visibility and the title text.
    """

    title_re = re.compile(r"请\s*注\s*意")
    selectors = (
        ".aurora-modal.aurora-modal-confirm[role=dialog], "
        ".auxo-modal-confirm, "
        '[role="dialog"], [role="document"]'
    )
    candidates = _visible(page.locator(selectors)).filter(has_text=title_re)
    if not await candidates.count():
        return None
    # Prefer the actual modal container over a nested body/wrapper.  The
    # explicit class selectors normally yield exactly one element; ``last`` is
    # retained for pages that keep a hidden stale copy before the live one.
    for index in range(await candidates.count() - 1, -1, -1):
        candidate = candidates.nth(index)
        if await candidate.locator("button").count():
            return candidate
    return candidates.last


async def _confirm_attention(page: "Page") -> None:
    """确认订单标准报表的敏感信息提示。

    该提示在点击“导出”后可能延迟渲染；不同版本的抖店分别使用“确认”
    和“确定”。只有按钮真正点击且弹窗消失后，调用方才会把任务标记为
    已创建，避免漏点确认后反复刷新导出历史却找不到任务。
    """

    # 不要只等待 auxo 节点：当前版本的真实弹窗是 aurora-modal，旧版本
    # 的隐藏旧节点会让单一选择器一直返回空，最终把未确认的任务误标记为
    # 已创建。
    modal = await _find_attention_modal(page)
    deadline = asyncio.get_running_loop().time() + 30
    while modal is None and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
        modal = await _find_attention_modal(page)

    if modal is None:
        # A few account/page variants do not show the sensitive-information
        # notice after it has already been acknowledged.  In that case the
        # export drawer must have closed (or navigation must have started); if
        # it is still open, the click did not submit and we must fail instead
        # of recording a phantom EXPORT_CREATED state.
        panel = _visible_text(page, "导出查询订单")
        if not await panel.count() or "export" in page.url.lower():
            return
        raise RuntimeError("抖店“请注意”弹窗未出现，导出任务未确认")

    # Aurora renders the actionable control as
    # ``button.aurora-btn... > span``; scope the lookup to this modal so that
    # the export drawer's other “确认”/“取消” controls cannot be clicked.
    confirm = _visible(modal.locator("button.aurora-btn").filter(
        has_text=re.compile(r"^\s*(?:确认|确定)\s*$")
    )).last
    if not await confirm.count():
        confirm = _visible(
            modal.locator("button").filter(has_text=re.compile(r"^\s*(?:确认|确定)\s*$"))
        ).last
    if not await confirm.count():
        confirm = _visible(
            modal.get_by_role("button", name=re.compile(r"^(?:确认|确定)$"))
        ).last
    if not await confirm.count():
        raise RuntimeError("抖店“请注意”弹窗未找到“确认/确定”按钮")

    await confirm.wait_for(state="visible", timeout=10_000)
    await confirm.scroll_into_view_if_needed()
    await click_compat(confirm)
    try:
        # The modal is sometimes detached by a history-page navigation rather
        # than transitioned to ``display:none``.  The locator wait handles the
        # former, while the URL/visible-title fallback handles the latter.
        await modal.wait_for(state="hidden", timeout=10_000)
    except PlaywrightTimeout as exc:
        with suppress(Exception):
            if "export" in page.url.lower() or not await _find_attention_modal(page):
                print("[DOUYIN] 已确认“请注意”敏感信息弹窗")
                return
        raise RuntimeError("抖店“请注意”弹窗点击确认后仍未关闭") from exc
    print("[DOUYIN] 已确认“请注意”敏感信息弹窗")


_EXPORT_RATE_LIMIT_RE = re.compile(
    r"操作过于频繁|请勿重复提交|重复提交(?:任务|报表)?|(?:5|５)\s*分钟|五分钟|短时间内(?:不能|无法|请勿)",
    flags=re.IGNORECASE,
)


async def _export_rate_limit_visible(page: "Page") -> bool:
    """识别刚刚产生的导出频控提示。

    不扫描整个 ``body``：订单页的隐藏旧组件、帮助文案或历史提示可能
    含有“重复提交/5 分钟”等字样，导致一个从未生成过报表的店铺被错误
    当成频控而跳过确认。只读取可见的 toast/alert/message 节点，并要求
    文案是短提示。
    """

    candidates = [
        _visible(page.locator('[role="alert"]')),
        _visible(page.locator(
            '[aria-live], [class*="toast" i], [class*="message" i], '
            '[class*="notice" i], [class*="notification" i], [class*="snackbar" i]'
        )),
    ]
    for locator in candidates:
        try:
            count = min(await locator.count(), 20)
        except Exception:
            continue
        for index in range(count):
            try:
                text = (await locator.nth(index).inner_text(timeout=500)).strip()
            except Exception:
                continue
            if text and len(text) <= 300 and _EXPORT_RATE_LIMIT_RE.search(text):
                print(f"[DOUYIN] 导出频控提示：{text[:160]}")
                return True
    return False


@automation_component("douyin.order.create_export", "抖音订单 · 创建导出", category="report")
async def create_export_once(page: "Page", state_path: Path, state: dict[str, Any]) -> None:
    """只负责创建一次任务；任何后续错误都不会重新调用本函数。"""

    await open_export_panel(page)
    standard = _visible_text(page, "标准报表")
    await standard.last.wait_for(state="visible", timeout=10_000)
    await click_compat(standard.last)
    export_buttons = _visible(page.get_by_role("button", name="导出", exact=True))
    if not await export_buttons.count():
        raise RuntimeError("导出查询订单侧栏中未找到导出按钮")
    await click_compat(export_buttons.last)
    # 抖店同一店铺在频控窗口内会弹出“操作过于频繁/重复提交任务”，
    # 这不表示导出失败，历史记录中仍可能有正在生成或可下载的任务。
    for _ in range(4):
        if await _export_rate_limit_visible(page):
            state["stage"] = "EXPORT_CREATED"
            state["created_at"] = date.today().isoformat()
            state["creation_proof"] = "rate_limit"
            _write_state(state_path, state)
            print("[DOUYIN] 检测到导出频控提示，复用导出记录，不再重复创建任务")
            return
        await asyncio.sleep(0.25)
    await _confirm_attention(page)
    state["stage"] = "EXPORT_CREATED"
    state["created_at"] = date.today().isoformat()
    state["creation_proof"] = "attention_confirmed"
    _write_state(state_path, state)
    print("[DOUYIN] 导出任务已创建；后续失败时禁止再次创建")


async def open_export_history(page: "Page") -> "Page":
    """通过页面入口打开导出历史；无法确认页面时回退到已验证路由。"""

    clicked_history = False
    opened_export_menu = False
    for _ in range(60):
        if await _history_ready(page):
            return page
        candidates = _visible_text(page, "导出记录")
        if not await candidates.count():
            candidates = _visible(
                page.get_by_role("menuitem", name="导出记录", exact=True)
            )
        if not clicked_history and await candidates.count():
            try:
                await click_compat(candidates.last)
                clicked_history = True
            except Exception:
                pass
        elif not clicked_history and not opened_export_menu:
            # 新版订单页先把“导出订单/导出记录”收进“导出”按钮菜单；
            # 仅查找已展开的菜单会导致进程恢复时永远找不到历史入口。
            trigger = _visible(page.get_by_role("button", name="导出", exact=True))
            if await trigger.count():
                try:
                    await click_compat(trigger.last)
                    opened_export_menu = True
                except Exception:
                    pass
        await asyncio.sleep(0.25)
        if await _history_ready(page):
            return page
        # 某些版本通过菜单链接跳转；若出现新标签页，接管它。
        for candidate in page.context.pages:
            if candidate is page or candidate.is_closed():
                continue
            try:
                if await _history_ready(candidate):
                    await candidate.bring_to_front()
                    return candidate
            except Exception:
                continue
    # 页面菜单可能仍让流程停留在订单列表；回退到脚本已有并在失败现场
    # 确认可用的订单导出历史路由。该导航只读取已有任务，不会创建导出。
    await page.goto(ORDER_EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
    if await _history_ready(page):
        print("[DOUYIN] 已通过兼容路由打开订单导出历史")
        return page
    raise RuntimeError("未能从抖店订单页打开导出记录")


async def _history_ready(page: "Page") -> bool:
    # 只接受抖店订单导出历史页，避免把 Compass 等其他标签上的静态
    # “报表类型”文案或订单页 URL 查询参数中的 export 误判为历史页。
    page_url = page.url.lower()
    if "/ffa/morder/order/export" in page_url:
        return True
    if "fxg.jinritemai.com" not in page_url or "/ffa/morder/order/list" in page_url:
        return False
    body = (await page.locator("body").inner_text(timeout=3_000)).strip()
    return bool(re.search(r"下载报表|生成中|生成失败|报表类型", body)) and "导出查询订单" not in body


async def _status_response(response) -> None:
    """记录状态字段名和值，不打印响应中的令牌或业务数据。"""

    if ORDER_EXPORT_STATUS_FRAGMENT not in response.url or response.status != 200:
        return
    try:
        data = await response.json()
    except Exception:
        return
    statuses: list[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for name, item in value.items():
                if any(word in str(name).lower() for word in ("status", "state", "progress")):
                    if isinstance(item, (str, int, float, bool)):
                        statuses.append(f"{name}={item}")
                walk(item, str(name))
        elif isinstance(value, list):
            for item in value[:20]:
                walk(item, key)

    walk(data)
    if statuses:
        print(f"[DOUYIN] queryDownloadStatus：{', '.join(statuses[:12])}")


def _date_text_matches(text: str, start_date: str, end_date: str) -> bool:
    normalized = text.replace("-", "/")
    return end_date.replace("-", "/") in normalized or (
        start_date.replace("-", "/") in normalized and end_date.replace("-", "/") in normalized
    )


def _parse_created(text: str) -> tuple[int, ...]:
    values = re.findall(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})[日 ]?(?:([01]?\d|2[0-3])[:时](\d{1,2})[:分](\d{1,2}))?", text)
    parsed: list[tuple[int, ...]] = []
    for year, month, day, hour, minute, second in values:
        parsed.append((int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)))
    return max(parsed) if parsed else (0,)


async def _download_candidates(page: "Page", start_date: str, end_date: str) -> list[tuple[tuple[int, ...], "Locator", str]]:
    cards = _visible(page.locator("li[class*='cardItem']"))
    result = []
    for index in range(await cards.count()):
        row = cards.nth(index)
        try:
            text = (await row.inner_text(timeout=1_500)).strip()
        except Exception:
            continue
        if "标准报表" not in text and "标准" not in text:
            continue
        # 任务创建后优先锁定目标结束日期；平台“近一个月”可能将起始日
        # 展示为自然月边界前一天，因此不能死比对起始日。
        if (start_date or end_date) and "下单时间" in text and not _date_text_matches(text, start_date, end_date):
            continue
        button = _visible(row.get_by_role("button", name=re.compile(r"下载报表|下载$"))).first
        if not await button.count():
            continue
        result.append((_parse_created(text), button, text))
    result.sort(key=lambda item: item[0], reverse=True)
    return result


async def _history_has_matching_task(page: "Page", start_date: str, end_date: str) -> bool:
    """Return whether history already contains this standard-report request.

    This is used only to migrate state files written by the old implementation,
    which could mark ``EXPORT_CREATED`` before the Aurora confirmation click.
    A matching row may still be generating and therefore have no download
    button yet, so this check deliberately does not call
    :func:`_download_candidates`.
    """

    cards = _visible(page.locator("li[class*='cardItem']"))
    for index in range(await cards.count()):
        try:
            text = (await cards.nth(index).inner_text(timeout=1_500)).strip()
        except Exception:
            continue
        if "标准报表" in text and _date_text_matches(text, start_date, end_date):
            return True
    # Some page revisions render table rows instead of cardItem.  Keep the
    # fallback bounded to short visible rows, never the whole body, so static
    # help text cannot be interpreted as an existing export task.
    rows = _visible(page.locator("tr"))
    for index in range(min(await rows.count(), 100)):
        try:
            text = (await rows.nth(index).inner_text(timeout=1_000)).strip()
        except Exception:
            continue
        if len(text) <= 2_000 and "标准报表" in text and _date_text_matches(text, start_date, end_date):
            return True
    return False


@automation_component("report.wait_export_ready", "等待导出任务就绪", category="report")
async def wait_latest_report(page: "Page", start_date: str, end_date: str, timeout: float = 900.0) -> "Locator":
    deadline = asyncio.get_running_loop().time() + timeout
    poll_count = 0
    while asyncio.get_running_loop().time() < deadline:
        candidates = await _download_candidates(page, start_date, end_date)
        if candidates:
            print("[DOUYIN] 已找到最新可下载标准订单报表")
            return candidates[0][1]
        if await _history_ready(page):
            body = await page.locator("body").inner_text(timeout=3_000)
            if "生成失败" in body:
                raise RuntimeError("抖店最新订单报表生成失败")
        await asyncio.sleep(5)
        poll_count += 1
        # 先在当前历史页轮询，避免每 5 秒 reload 破坏 SPA 上下文；每 30 秒
        # 才刷新一次，并在刷新后确认仍在历史页，必要时重新点击“导出记录”。
        if poll_count % 6:
            continue
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
        except Exception:
            continue
        if "export" not in page.url.lower():
            with suppress(Exception):
                await open_export_history(page)
    raise TimeoutError("等待抖店订单报表生成可下载超时")


async def _find_dialog(page: "Page") -> "Locator | None":
    """只返回真正的下载验证弹窗，不把普通可见弹层当成验证码挑战。"""

    candidates = _visible(page.locator(
        '[role="dialog"], [role="document"], .auxo-modal, '
        '[class*="modal" i], [class*="dialog" i]'
    ))
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        try:
            text = (await candidate.inner_text(timeout=500)).strip()
        except Exception:
            continue
        if not any(marker in text for marker in ("下载验证", "获取验证码", "验证码")):
            continue
        if any(marker in text for marker in ("下载验证", "获取验证码")):
            return candidate
        if await _verification_input(page, candidate).count():
            return candidate

    # 无 role/class 的版本仍可通过“下载验证”标题找到；返回最近的弹层
    # 容器，而不是标题自身，供后续查找输入框和确认按钮。
    title = _visible(page.get_by_text(re.compile(r"下载\s*验证"), exact=False))
    if await title.count():
        for index in range(await title.count()):
            node = title.nth(index)
            ancestor = node.locator(
                "xpath=ancestor::*[@role='dialog' or @role='document' or "
                "contains(translate(@class,'MODALDIALOG','modaldialog'),'modal') or "
                "contains(translate(@class,'MODALDIALOG','modaldialog'),'dialog')][1]"
            )
            if await ancestor.count():
                return ancestor
    return None


async def _verification_input(page: "Page", dialog: "Locator | None" = None) -> "Locator":
    selectors = (
        'input[placeholder*="验证码"], input[aria-label*="验证码"], '
        'input[name*="verify" i], input[id*="verify" i], input[name*="captcha" i], input[id*="captcha" i]'
    )
    if dialog is not None:
        scoped = _visible(dialog.locator(selectors)).first
        if await scoped.count():
            return scoped
        # 下载验证弹窗有版本只给“请输入”或空 placeholder；此时弹窗内
        # 唯一可见的非隐藏输入框就是验证码输入框。
        generic = _visible(dialog.locator(
            'input:not([type="hidden"]):not([disabled])'
        )).first
        if await generic.count():
            return generic
        # 已经确定是一个弹窗时，不要退回页面级输入框；页面其他区域的
        # 搜索框/隐藏旧节点不能证明该弹窗需要验证码。
        return _visible(dialog.locator(selectors)).first
    return _visible(page.locator(selectors)).first


_VERIFICATION_ERROR_RE = re.compile(
    r"(?:验证码|校验码).{0,12}(?:错误|不正确|失效|过期|失败)|"
    r"(?:验证失败|请重新输入验证码)",
    flags=re.IGNORECASE | re.DOTALL,
)


class VerificationCodeError(RuntimeError):
    """页面明确拒绝了本次验证码，允许向负责人发送重试提醒。"""


async def _verification_error_visible(page: "Page", dialog: "Locator | None") -> bool:
    """只识别验证弹窗中的明确失败文案，不把普通提示当成验证码错误。"""

    candidates = []
    if dialog is not None:
        candidates.extend([
            dialog.locator('[role="alert"]'),
            dialog.locator('[class*="error" i]'),
            dialog,
        ])
    candidates.extend([
        _visible(page.locator('[role="alert"]')),
        _visible(page.locator('[class*="error" i]')),
    ])
    for locator in candidates:
        try:
            count = min(await locator.count(), 30)
        except Exception:
            continue
        for index in range(count):
            try:
                text = (await locator.nth(index).inner_text(timeout=500)).strip()
            except Exception:
                continue
            if text and _VERIFICATION_ERROR_RE.search(text):
                return True
    return False


async def _click_get_code_control(page: "Page", dialog: "Locator", *, retry: bool = False) -> None:
    """Click the real verification suffix in the download dialog.

    The current page renders it as ``span.input-suffix-verify`` inside the
    input wrapper, not as a button.  After a successful request the same node
    becomes a countdown and then changes to ``重新发送``, so a retry waits for
    either label instead of clicking a stale/disabled control.
    """

    control_labels = ("获取验证码", "重新发送")
    timeout = 60.0 if retry else 10.0
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        for label in control_labels:
            get_code = _visible(dialog.get_by_text(label, exact=True))
            if not await get_code.count():
                get_code = _visible(page.get_by_text(label, exact=True))
            if await get_code.count():
                await click_compat(get_code.last)
                print(
                    f"[DOUYIN] 已重新点击“{label}”"
                    if retry
                    else f"[DOUYIN] 已点击“{label}”"
                )
                return
        await asyncio.sleep(0.5)
    raise RuntimeError("抖店下载验证弹窗未找到可用的“获取验证码”控件")


def _is_verification_service_failure(exc: BaseException) -> bool:
    """Only retry transport/service failures, not expired challenges or bad codes."""

    return str(exc).startswith("自动化验证码服务")


async def _request_verification_answer_with_retry(
    page: "Page",
    dialog: "Locator",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> str:
    """Request the SMS answer and recover from a transient relay failure.

    A relay failure can happen before the original implementation's
    ``after_create`` callback, which meant the platform never received a
    ``获取验证码`` click.  On each retry we register the Challenge first and
    then click that control. The existing Challenge ID, when present, is preserved
    and is never duplicated.
    """

    sms_requested = False
    for retry_count in range(MAX_VERIFICATION_SERVICE_RETRIES + 1):
        # A failed preflight means no Challenge can be delivered. Keep it out
        # of the retry handler so a relay outage never triggers an orphan SMS.
        await asyncio.to_thread(probe_relay)
        try:
            async def request_sms_code() -> None:
                nonlocal sms_requested
                if sms_requested:
                    print("[DOUYIN] 已在验证码服务重试前触发短信，不重复点击“获取验证码”")
                    return
                await _click_get_code_control(page, dialog, retry=retry_count > 0)
                sms_requested = True

            purpose = "订单报表下载验证码"
            if retry_count:
                purpose += f"（自动化验证码服务第 {retry_count + 1} 次尝试）"
            return await _request_stateful_answer(
                challenge_key="verification_challenge_id",
                challenge_type="verification_code", platform=platform, company=company, shop=shop,
                purpose=purpose,
                page_url=page.url, state_path=state_path, state=state,
                after_create=request_sms_code,
            )
        except RuntimeError as exc:
            # Once a Challenge ID has been persisted, the SMS request already
            # exists.  Preserve it for a later process restart instead of
            # sending duplicate SMS messages or creating orphan Challenges.
            if (
                not _is_verification_service_failure(exc)
                or state.get("verification_challenge_id")
                or retry_count >= MAX_VERIFICATION_SERVICE_RETRIES
            ):
                raise
            print(
                f"[DOUYIN] 自动化验证码服务第 {retry_count + 1} 次失败；"
                f"先重新登记等待请求，准备第 {retry_count + 2} 次尝试"
            )
            # Retry registration first; after_create triggers SMS only after it succeeds.
    raise RuntimeError("自动化验证码服务重试未返回答案")


async def _wait_for_download_or_verification(
    info, page: "Page", *, timeout: float = 20.0, download_task: asyncio.Task | None = None
) -> tuple["Download | None", "Locator | None", "Locator | None", asyncio.Task]:
    """在下载事件和验证码弹窗之间择一，不把无验证码下载误判为挑战。"""

    download_task = download_task or asyncio.create_task(info.value)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if download_task.done():
            return await download_task, None, None, download_task
        dialog = await _find_dialog(page)
        if dialog is not None:
            field = await _verification_input(page, dialog)
            if await field.count():
                return None, dialog, field, download_task
        await asyncio.sleep(0.25)
    if download_task.done():
        return await download_task, None, None, download_task
    download_task.cancel()
    with suppress(asyncio.CancelledError):
        await download_task
    raise TimeoutError("抖店下载既未出现验证码输入框，也未开始下载 ZIP")


async def _wait_download_or_verification_error(
    info, page: "Page", dialog: "Locator | None", download_task: asyncio.Task | None = None
) -> "Download":
    """等待下载事件，同时轮询弹窗失败文案，避免错误验证码静默超时。"""

    download_task = download_task or asyncio.create_task(info.value)
    try:
        while True:
            if download_task.done():
                return await download_task
            if await _verification_error_visible(page, dialog):
                raise VerificationCodeError("抖店下载验证码错误")
            await asyncio.sleep(0.25)
    finally:
        if not download_task.done():
            download_task.cancel()
            with suppress(asyncio.CancelledError):
                await download_task


def _challenge_purpose(base_purpose: str, challenge_type: str, retry: bool) -> str:
    if not retry:
        return base_purpose
    if challenge_type == "verification_code":
        return f"验证码错误，请重新输入。{base_purpose}"
    return f"解压密码错误，请重新输入。{base_purpose}"


@automation_component("human.verification.wait", "等待飞书验证码 / 密码", category="human")
async def _request_stateful_answer(
    *,
    challenge_key: str,
    challenge_type: str,
    platform: str,
    company: str,
    shop: str,
    purpose: str,
    page_url: str,
    state_path: Path,
    state: dict[str, Any],
    after_create: Callable[[], Awaitable[None]] | None = None,
    resume_human: bool = False,
) -> str:
    """保存 Challenge ID，进程中断后继续等待同一条请求而不重复轰炸群聊。"""

    force_human = resume_human or bool(state.get(challenge_key + "_human_required"))
    if resume_human and not state.get(challenge_key) and state.get(challenge_key + "_last_answered"):
        state[challenge_key] = state[challenge_key + "_last_answered"]
    if "错误" in purpose:
        try:
            await reopen_for_human(state, challenge_key)
        except RuntimeError as exc:
            if "过期" not in str(exc) and "取消" not in str(exc):
                raise
            state.pop(challenge_key, None)
            state.pop(challenge_key + "_last_answered", None)
        force_human = True
        _write_state(state_path, state)
    existing_id = str(state.get(challenge_key) or "").strip()
    if existing_id:
        if resume_human or state.get(challenge_key + "_manual_only"):
            await resume_challenge(existing_id)
        component_event("waiting_human", "复用已有 Challenge，等待自动接收或人工回复", detail={"challenge_id": existing_id})
        try:
            answer = await wait_answer(challenge_id=existing_id)
        except RuntimeError as exc:
            if "过期" not in str(exc) and "取消" not in str(exc):
                raise
            state.pop(challenge_key, None)
            force_human = force_human or challenge_type == "archive_password"
            _write_state(state_path, state)
        else:
            state.pop(challenge_key, None)
            state.pop(challenge_key + "_human_required", None)
            state.pop(challenge_key + "_manual_only", None)
            state[challenge_key + "_last_answered"] = existing_id
            _write_state(state_path, state)
            component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
            return answer
    challenge = await create_challenge(
        challenge_type=challenge_type, platform=platform, company=company, shop=shop,
        purpose=purpose, page_url=page_url, force_human=force_human,
    )
    challenge_id = str(challenge.get("challenge_id") or "").strip()
    if not challenge_id:
        raise RuntimeError("自动化验证码服务未返回 challenge_id")
    state[challenge_key] = challenge_id
    _write_state(state_path, state)
    component_event("waiting_human", "Challenge 已创建，等待自动接收或人工回复", detail={"challenge_id": challenge_id, "challenge_type": challenge_type if "challenge_type" in locals() else "archive_password"})
    try:
        if after_create is not None:
            await after_create()
        answer = await wait_answer(
            challenge_id=challenge_id,
            timeout_seconds=int(challenge.get("timeout_seconds") or 300),
        )
    except RuntimeError as exc:
        # 只有服务明确判定 Challenge 失效时才清掉 ID；网络错误、服务重启
        # 或进程中断都保留它，重跑可以继续同一条群消息而不重复发送。
        if "过期" in str(exc) or "取消" in str(exc):
            state.pop(challenge_key, None)
            if challenge_type == "archive_password":
                state[challenge_key + "_human_required"] = True
            _write_state(state_path, state)
        raise
    else:
        state.pop(challenge_key, None)
        state.pop(challenge_key + "_human_required", None)
        state.pop(challenge_key + "_manual_only", None)
        state[challenge_key + "_last_answered"] = challenge_id
        _write_state(state_path, state)
        component_event("human_answered", "验证码 / 密码已收到；答案未写入事件")
        return answer


async def _cancel_password_listener(state_path: Path, state: dict[str, Any]) -> None:
    key = "archive_password_challenge_id"
    challenge_id = state.get(key)
    if challenge_id:
        await cancel_challenge(str(challenge_id))
        state.pop(key, None)
        state.pop(key + "_manual_only", None)
        _write_state(state_path, state)


async def _prepare_password_listener(
    page: "Page", *, platform: str, company: str, shop: str,
    state_path: Path, state: dict[str, Any],
) -> None:
    """Persist the password listener before any action that can send its SMS."""
    await _cancel_password_listener(state_path, state)
    challenge = await create_challenge(
        challenge_type="archive_password", platform=platform, company=company, shop=shop,
        purpose="订单报表 ZIP 解压密码", page_url=page.url, defer_human_notice=True,
    )
    challenge_id = str(challenge.get("challenge_id") or "")
    if not challenge_id:
        raise RuntimeError("自动化验证码服务未返回解压密码 challenge_id")
    state["archive_password_challenge_id"] = challenge_id
    state["archive_password_challenge_id_manual_only"] = not challenge.get("automatic_enabled", True)
    state.pop("archive_password_challenge_id_human_required", None)
    _write_state(state_path, state)
    component_event("waiting_human", "解压密码接收已启动，随后触发报表下载", detail={"challenge_id": challenge_id, "challenge_type": "archive_password"})


@automation_component("file.download", "下载报表文件", category="file")
async def download_zip_with_challenges(
    page: "Page",
    button: "Locator",
    *,
    platform: str,
    company: str,
    shop: str,
    state_path: Path,
    state: dict[str, Any],
) -> Path:
    state["stage"] = "DOWNLOADING"
    _write_state(state_path, state)
    download: "Download | None" = None
    for attempt in range(3):
        try:
            async with page.expect_download(timeout=900_000) as info:
                dialog = await _find_dialog(page)
                # The verification dialog can already be open when the process is
                # resumed (for example, after a transient Playwright timeout).  In
                # that case do not click the row button again; it would create a
                # second verification request and invalidate the first one.
                download_task = asyncio.create_task(info.value)
                if dialog is None:
                    await _prepare_password_listener(
                        page, platform=platform, company=company, shop=shop,
                        state_path=state_path, state=state,
                    )
                    await click_compat(button)
                direct_download, dialog, field, download_task = await _wait_for_download_or_verification(
                    info, page, download_task=download_task
                )
                if direct_download is not None:
                    # 下载验证不是必现的；当天已经验证过时，点击后会直接
                    # 触发 ZIP 下载，跳过验证码 Challenge，保留预登记的密码请求。
                    download = direct_download
                    print("[DOUYIN] 未触发下载验证码，已直接接收 ZIP")
                else:
                    if dialog is None or field is None:
                        raise RuntimeError("抖店下载验证状态不完整")
                    # The first click only opened verification, so no password
                    # was sent. Release its listener before registering the OTP.
                    await _cancel_password_listener(state_path, state)
                    answer = await _request_verification_answer_with_retry(
                        page, dialog, platform=platform, company=company, shop=shop,
                        state_path=state_path, state=state,
                    )
                    await field.fill(answer)
                    confirm = _visible(dialog.get_by_role("button", name=re.compile("确定|确认|提交")))
                    if not await confirm.count():
                        confirm = _visible(page.get_by_role("button", name=re.compile("确定|确认|提交")))
                    if not await confirm.count():
                        raise RuntimeError("抖店下载验证弹窗未找到提交按钮")
                    await _prepare_password_listener(
                        page, platform=platform, company=company, shop=shop,
                        state_path=state_path, state=state,
                    )
                    await click_compat(confirm.last)
                    download = await _wait_download_or_verification_error(
                        info, page, dialog, download_task
                    )
            break
        except VerificationCodeError:
            await _cancel_password_listener(state_path, state)
            if attempt >= 2:
                raise RuntimeError("连续三次验证码错误，保留当前页面供人工恢复")
            print("[DOUYIN] 验证码输入错误，已发送重新输入提醒；不重新生成订单报表")
            await reopen_for_human(state, "verification_challenge_id")
            _write_state(state_path, state)
        except PlaywrightTimeout as exc:
            raise TimeoutError("抖店订单下载验证或下载超时") from exc
    if download is None:
        raise RuntimeError("抖店下载事件未返回文件")
    filename = download.suggested_filename or "douyin_order.zip"
    zip_path = state_path.parent / filename
    await download.save_as(str(zip_path))
    if not zip_path.is_file() or zip_path.stat().st_size == 0:
        raise RuntimeError("抖店订单 ZIP 文件为空")
    state["stage"] = "ZIP_DOWNLOADED"
    state["zip_path"] = str(zip_path)
    _write_state(state_path, state)
    print(f"[DOUYIN] ZIP 已保存：{zip_path}")
    return zip_path


def _archive_requires_password(archive: Path) -> bool:
    with zipfile.ZipFile(archive) as bundle:
        return any(info.flag_bits & 0x1 for info in bundle.infolist() if not info.is_dir())


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"ZIP 中存在不安全路径：{name}")
    return str(path)


def extract_zip(archive: Path, destination: Path, password: str = "") -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    pwd = password.encode("utf-8") if password else None
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            safe = _safe_member_name(info.filename)
            target = destination / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with bundle.open(info, pwd=pwd) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
            except RuntimeError as exc:
                if "Bad password" in str(exc) or "password" in str(exc).lower():
                    raise ValueError("ZIP 解压密码错误") from exc
                raise
            extracted.append(target)
    if not extracted:
        raise RuntimeError("ZIP 中没有可解压文件")
    return extracted


def select_report_file(files: list[Path]) -> Path:
    candidates = [path for path in files if path.suffix.lower() in {".xlsx", ".xls", ".csv"}]
    if len(candidates) != 1:
        names = "、".join(path.name for path in candidates)
        raise RuntimeError(f"订单 ZIP 中未找到唯一报表文件：{names or '无 CSV/XLSX'}")
    return candidates[0]


def _recover_extracted_report(archive: Path, extraction_dir: Path) -> Path | None:
    """Reuse a complete extraction left by a failure during the archive step."""

    if not extraction_dir.is_dir():
        return None
    candidates = [
        path
        for path in extraction_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".csv"}
    ]
    if len(candidates) != 1:
        return None
    report_file = candidates[0]
    try:
        relative_name = report_file.relative_to(extraction_dir).as_posix()
        with zipfile.ZipFile(archive) as bundle:
            member = next(
                (
                    info
                    for info in bundle.infolist()
                    if not info.is_dir()
                    and _safe_member_name(info.filename) == relative_name
                ),
                None,
            )
        if member is None or report_file.stat().st_size <= 0:
            return None
        if report_file.stat().st_size != member.file_size:
            return None
    except (OSError, ValueError, zipfile.BadZipFile):
        return None
    return report_file


@automation_component("file.archive.extract", "解压 / 解密归档", category="file")
async def process_zip(
    page: "Page", archive: Path, *, platform: str, company: str, shop: str,
    state_path: Path, state: dict[str, Any], business_date: str, dest: Path,
    resume_human: bool = False,
) -> None:
    extraction_dir = archive.parent / "extracted"
    report_file = (
        _recover_extracted_report(archive, extraction_dir)
        if state.get("stage") == "EXTRACTING"
        else None
    )
    if report_file is not None:
        print("[DOUYIN] 发现校验完整的已解压报表，从归档步骤恢复")
    else:
        password = ""
        try:
            needs_password = _archive_requires_password(archive)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("抖店下载文件不是有效 ZIP") from exc
        base_purpose = f"订单报表 ZIP 解压（{archive.name}）"
        if not needs_password:
            await _cancel_password_listener(state_path, state)
        for attempt in range(3 if needs_password else 1):
            if needs_password:
                state["stage"] = "PASSWORD_REQUIRED"
                _write_state(state_path, state)
                print("[DOUYIN] ZIP 已加密，正在请求解压密码")
                password = await _request_stateful_answer(
                    challenge_key="archive_password_challenge_id",
                    challenge_type="archive_password", platform=platform, company=company, shop=shop,
                    purpose=_challenge_purpose(base_purpose, "archive_password", attempt > 0), page_url=page.url,
                    state_path=state_path, state=state,
                    resume_human=resume_human and attempt == 0,
                )
            state["stage"] = "EXTRACTING"
            _write_state(state_path, state)
            try:
                files = await asyncio.to_thread(extract_zip, archive, extraction_dir, password)
                break
            except ValueError:
                if attempt >= 2:
                    raise RuntimeError("连续三次解压密码错误，保留 ZIP 供人工恢复")
                print("[DOUYIN] 解压密码输入错误，已发送重新输入提醒；不重新下载 ZIP")
        report_file = select_report_file(files)

    archived_path = await asyncio.to_thread(
        archive_report,
        report_file,
        platform,
        company,
        shop,
        REPORT_NAME,
        business_date,
        dest,
    )
    print(
        f"已移动：{report_file.name}\n"
        f"  -> {archived_path}\n"
        f"报表类型目录：{archived_path.parent}"
    )
    state["stage"] = "COMPLETED"
    state["report_path"] = str(archived_path)
    _write_state(state_path, state)
    try:
        archive.unlink(missing_ok=True)
        shutil.rmtree(extraction_dir, ignore_errors=True)
        state_path.unlink(missing_ok=True)
    except OSError:
        pass
    print("[DOUYIN] 订单报表下载、解压、归档完成")


@automation_component("douyin.order.workflow", "抖音订单 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    business_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    custom_range = start_date is not None or end_date is not None
    if custom_range and (start_date is None or end_date is None):
        raise ValueError("自定义日期范围必须同时提供开始日期和结束日期")
    if custom_range:
        assert start_date is not None and end_date is not None
    else:
        start_date, end_date = near_thirty_days()
    assert start_date is not None and end_date is not None
    business_date = business_date or end_date
    work_dir.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(work_dir)
    state = _read_state(state_path)
    if not _same_task(state, start_date, end_date) or state.get("stage") == "COMPLETED":
        state = {"platform": platform, "company": company, "shop": shop,
                 "start_date": start_date, "end_date": end_date, "stage": "EXPORT_NOT_CREATED"}
        _write_state(state_path, state)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器没有可用上下文")
        context = browser.contexts[0]
        page, created = await open_order_page(
            context,
            shop,
            platform=platform,
            company=company,
        )
        page.on("response", lambda response: asyncio.create_task(_status_response(response)))
        try:
            # State files produced before the confirmation fix do not contain
            # ``creation_proof``.  Do not blindly trust such a file: inspect
            # the actual history for this date range first.  This repairs the
            # exact failure mode where a missing “请注意→确认” click left a
            # phantom EXPORT_CREATED marker and every retry opened history
            # without ever creating a report.
            if state.get("stage") == "EXPORT_CREATED" and not state.get("creation_proof"):
                await page.goto(ORDER_EXPORT_URL, wait_until="domcontentloaded", timeout=60_000)
                try:
                    await page.get_by_role("button", name=re.compile(r"下载报表|下载$"))\
                        .filter(visible=True).first.wait_for(state="visible", timeout=30_000)
                except PlaywrightTimeout:
                    # An empty history page is valid; the bounded row check
                    # below determines whether the task exists.
                    pass
                if await _history_has_matching_task(page, start_date, end_date):
                    state["creation_proof"] = "legacy_history"
                    _write_state(state_path, state)
                    print("[DOUYIN] 旧状态已在导出记录中核验，继续等待/下载")
                else:
                    state = {"platform": platform, "company": company, "shop": shop,
                             "start_date": start_date, "end_date": end_date,
                             "stage": "EXPORT_NOT_CREATED"}
                    _write_state(state_path, state)
                    await page.goto(ORDER_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
                    page, _ = await open_order_page(
                        context,
                        shop,
                        platform=platform,
                        company=company,
                    )
                    print("[DOUYIN] 旧状态未找到对应导出记录，已恢复为待创建并重新查询")
            if state.get("stage") == "EXPORT_NOT_CREATED":
                order_count = await query_orders(
                    page, start_date, end_date, custom_range=custom_range
                )
                if order_count == 0:
                    print(
                        f"[DOUYIN] 指定范围无订单（{start_date} ~ {end_date}），跳过订单导出"
                    )
                    with suppress(OSError):
                        state_path.unlink(missing_ok=True)
                    return 0
                await create_export_once(page, state_path, state)
            page = await open_export_history(page)
            button = await wait_latest_report(page, start_date, end_date)
            zip_path = Path(state.get("zip_path", "")) if state.get("zip_path") else None
            cached_zip = bool(zip_path and zip_path.is_file())
            if not zip_path or not zip_path.is_file():
                zip_path = await download_zip_with_challenges(
                    page, button, platform=platform, company=company, shop=shop,
                    state_path=state_path, state=state,
                )
            await process_zip(page, zip_path, platform=platform, company=company, shop=shop,
                              state_path=state_path, state=state, business_date=business_date, dest=dest,
                              resume_human=cached_zip)
        finally:
            if created and not page.is_closed():
                await page.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="抖店订单标准报表下载")
    parser.add_argument("--cdp", required=True, help="Cloak Login start_profile 返回的 wsEndpoint")
    parser.add_argument("--platform", default=PLATFORM)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument("--work-dir", default=None, help="可恢复工作目录；默认 data\\.automation_cache\\douyin_order\\<shop>")
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--business-date", default=None, help="归档日期前缀，默认查询结束日期")
    parser.add_argument("--start-date", default=None, help="自定义下单开始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义下单结束日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
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
    work_dir = Path(args.work_dir) if args.work_dir else Path(args.dest) / ".automation_cache" / "douyin_order" / args.shop
    try:
        return asyncio.run(run(args.cdp, args.platform, args.company, args.shop, work_dir,
                               Path(args.dest), args.business_date,
                               args.start_date, args.end_date))
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 2 if getattr(exc, 'requires_human', False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
