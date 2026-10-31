# -*- coding: utf-8 -*-
"""小红书账单下载共用的登录、下载与业务校验能力。"""

from __future__ import annotations

from .component_runtime import automation_component

import asyncio
import re
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from openpyxl import load_workbook

from ..extract_report import unique_path
from .report_validation import validate_report_columns, warn_unread_sheets

if TYPE_CHECKING:
    from playwright.async_api import Download, Page

LOGIN_HOST = "customer.xiaohongshu.com"
ARK_HOST = "ark.xiaohongshu.com"
XHS_HOME_URL = "https://ark.xiaohongshu.com/app-system/home"
ROW_SELECTOR = "tr.prada-table-row"
FUND_HEADERS = (
    "动账时间",
    "业务单号",
    "动账场景",
    "动账方向",
    "动账金额",
    "动账账户",
    "动账后余额",
)
SETTLEMENT_INCOME_HEADERS = (
    "订单号",
    "售后单号",
    "下单时间",
    "完成时间",
    "结算时间",
    "交易类型",
    "动账金额",
    "结算账户",
    "计佣基数",
    "商品实付/实退",
    "运费实付/实退",
    "商家优惠总额",
    "平台优惠补贴",
    "政府券优惠补贴",
    "平台佣金",
    "买手佣金",
    "花呗分期手续费",
)
SETTLEMENT_EXPENSE_HEADERS = (
    "订单号",
    "业务款项",
    "业务单号",
    "结算时间",
    "结算账户",
    "动账金额",
    "佣金金额",
    "备注",
)

# 小红书的活动广告使用 portal 挂载，层级编号并不稳定；用户当前页面
# 的已知路径保留为第一优先级，其他选择器只在确认可见且像广告时使用。
AD_POPUP_ROOT_XPATH = "xpath=/html/body/div[3]/div"
AD_POPUP_CLOSE_XPATH = "xpath=/html/body/div[3]/div/div[1]/span/svg"
AD_POPUP_CLOSE_PARENT_XPATH = "xpath=/html/body/div[3]/div/div[1]/span"
_AD_CLOSE_SELECTORS = (
    'button[aria-label*="关闭"], [role="button"][aria-label*="关闭"], '
    'button[title*="关闭"], [class*="close" i], svg[class*="close" i], '
    'button:has-text("关闭")',
)
_AD_CLASS_RE = re.compile(
    r"advert|ad[-_]?popup|activity|promotion|campaign|marketing|banner|floating",
    re.IGNORECASE,
)
_AD_TEXT_RE = re.compile(r"广告|活动|优惠|福利|红包|礼包|权益|开通|新人|限时")
_BLOCKING_TEXT_RE = re.compile(
    r"订单|导出|查询|近\s*30|开始时间|结束时间|确定|取消|登录|账号|密码|请注意|提示"
)


def is_login_page(page: "Page") -> bool:
    return urlparse(page.url).hostname == LOGIN_HOST


async def click_compat(locator: "Locator", *, timeout: int = 8_000) -> None:
    """优先使用真实点击，固定层或动画阻挡时退回到 DOM click。"""
    try:
        await locator.click(timeout=timeout)
    except Exception:
        await locator.evaluate(
            """
            element => {
                if (typeof element.click === 'function') {
                    element.click();
                    return;
                }
                element.dispatchEvent(new MouseEvent('click', {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                }));
            }
            """
        )


async def _is_visible(locator: "Locator") -> bool:
    with suppress(Exception):
        return await locator.is_visible()
    return False


async def _first_visible(locator: "Locator"):
    with suppress(Exception):
        count = await locator.count()
        for index in range(count):
            candidate = locator.nth(index)
            if await _is_visible(candidate):
                return candidate
    return None


def is_probable_ad_popup(class_name: str, text: str) -> bool:
    """判断一个可见 portal 是否像广告活动，而不是订单操作弹窗。"""
    class_value = class_name or ""
    text_value = re.sub(r"\s+", "", text or "")
    if _BLOCKING_TEXT_RE.search(text_value):
        return False
    return bool(_AD_CLASS_RE.search(class_value) or _AD_TEXT_RE.search(text_value))


async def _close_candidate(root: "Locator"):
    candidate = await _first_visible(root.locator(", ".join(_AD_CLOSE_SELECTORS)))
    if candidate is not None:
        return candidate
    # 已知小红书广告的关闭控件就是一个没有可访问文本的 SVG。
    return await _first_visible(root.locator("svg"))


async def _click_ad_close(close: "Locator") -> bool:
    """点击关闭控件；如果 portal 重绘后候选已消失，交给调用方重新扫描。"""
    try:
        await click_compat(close, timeout=4_000)
    except Exception:
        if await _is_visible(close):
            raise
        return False
    return True


async def dismiss_ad_popups(page: "Page", *, max_popups: int = 3) -> int:
    """智能关闭小红书广告活动弹窗，返回本次关闭数量。

    只处理已知广告路径，或同时满足“可见、像广告、含关闭控件”的动态
    portal。包含订单、日期、导出、确定等业务文本的弹窗会被跳过，避免
    把日期面板或导出确认框当成广告关闭。
    """
    dismissed = 0
    for _ in range(max_popups):
        close = None
        known_root = page.locator(AD_POPUP_ROOT_XPATH)
        if await _is_visible(known_root):
            for selector in (
                AD_POPUP_CLOSE_XPATH,
                AD_POPUP_CLOSE_PARENT_XPATH,
            ):
                close = await _first_visible(page.locator(selector))
                if close is not None:
                    break
            if close is None:
                close = await _close_candidate(known_root)

        if close is None:
            roots = page.locator(
                'body > div, [role="dialog"], [class*="popup" i], '
                '[class*="modal" i], [class*="activity" i], [class*="advert" i]'
            )
            with suppress(Exception):
                count = min(await roots.count(), 80)
                for index in range(count):
                    root = roots.nth(index)
                    if not await _is_visible(root):
                        continue
                    class_name = await root.get_attribute("class") or ""
                    text = ""
                    with suppress(Exception):
                        text = await root.inner_text(timeout=500)
                    if not is_probable_ad_popup(class_name, text):
                        continue
                    close = await _close_candidate(root)
                    if close is not None:
                        break

        if close is None:
            break
        if not await _click_ad_close(close):
            continue
        dismissed += 1
        with suppress(Exception):
            await page.wait_for_timeout(120)
    return dismissed


@automation_component("xhs.session.ensure_login", "小红书 · 检查登录态", category="browser")
async def ensure_logged_in(page: "Page") -> None:
    """必要时使用已保存的账号密码完成小红书账号登录。"""
    if not is_login_page(page):
        return
    account_login = page.get_by_text("账号登录", exact=True)
    await account_login.wait_for(state="visible", timeout=30_000)
    email = page.locator('input[name="email"]')
    password = page.locator('input[name="password"]')
    form_visible = (
        await email.count()
        and await password.count()
        and await email.is_visible()
        and await password.is_visible()
    )
    if not form_visible:
        await account_login.click()
        await email.wait_for(state="visible", timeout=30_000)
        await password.wait_for(state="visible", timeout=30_000)

    # Cloak profile 的浏览器自动填充可能晚于表单可见；不要在第一帧就把
    # 暂时空值误报为缺少凭据，否则会在登录按钮点击之前退出。
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        if (await email.input_value()).strip() and await password.input_value():
            break
        await asyncio.sleep(0.25)
    else:
        raise RuntimeError("小红书账号密码在等待 profile 自动填充后仍为空")

    agreement = page.locator('input[type="checkbox"]').first
    if not await agreement.is_checked():
        await agreement.check(force=True)
    login_button = page.locator("button.beer-login-btn")
    await login_button.wait_for(state="visible", timeout=10_000)
    await login_button.scroll_into_view_if_needed()
    await login_button.click(timeout=10_000)
    deadline = asyncio.get_running_loop().time() + 60
    while asyncio.get_running_loop().time() < deadline:
        if urlparse(page.url).hostname == ARK_HOST:
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"小红书登录后未进入商家后台：{page.url}")


@automation_component("xhs.report.open", "小红书 · 打开报表页", category="report")
async def open_report_page(context, target_url: str) -> "Page":
    """复用 profile 页面登录后，在独立页面打开报表页。"""
    session_page = next(
        (
            candidate
            for candidate in context.pages
            if not candidate.is_closed()
            and urlparse(candidate.url).hostname in (LOGIN_HOST, ARK_HOST)
        ),
        None,
    )
    if session_page is None:
        session_page = await context.new_page()
        await session_page.goto(
            "https://ark.xiaohongshu.com/app-system/home",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
    await ensure_logged_in(session_page)
    await dismiss_ad_popups(session_page)
    page = await context.new_page()
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    await ensure_logged_in(page)
    await dismiss_ad_popups(page)
    if not page.url.startswith(target_url):
        await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    if urlparse(page.url).hostname != ARK_HOST:
        raise RuntimeError(f"小红书报表页打开失败：{page.url}")
    return page


def extract_business_date(row_text: str, mode: str) -> str:
    match = re.search(r"(20\d{2})[.-](\d{2})[.-](\d{2})", row_text)
    if not match:
        raise RuntimeError(f"无法识别最新{mode}账单日期：{row_text!r}")
    year, month, day = match.groups()
    return f"{year}{month}" if mode == "month" else f"{year}-{month}-{day}"


@automation_component("report.mode.select", "选择日 / 月报表模式", category="report")
async def select_bill_mode(page: "Page", mode: str) -> None:
    tab_name = "月度汇总单" if mode == "month" else "日账单"
    tab = page.locator("div.d-tabs-header").filter(
        has_text=re.compile(rf"^\s*{re.escape(tab_name)}\s*$")
    ).first
    await tab.wait_for(state="visible", timeout=30_000)
    await click_compat(tab)


@automation_component("report.latest.locate", "定位最新可下载报表", category="report")
async def latest_bill_row(page: "Page", mode: str, target_date: str | None = None):
    if target_date:
        from .historical_bill import locate_bill
        if mode == "day":
            start = page.locator('.d-daterangepicker-input-start input')
            end = page.locator('.d-daterangepicker-input-end input')
            await end.fill(target_date);await end.press('Enter')
            await start.fill(target_date);await start.press('Enter')
            if await start.input_value() != target_date or await end.input_value() != target_date:
                raise RuntimeError("小红书目标账单日期未生效；已停止下载")
            await page.get_by_text('查询', exact=True).click()
        return await locate_bill(page, ROW_SELECTOR, target_date, mode, extract_business_date,
                                 lambda row: row.get_by_text("下载账单", exact=True))
    rows = page.locator(ROW_SELECTOR)
    await rows.first.wait_for(state="visible", timeout=60_000)
    # The newest row can still be detail-only while the first downloadable
    # report is an older row. Select the newest row that actually exposes the
    # download action instead of waiting forever on the detail-only row.
    row = rows.filter(has=page.get_by_text("下载账单", exact=True)).first
    await row.wait_for(state="visible", timeout=60_000)
    row_text = (await row.inner_text()).strip()
    return row, extract_business_date(row_text, mode)


@automation_component("file.download", "保存浏览器下载文件", category="file")
async def save_download(download: "Download", directory: Path, fallback_name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = unique_path(directory, download.suggested_filename or fallback_name)
    await download.save_as(str(target))
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"小红书下载文件为空：{target}")
    if target.suffix.lower() != ".xlsx":
        raise RuntimeError(f"小红书账单格式异常：{target.suffix}")
    return target


def read_header(worksheet) -> tuple[str, ...]:
    if hasattr(worksheet, "reset_dimensions"):
        worksheet.reset_dimensions()
    row = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True))
    return tuple(str(value).strip() for value in row if value is not None)


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_fund_report(report: Path) -> None:
    workbook = load_workbook(report, read_only=True, data_only=True)
    try:
        if not workbook.worksheets or workbook.worksheets[0].title != "资金账单明细":
            raise RuntimeError(
                f"小红书资金账单首个工作表异常：期望“资金账单明细”，实际为 {workbook.sheetnames}"
            )
        warn_unread_sheets("小红书资金账单", workbook.sheetnames, ("资金账单明细",))
        validate_report_columns(
            read_header(workbook.worksheets[0]),
            FUND_HEADERS,
            report_name="小红书资金账单",
            missing_error_prefix="小红书资金账单表头异常，缺少必需字段：",
        )
    finally:
        workbook.close()


@automation_component("report.validate.schema", "校验报表结构", category="file")
def validate_settlement_report(report: Path) -> None:
    workbook = load_workbook(report, read_only=True, data_only=True)
    try:
        required_sheets = ("订单结算", "其他服务款")
        missing = [sheet for sheet in required_sheets if sheet not in workbook.sheetnames]
        if missing:
            raise RuntimeError(f"小红书结算账单缺少工作表：{'、'.join(missing)}")
        warn_unread_sheets("小红书结算账单", workbook.sheetnames, required_sheets)
        income_header = read_header(workbook["订单结算"])
        expense_header = read_header(workbook["其他服务款"])
        validate_report_columns(
            income_header,
            SETTLEMENT_INCOME_HEADERS,
            report_name="小红书订单结算",
            missing_error_prefix="小红书订单结算表头异常，缺少必需字段：",
        )
        validate_report_columns(
            expense_header,
            SETTLEMENT_EXPENSE_HEADERS,
            report_name="小红书其他服务款",
            optional_columns=("佣金金额",),
            missing_error_prefix="小红书其他服务款表头异常，缺少必需字段：",
        )
    finally:
        workbook.close()
