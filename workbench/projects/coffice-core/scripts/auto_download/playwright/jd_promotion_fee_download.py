# -*- coding: utf-8 -*-
"""京东联盟与京准通推广费报表下载。

脚本连接已经由 Cloak Login 启动的京东 profile，依次执行两个京准通页面
的导出任务：

* 京东联盟 ``jtk/#/account-bill`` -> ``京东联盟推广费``；
* 账户中心（京准通） ``account/#/financialRecord`` -> ``京东通推广费``。

两个报表共用京东下载锁，脚本内部也严格串行。正常的“近 30 天”任务使用
页面快捷项；指定日期区间时使用页面双面日历，并保存任务状态，进程中断后
不会盲目重复点击“开始生成”。
"""

from __future__ import annotations

from .component_runtime import automation_component

import argparse
import asyncio
import json
import re
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TYPE_CHECKING

from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from .jd_download_common import (
    acquire_download_lock,
    move_report,
    release_download_lock,
    save_download,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Locator, Page


PLATFORM = "京东"
DEFAULT_DEST = Path(r"C:\Users\win\Desktop\data")
DEFAULT_CACHE_ROOT = DEFAULT_DEST / ".automation_cache" / "jd_promotion"

ALLIANCE_URL = "https://jzt.jd.com/jtk/#/account-bill"
ALLIANCE_DOWNLOAD_URL = "https://jzt.jd.com/jtk/#/download-report"
TONG_URL = "https://jzt.jd.com/account/#/financialRecord"
TONG_DOWNLOAD_URL = "https://jzt.jd.com/account/#/downReport"

ALLIANCE_REPORT = "京东联盟推广费"
TONG_REPORT = "京东通推广费"
ALLIANCE_HISTORY_NAME = "结算信息"
TONG_HISTORY_NAME = "财务记录_消费记录_现金"

ALLIANCE_FEE_TIME_XPATH = '//*[@id="app"]/div/div[2]/div/div/div[2]/div/div/div[1]/div[1]/button/span'
ALLIANCE_SETTLEMENT_OPTION_XPATH = '//*[@id="select_1788333950369"]/ul/li[2]'
ALLIANCE_DATE_XPATH = '//*[@id="app"]/div/div[2]/div/div/div[2]/div/div/div[1]/div[2]/div/div[1]/input'
ALLIANCE_RECENT_30_XPATH = '//*[@id="jzt-body-gw"]/div[6]/div/div[3]/p[4]/label'
ALLIANCE_DOWNLOAD_ICON_XPATH = '//*[@id="app"]/div/div[2]/div/div/div[2]/div/div/div[1]/div[4]/div/button'

TONG_CONSUMPTION_XPATH = '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[2]/div/div/div[2]/div[4]/span'
TONG_TIME_XPATH = '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[1]/div/div[1]/button/span'
TONG_BOOKING_OPTION_XPATH = '//*[@id="select_1788334355443"]/ul/li[2]'
TONG_DATE_XPATH = '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[1]/div/div[3]'
TONG_START_DATE_INPUT_XPATH = (
    '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[1]/div/div[3]'
    '/div[1]/input[1]'
)
TONG_DOWNLOAD_ICON_XPATH = '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[3]/div[4]/div/div[2]/div[2]/div/button/i'

GENERATE_BUTTON_XPATH = '//*[@id="jzt-body-gw"]/div[10]/div[2]/div/div/button'
CONFIRM_BUTTON_XPATH = '//*[@id="jzt-body-gw"]/div[4]/div/div/div/div[3]/div/div/button'
LEFT_MONTH_ARROW_XPATH = '//*[@id="jzt-body-gw"]/div[6]/div/div[1]/div[1]/div[1]/span[2]/i'
RIGHT_MONTH_ARROW_XPATH = '//*[@id="jzt-body-gw"]/div[6]/div/div[1]/div[2]/div[1]/span[5]/i'

REPORT_CHOICES = {
    "union": ("union",),
    "alliance": ("union",),
    "jd_union_ad": ("union",),
    "tong": ("tong",),
    "account": ("tong",),
    "jd_tong_ad": ("tong",),
    "all": ("union", "tong"),
}

MONTH_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月)?"
)
DATE_TIME_RE = re.compile(
    r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})"
    r"(?:[日 T]|\s+)([01]?\d|2[0-3])[:时]([0-5]?\d)[:分]([0-5]?\d)?"
)
DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})(?!\d)")
ERROR_RE = re.compile(r"生成失败|导出失败|失败|异常|错误|取消")


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date
    from_shortcut: bool

    @property
    def start_text(self) -> str:
        return self.start.isoformat()

    @property
    def end_text(self) -> str:
        return self.end.isoformat()


@dataclass
class ReportRow:
    row: "Locator"
    text: str
    created_at: datetime | None
    download_link: "Locator | None"


def _visible(locator: "Locator") -> "Locator":
    return locator.filter(visible=True)


async def click_compat(locator: "Locator") -> None:
    """先走 Playwright 正常点击，固定层/动画阻挡时再触发 DOM click。"""

    try:
        await locator.click(timeout=8_000)
    except Exception:
        await locator.evaluate("element => element.click()")


def parse_date(value: str) -> date:
    """解析 CLI 日期，拒绝无效日期和隐式猜测。"""

    text = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"日期格式错误：{value!r}（支持 YYYY-MM-DD 或 YYYYMMDD）")


def recent_30_day_range(*, today: date | None = None) -> DateRange:
    end = today or date.today()
    return DateRange(end - timedelta(days=29), end, True)


def requested_range(
    start_text: str | None,
    end_text: str | None,
    *,
    today: date | None = None,
) -> DateRange:
    if not start_text and not end_text:
        return recent_30_day_range(today=today)
    if not start_text or not end_text:
        raise ValueError("--start-date 和 --end-date 必须同时提供")
    start = parse_date(start_text)
    end = parse_date(end_text)
    if start > end:
        raise ValueError(f"开始日期不能晚于结束日期：{start} > {end}")
    return DateRange(start, end, False)


def previous_complete_month(*, today: date | None = None) -> tuple[str, str]:
    """返回上一个完整自然月，供父 skill/调用方生成自定义区间。"""

    current = today or date.today()
    first = current.replace(day=1)
    end = first - timedelta(days=1)
    return end.replace(day=1).isoformat(), end.isoformat()


def compact_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def month_key(value: date) -> tuple[int, int]:
    return value.year, value.month


def month_keys_for_range(start: date, end: date) -> tuple[tuple[int, int], ...]:
    """列出日期区间涉及的自然月，跨月日历必须同时可见这些月份。"""

    current = start.replace(day=1)
    result: list[tuple[int, int]] = []
    while current <= end:
        result.append(month_key(current))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return tuple(result)


def month_navigation_direction(
    visible_months: list[tuple[int, int]], target_months: tuple[tuple[int, int], ...]
) -> str | None:
    """决定双面日历下一步点击左切、右切，便于单元测试和稳定导航。"""

    if not visible_months:
        return "right"
    visible = set(visible_months)
    if all(item in visible for item in target_months):
        return None
    visible_min, visible_max = min(visible_months), max(visible_months)
    target_min, target_max = min(target_months), max(target_months)
    if target_min < visible_min:
        return "left"
    if target_max > visible_max:
        return "right"
    # 有月份落在双面区间之间但文本未被识别时，优先向右移动，避免死循环。
    return "right"


def parse_visible_months(text: str) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for year, month in MONTH_RE.findall(text or ""):
        item = (int(year), int(month))
        if 1 <= item[1] <= 12 and item not in result:
            result.append(item)
    return result


def parse_created_at(text: str) -> datetime | None:
    values: list[datetime] = []
    for year, month, day, hour, minute, second in DATE_TIME_RE.findall(text or ""):
        values.append(
            datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second or 0),
            )
        )
    return max(values) if values else None


def report_row_matches_range(text: str, date_range: DateRange) -> bool:
    """判断下载历史首行是否就是本次请求的起止日期。"""

    compact = re.sub(r"\s+", "", text or "").replace(":", "：")
    return (
        f"起：{date_range.start_text}" in compact
        and f"止：{date_range.end_text}" in compact
    )


def report_row_is_current(
    text: str,
    date_range: DateRange,
    submitted_after: datetime | None,
    *,
    report_name: str | None = None,
    require_range: bool = True,
) -> bool:
    """按首行起止日期和创建日期确认任务，避免误下载历史任务。"""

    if report_name and report_name not in text:
        return False
    if require_range and not report_row_matches_range(text, date_range):
        return False
    created_at = parse_created_at(text)
    if created_at is None:
        return False
    expected_day = (submitted_after or datetime.now()).date()
    if created_at.date() != expected_day:
        return False
    if submitted_after is not None and created_at < submitted_after - timedelta(minutes=5):
        return False
    return True


def _state_path(work_dir: Path, report_key: str) -> Path:
    return work_dir / f"jd_{report_key}_promotion_task.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _parse_state_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _report_definition(report_key: str) -> tuple[str, str, str]:
    if report_key == "union":
        return ALLIANCE_URL, ALLIANCE_DOWNLOAD_URL, ALLIANCE_REPORT
    if report_key == "tong":
        return TONG_URL, TONG_DOWNLOAD_URL, TONG_REPORT
    raise ValueError(f"不支持的京东推广费报表：{report_key}")


async def _click_xpath(
    page: "Page",
    xpath: str,
    *,
    fallback_text: str | re.Pattern[str] | None = None,
    timeout: float = 15_000,
) -> "Locator":
    exact = _visible(page.locator(f"xpath={xpath}"))
    if await exact.count():
        target = exact.last
        await target.wait_for(state="visible", timeout=timeout)
        await click_compat(target)
        return target
    if fallback_text is not None:
        if isinstance(fallback_text, re.Pattern):
            fallback = _visible(page.get_by_text(fallback_text, exact=False))
        else:
            fallback = _visible(page.get_by_text(fallback_text, exact=True))
        if await fallback.count():
            target = fallback.last
            await target.wait_for(state="visible", timeout=timeout)
            await click_compat(target)
            return target
    raise RuntimeError(f"页面未找到可点击元素：{xpath}")


async def _select_option(
    page: "Page",
    dropdown_xpath: str,
    option_xpath: str,
    label: str,
) -> None:
    await _click_xpath(page, dropdown_xpath, fallback_text=re.compile(r"交易时间|费用时间"))
    option = _visible(page.locator(f"xpath={option_xpath}"))
    if not await option.count():
        option = _visible(page.get_by_text(label, exact=True))
    if not await option.count():
        # 选项 ID 每次渲染都会变化；账户中心当前实际为
        # #select_<timestamp> .jad-dropdown-item，且文本带换行空白。
        # 某些版本的浮层祖先会被 Playwright 判定为不可见（浮层通过
        # transform 定位），因此不要只依赖 .jad-select-popper:visible，
        # 直接从所有 li 中筛出真正可见且文本完全匹配的候选。
        items = page.locator("li")
        for item_index in range(await items.count() - 1, -1, -1):
            item = items.nth(item_index)
            with suppress(Exception):
                if not await item.is_visible():
                    continue
                item_text = re.sub(r"\s+", "", await item.inner_text(timeout=1_000))
                if item_text == label:
                    option = item
                    break
    if not await option.count():
        raise RuntimeError(f"下拉框未找到“{label}”选项")
    await click_compat(option.last)


async def _page_body_text(page: "Page") -> str:
    with suppress(Exception):
        return (await page.locator("body").inner_text(timeout=3_000)).strip()
    return ""


async def _wait_hash(page: "Page", fragment: str, timeout_seconds: float = 75) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if fragment in page.url:
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"等待京东推广费页面自动跳转超时，当前 URL：{page.url}")


async def _handle_login_redirect(page: "Page") -> None:
    """登录态失效时只点击页面已有的“立即登录”，不读取凭据。"""

    if "shop.jd.com" not in page.url and not re.search(r"login|passport", page.url, re.I):
        return
    button = _visible(page.get_by_role("button", name="立即登录", exact=True))
    if await button.count():
        await click_compat(button.last)
        await asyncio.sleep(1.5)


async def _wait_page_marker(page: "Page", xpath: str, text: str, timeout: float = 45_000) -> None:
    exact = _visible(page.locator(f"xpath={xpath}"))
    fallback = _visible(page.get_by_text(text, exact=True))
    deadline = asyncio.get_running_loop().time() + timeout / 1000
    while asyncio.get_running_loop().time() < deadline:
        if await exact.count() or await fallback.count():
            return
        await asyncio.sleep(0.25)
    raise TimeoutError(f"京东推广费页面加载不完整，未找到“{text}”")


async def _visible_jzt_text(page: "Page") -> str:
    root = _visible(page.locator("#jzt-body-gw"))
    if await root.count():
        with suppress(Exception):
            return (await root.inner_text(timeout=2_000)).strip()
    return ""


async def _ensure_calendar_months(
    page: "Page", target_months: tuple[tuple[int, int], ...]
) -> None:
    """用用户提供的左右切按钮把目标月份放入双面日历。"""

    for _ in range(24):
        months = parse_visible_months(await _visible_jzt_text(page))
        direction = month_navigation_direction(months, target_months)
        if direction is None:
            return
        xpath = LEFT_MONTH_ARROW_XPATH if direction == "left" else RIGHT_MONTH_ARROW_XPATH
        try:
            await _click_xpath(page, xpath)
        except Exception as exc:
            raise RuntimeError(
                f"京东推广费日期弹层未能切换月份：目标={target_months}，当前={months}，方向={direction}"
            ) from exc
        await asyncio.sleep(0.2)
    raise RuntimeError(f"京东推广费日期弹层无法显示目标月份：{target_months}")


async def _calendar_click_day(
    page: "Page", target: date, *, double: bool = False
) -> bool:
    """在包含目标年月的日历面板内点击日，排除上/下月的同名日期。"""

    def month_tokens(value: date) -> tuple[str, ...]:
        return (
            f"{value.year}年{value.month}月",
            f"{value.year}-{value.month:02d}",
            f"{value.year}/{value.month:02d}",
            f"{value.year}-{value.month}",
            f"{value.year}/{value.month}",
        )

    panels = _visible(
        page.locator(
            "#jzt-body-gw .jad-date-picker-content-left, "
            "#jzt-body-gw .jad-date-picker-content-right"
        )
    )
    target_panel: Locator | None = None
    for index in range(await panels.count()):
        panel = panels.nth(index)
        with suppress(Exception):
            panel_text = re.sub(r"\s+", "", await panel.inner_text(timeout=1_000))
            if any(token in panel_text for token in month_tokens(target)):
                target_panel = panel
                break

    if target_panel is None:
        return False
    cells = _visible(target_panel.locator(".jad-date-picker-cell"))
    cell: Locator | None = None
    for index in range(await cells.count()):
        candidate = cells.nth(index)
        try:
            text = (await candidate.inner_text(timeout=1_000)).strip()
            classes = await candidate.get_attribute("class") or ""
        except Exception:
            continue
        if text == str(target.day) and not re.search(
            r"prev-month|next-month|disabled", classes, re.I
        ):
            cell = candidate
            break
    if cell is None:
        return False
    try:
        await cell.wait_for(state="visible", timeout=5_000)
        if double:
            try:
                await cell.dblclick(timeout=5_000)
            except Exception:
                await cell.evaluate(
                    "element => element.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))"
                )
        else:
            await click_compat(cell)
        return True
    except Exception:
        return False


async def _fill_date_inputs_if_available(page: "Page", start: date, end: date) -> bool:
    """日历 DOM 变化时的可见输入保底；不读取或写入任何凭据。"""

    inputs = _visible(page.locator('input[placeholder*="开始"], input[placeholder*="结束"]'))
    if await inputs.count() < 2:
        return False
    start_input, end_input = inputs.nth(0), inputs.nth(1)
    try:
        await start_input.fill(f"{start.isoformat()} 00:00:00")
        await start_input.press("Enter")
        await end_input.click()
        await end_input.fill(f"{end.isoformat()} 23:59:59")
        await end_input.press("Enter")
        return True
    except Exception:
        return False


async def select_custom_range(
    page: "Page",
    trigger_xpath: str,
    date_range: DateRange,
    *,
    fallback_trigger_xpath: str | None = None,
    trigger_already_open: bool = False,
) -> None:
    if not trigger_already_open:
        await _click_xpath(page, trigger_xpath)
    if fallback_trigger_xpath is not None and not trigger_already_open:
        # 账户中心给出的 XPath 指向 .jad-date-picker 外层容器；实际可
        # 触发浮层的是容器内的开始日期 input。仅在首次点击没有打开日历
        # 时使用保底，避免在能正常打开的版本中二次点击关闭浮层。
        calendar = _visible(
            page.locator(
                ".jad-date-picker-content-left, .jad-date-picker-content-right"
            )
        )
        if not await calendar.count():
            await _click_xpath(page, fallback_trigger_xpath)
    target_months = month_keys_for_range(date_range.start, date_range.end)
    await _ensure_calendar_months(page, target_months)
    if date_range.start == date_range.end:
        if not await _calendar_click_day(page, date_range.start, double=True):
            if not await _fill_date_inputs_if_available(page, date_range.start, date_range.end):
                raise RuntimeError(f"日期弹层未找到目标日期：{date_range.start}")
        return

    if not await _calendar_click_day(page, date_range.start):
        if not await _fill_date_inputs_if_available(page, date_range.start, date_range.end):
            raise RuntimeError(f"日期弹层未找到开始日期：{date_range.start}")
        return
    await asyncio.sleep(0.25)
    # 选择开始日后，跨月面板可能自动滚动；再次确认结束月仍然可见。
    await _ensure_calendar_months(page, target_months)
    if not await _calendar_click_day(page, date_range.end):
        if not await _fill_date_inputs_if_available(page, date_range.start, date_range.end):
            raise RuntimeError(f"日期弹层未找到结束日期：{date_range.end}")


@automation_component("jd.promotion.set_date", "京东推广费 · 设置日期", category="report")
async def select_alliance_date(page: "Page", date_range: DateRange) -> None:
    await _click_xpath(page, ALLIANCE_DATE_XPATH)
    if date_range.from_shortcut:
        shortcut = _visible(page.locator(f"xpath={ALLIANCE_RECENT_30_XPATH}"))
        if not await shortcut.count():
            # 当前联盟页的快捷项实际是 label.jad-radio-wrapper，用户提供
            # 的旧版 XPath 已失效；逐个检查可见 label 的纯文本，避免
            # Playwright 的嵌套文本 filter 在 Vue 浮层上漏匹配。
            labels = page.locator("label")
            for index in range(await labels.count() - 1, -1, -1):
                candidate = labels.nth(index)
                with suppress(Exception):
                    if not await candidate.is_visible():
                        continue
                    candidate_text = re.sub(r"\s+", "", await candidate.inner_text(timeout=1_000))
                    if re.fullmatch(
                        r"最近30天|近30天|近(?:1|一)个月", candidate_text
                    ):
                        shortcut = candidate
                        break
        if await shortcut.count():
            await click_compat(shortcut.last)
            print("[JD推广费][联盟][日期] 已选择页面快捷项：最近30天")
            return
        with suppress(Exception):
            await page.keyboard.press("Escape")
    # 自定义范围沿用刚才已经打开的弹层；再次点击日期输入框会在当前
    # Vue 版本中把弹层关闭，导致红框日期明明可见却无法定位。若首次
    # 点击因动画或遮罩没有打开，再补点一次即可。
    calendar = _visible(
        page.locator(
            "#jzt-body-gw .jad-date-picker-content-left, "
            "#jzt-body-gw .jad-date-picker-content-right"
        )
    )
    for _ in range(12):
        if await calendar.count():
            break
        await asyncio.sleep(0.25)
    if not await calendar.count():
        await _click_xpath(page, ALLIANCE_DATE_XPATH)
    await select_custom_range(
        page, ALLIANCE_DATE_XPATH, date_range, trigger_already_open=True
    )
    print(f"[JD推广费][联盟][日期] 已选择：{date_range.start_text} ~ {date_range.end_text}")


@automation_component("jd.promotion.set_date", "京东推广费 · 设置日期", category="report")
async def select_tong_date(page: "Page", date_range: DateRange) -> None:
    if date_range.from_shortcut:
        print("[JD推广费][京东通][日期] 使用页面默认范围：最近30天")
        return
    await select_custom_range(
        page,
        TONG_DATE_XPATH,
        date_range,
        fallback_trigger_xpath=TONG_START_DATE_INPUT_XPATH,
    )
    print(f"[JD推广费][京东通][日期] 已选择：{date_range.start_text} ~ {date_range.end_text}")


@automation_component("jd.promotion.create_export", "京东推广费 · 创建报表", category="report")
async def _start_generation(
    page: "Page", *, report_label: str, before_generation: Any = None
) -> datetime:
    submitted_at = datetime.now()
    generate = _visible(page.locator(f"xpath={GENERATE_BUTTON_XPATH}"))
    if not await generate.count():
        generate = _visible(page.get_by_text("开始生成", exact=True))
    if not await generate.count():
        raise RuntimeError(f"{report_label}未找到“开始生成”按钮")
    await generate.last.wait_for(state="visible", timeout=20_000)
    if before_generation is not None:
        before_generation(submitted_at)
    try:
        await click_compat(generate.last)
    except Exception as exc:
        raise RuntimeError(f"{report_label}点击“开始生成”失败") from exc
    try:
        await _click_xpath(page, CONFIRM_BUTTON_XPATH, fallback_text="确定", timeout=20_000)
    except Exception as exc:
        raise RuntimeError(f"{report_label}下载确认弹窗未找到“确定”按钮") from exc
    return submitted_at


async def _download_link_for_row(row: "Locator", action_column: int) -> "Locator | None":
    cells = row.locator("td")
    if await cells.count() > action_column:
        links = cells.nth(action_column).locator("a")
        for index in range(await links.count()):
            link = links.nth(index)
            with suppress(Exception):
                if not await link.is_visible():
                    continue
            text = re.sub(r"\s+", "", await link.inner_text(timeout=1_000))
            aria_label = re.sub(r"\s+", "", await link.get_attribute("aria-label") or "")
            title = re.sub(r"\s+", "", await link.get_attribute("title") or "")
            # 线上版本的第一个下载操作有时只显示图标，没有文本；
            # 只有在完全没有动作标签时才使用第一个链接兜底，避免把“删除”误判成下载。
            if _is_download_action(
                text,
                index=index,
                aria_label=aria_label,
                title=title,
            ) and not await _is_disabled(link):
                return link
    links = row.locator("a")
    for index in range(await links.count()):
        link = links.nth(index)
        with suppress(Exception):
            if not await link.is_visible():
                continue
        text = re.sub(r"\s+", "", await link.inner_text(timeout=1_000))
        aria_label = re.sub(r"\s+", "", await link.get_attribute("aria-label") or "")
        title = re.sub(r"\s+", "", await link.get_attribute("title") or "")
        if not _is_download_action(
            text,
            index=index,
            aria_label=aria_label,
            title=title,
        ):
            continue
        if not await _is_disabled(link):
            return link
    return None


def _is_download_action(
    text: str,
    *,
    index: int,
    aria_label: str = "",
    title: str = "",
) -> bool:
    labels = re.sub(r"\s+", "", "".join((text, aria_label, title)))
    if "下载" in labels or "download" in labels.lower():
        return True
    return index == 0 and not labels


async def _is_disabled(locator: "Locator") -> bool:
    aria = await locator.get_attribute("aria-disabled")
    classes = await locator.get_attribute("class") or ""
    return aria in {"true", "1"} or bool(re.search(r"disabled|is-disabled", classes, re.I))


async def _report_rows(page: "Page") -> list["Locator"]:
    rows = page.locator("table tbody tr")
    result: list[Locator] = []
    for index in range(await rows.count()):
        row = rows.nth(index)
        with suppress(Exception):
            if await row.is_visible():
                result.append(row)
    return result


@automation_component("jd.promotion.wait_ready", "京东推广费 · 等待报表", category="report")
async def wait_report_ready(
    page: "Page",
    *,
    date_range: DateRange,
    report_name: str,
    require_range: bool,
    action_column: int,
    submitted_after: datetime | None,
    timeout_seconds: float,
    report_label: str,
) -> ReportRow:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_status = ""
    next_refresh_at = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        rows = await _report_rows(page)
        if rows:
            first = rows[0]
            try:
                text = (await first.inner_text(timeout=1_000)).strip()
            except Exception:
                text = ""
            created_at = parse_created_at(text)
            row = ReportRow(
                first,
                text,
                created_at,
                await _download_link_for_row(first, action_column),
            )
            if report_row_is_current(
                text,
                date_range,
                submitted_after,
                report_name=report_name,
                require_range=require_range,
            ):
                if row.download_link is not None:
                    range_message = (
                        f"起止日期={date_range.start_text}~{date_range.end_text}"
                        if require_range
                        else "页面默认近30天范围"
                    )
                    print(
                        f"[JD推广费][{report_label}][任务] 首行已核对："
                        f"{range_message}，"
                        f"创建时间={row.created_at or '未知'}，可下载"
                    )
                    return row
                last_status = text
                if ERROR_RE.search(text):
                    raise RuntimeError(f"{report_label}报表生成失败：{text[:300]}")
                status_message = f"首行是本次任务但仍未生成：{text[:300]}"
            else:
                status_message = f"首行不是本次任务，继续等待：{text[:300]}"
            if status_message != last_status:
                print(f"[JD推广费][{report_label}][任务] {status_message}")
            last_status = status_message
        else:
            status_message = "导出任务列表仍在加载"
            if status_message != last_status:
                print(
                    f"[JD推广费][{report_label}][任务] {status_message}"
                )
            last_status = status_message
        now = asyncio.get_running_loop().time()
        if now >= next_refresh_at:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=60_000)
            except PlaywrightTimeout:
                pass
            next_refresh_at = asyncio.get_running_loop().time() + 5
        await asyncio.sleep(1)
    raise TimeoutError(
        f"等待{report_label}下载按钮超时，最后任务状态：{last_status[:300] or '未找到本次任务'}"
    )


@automation_component("file.download", "下载报表文件", category="file")
async def _download_report_file(
    page: "Page", row: ReportRow, *, action_column: int, work_dir: Path, fallback: str
) -> Path:
    link = row.download_link
    if link is None:
        link = await _download_link_for_row(row.row, action_column)
    if link is None:
        raise RuntimeError("最新京东推广费任务的操作列未找到可用下载按钮")
    try:
        async with page.expect_download(timeout=120_000) as info:
            await click_compat(link)
        downloaded = await save_download(await info.value, work_dir, fallback)
    except PlaywrightTimeout as exc:
        raise TimeoutError("京东推广费报表下载超时") from exc
    suffix = downloaded.suffix.lower()
    if suffix not in {".xlsx", ".xls", ".xlsm", ".csv", ".zip"}:
        raise RuntimeError(f"京东推广费下载文件扩展名不受支持：{downloaded}")
    return downloaded


async def _open_alliance_page(
    page: "Page", date_range: DateRange, *, before_generation: Any = None
) -> datetime:
    await page.goto(ALLIANCE_URL, wait_until="domcontentloaded", timeout=60_000)
    await _handle_login_redirect(page)
    await _wait_page_marker(page, ALLIANCE_FEE_TIME_XPATH, "费用时间")
    await _select_option(
        page,
        ALLIANCE_FEE_TIME_XPATH,
        ALLIANCE_SETTLEMENT_OPTION_XPATH,
        "结算时间",
    )
    await select_alliance_date(page, date_range)
    await _click_xpath(page, ALLIANCE_DOWNLOAD_ICON_XPATH, fallback_text=re.compile(r"下载"))
    submitted_at = await _start_generation(
        page, report_label="京东联盟", before_generation=before_generation
    )
    await _wait_hash(page, "#/download-report")
    return submitted_at


async def _open_tong_page(
    page: "Page", date_range: DateRange, *, before_generation: Any = None
) -> datetime:
    await page.goto(TONG_URL, wait_until="domcontentloaded", timeout=60_000)
    await _handle_login_redirect(page)
    await _wait_page_marker(page, TONG_CONSUMPTION_XPATH, "消费记录")
    await _click_xpath(page, TONG_CONSUMPTION_XPATH, fallback_text="消费记录")
    await _select_option(page, TONG_TIME_XPATH, TONG_BOOKING_OPTION_XPATH, "记账时间")
    await select_tong_date(page, date_range)
    await _click_xpath(page, TONG_DOWNLOAD_ICON_XPATH, fallback_text=re.compile(r"下载"))
    submitted_at = await _start_generation(
        page, report_label="京东通", before_generation=before_generation
    )
    await _wait_hash(page, "#/downReport")
    return submitted_at


@automation_component("report.archive", "归档标准报表", category="file")
async def _archive_download(
    downloaded: Path,
    *,
    report_label: str,
    business_date: str,
    platform: str,
    company: str,
    shop: str,
    dest: Path,
) -> str:
    if not downloaded.is_file() or downloaded.stat().st_size <= 0:
        raise RuntimeError(f"{report_label}下载文件为空：{downloaded}")
    return await asyncio.to_thread(
        move_report,
        downloaded,
        platform,
        company,
        shop,
        report_label,
        business_date,
        dest,
    )


async def run_one(
    context: "BrowserContext",
    *,
    report_key: str,
    date_range: DateRange,
    business_date: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    timeout_seconds: float,
) -> str:
    page: Page | None = None
    report_work_dir = work_dir / report_key
    report_work_dir.mkdir(parents=True, exist_ok=True)
    state_path = _state_path(report_work_dir, report_key)
    state = _read_state(state_path)
    expected = {
        "report_key": report_key,
        "start_date": date_range.start_text,
        "end_date": date_range.end_text,
        "business_date": business_date,
    }
    if state and any(state.get(key) not in {None, value} for key, value in expected.items()):
        raise RuntimeError(f"{report_key} 工作目录已有不同日期任务状态：{state_path}")

    try:
        downloaded: Path | None = None
        if state.get("stage") == "DOWNLOADED":
            candidate = Path(str(state.get("download_path") or ""))
            if candidate.is_file() and candidate.stat().st_size > 0:
                downloaded = candidate

        page = await context.new_page()
        report_url, download_url, report_label = _report_definition(report_key)
        action_column = 4 if report_key == "union" else 5
        if downloaded is None:
            if state.get("stage") in {"SUBMITTING", "SUBMITTED"}:
                submitted_after = _parse_state_datetime(state.get("submitted_at"))
                print(f"[JD推广费][{report_label}][恢复] 复用已提交任务，不重复生成")
                await page.goto(download_url, wait_until="domcontentloaded", timeout=60_000)
            else:
                # 只有生成按钮已经定位后才落盘 SUBMITTING，避免日期选择等
                # 前置阶段失败时留下一个看似已提交的假状态。
                def mark_submitting(submitted_at: datetime) -> None:
                    nonlocal state
                    state = {
                        **expected,
                        "stage": "SUBMITTING",
                        "submitted_at": submitted_at.isoformat(timespec="seconds"),
                    }
                    _write_state(state_path, state)

                if report_key == "union":
                    submitted_after = await _open_alliance_page(
                        page, date_range, before_generation=mark_submitting
                    )
                else:
                    submitted_after = await _open_tong_page(
                        page, date_range, before_generation=mark_submitting
                    )
                state = {
                    **expected,
                    "stage": "SUBMITTED",
                    "submitted_at": submitted_after.isoformat(timespec="seconds"),
                }
                _write_state(state_path, state)
                print(f"[JD推广费][{report_label}][任务] 已提交，等待下载页刷新")

            row = await wait_report_ready(
                page,
                date_range=date_range,
                report_name=(
                    ALLIANCE_HISTORY_NAME if report_key == "union" else TONG_HISTORY_NAME
                ),
                require_range=report_key != "union" and not date_range.from_shortcut,
                action_column=action_column,
                submitted_after=submitted_after,
                timeout_seconds=timeout_seconds,
                report_label=report_label,
            )
            downloaded = await _download_report_file(
                page,
                row,
                action_column=action_column,
                work_dir=report_work_dir,
                fallback=f"jd_{report_key}_promotion.xlsx",
            )
            state["stage"] = "DOWNLOADED"
            state["download_path"] = str(downloaded)
            _write_state(state_path, state)
            print(f"[JD推广费][{report_label}][下载] 临时文件：{downloaded}")
        else:
            report_label = _report_definition(report_key)[2]
            print(f"[JD推广费][{report_label}][恢复] 复用已下载文件：{downloaded}")

        move_log = await _archive_download(
            downloaded,
            report_label=report_label,
            business_date=business_date,
            platform=platform,
            company=company,
            shop=shop,
            dest=dest,
        )
        with suppress(OSError):
            state_path.unlink()
        print(move_log)
        return move_log
    finally:
        if page is not None:
            with suppress(Exception):
                await page.close()


@automation_component("jd.promotion.workflow", "京东推广费 · 下载流程", category="workflow")
async def run(
    cdp_url: str,
    *,
    report_keys: tuple[str, ...],
    date_range: DateRange,
    business_date: str,
    platform: str,
    company: str,
    shop: str,
    work_dir: Path,
    dest: Path,
    timeout_seconds: float,
) -> int:
    lock = await asyncio.to_thread(acquire_download_lock)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器中没有可用上下文")
            context = browser.contexts[0]
            for report_key in report_keys:
                await run_one(
                    context,
                    report_key=report_key,
                    date_range=date_range,
                    business_date=business_date,
                    platform=platform,
                    company=company,
                    shop=shop,
                    work_dir=work_dir,
                    dest=dest,
                    timeout_seconds=timeout_seconds,
                )
    finally:
        await asyncio.to_thread(release_download_lock, lock)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="京东联盟与京东通推广费报表下载")
    parser.add_argument("--cdp", required=True, help="本次 Cloak Login profile 返回的 wsEndpoint")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--company", required=True)
    parser.add_argument("--shop", required=True)
    parser.add_argument(
        "--report",
        default="all",
        help="all、union/alliance、tong/account；默认依次下载联盟和京东通",
    )
    parser.add_argument("--start-date", default=None, help="自定义开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="自定义结束日期 YYYY-MM-DD")
    parser.add_argument("--business-date", default=None, help="归档文件日期，默认取结束日期")
    parser.add_argument("--work-dir", "--src", dest="work_dir", default=None)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()

    if not args.cdp.startswith(("ws://", "wss://")):
        print("--cdp 必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        return 2
    if args.report not in REPORT_CHOICES:
        print(f"--report 不支持：{args.report}；可选 all、union、alliance、tong、account", file=sys.stderr)
        return 2
    if args.timeout_seconds <= 0:
        print("--timeout-seconds 必须大于 0", file=sys.stderr)
        return 2
    try:
        date_range = requested_range(args.start_date, args.end_date)
        business_date = compact_date(parse_date(args.business_date)) if args.business_date else compact_date(date_range.end)
        work_dir = Path(args.work_dir) if args.work_dir else DEFAULT_CACHE_ROOT / args.shop
        report_keys = REPORT_CHOICES[args.report]
        return asyncio.run(
            run(
                args.cdp,
                report_keys=report_keys,
                date_range=date_range,
                business_date=business_date,
                platform=args.platform,
                company=args.company,
                shop=args.shop,
                work_dir=work_dir,
                dest=Path(args.dest),
                timeout_seconds=args.timeout_seconds,
            )
        )
    except (ValueError, TimeoutError, PlaywrightTimeout, RuntimeError, OSError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
