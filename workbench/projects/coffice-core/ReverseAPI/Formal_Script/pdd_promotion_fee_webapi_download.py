#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过拼多多推广平台 WebAPI 下载推广费原始 XLS。

脚本只把浏览器自动化用于完成真实入口和筛选，并在点击“查询”时监听
``getDailyInvoice`` 的自然请求。正式查询和导出均使用同一页面上下文发起
WebAPI 请求：保留自然请求中的动态字段和动态请求头，只替换日期字段。

默认用法（昨天）：

    .venv\\Scripts\\python.exe -m Formal_Script.pdd_promotion_fee_webapi_download

使用页面自然默认日期范围（兼容旧调用）：

    .venv\\Scripts\\python.exe -m Formal_Script.pdd_promotion_fee_webapi_download \\
        --date-mode default

指定日期范围：

    .venv\\Scripts\\python.exe -m Formal_Script.pdd_promotion_fee_webapi_download \\
        --start-date 2026-09-01 --end-date 2026-09-08

说明：
- 必须从商家后台首页点击“推广账户”，再点击“财务流水”；不把已打开的
  推广费深链页面作为入口。
- 不操作日期输入框。默认模式直接使用自然查询请求的两个日期字段；其他
  模式只在 WebAPI 请求体中替换这两个字段。
- 先查询行数，0 条时直接结束，不调用导出接口。
- 只保存原始 XLS/ZIP，不解压、不改写、不做业务表头校验。
- 不输出、硬编码或持久化 Cookie、Anti-Content、crawlerInfo 和签名下载地址。
- 不关闭用户已有的浏览器页面或 profile；脚本结束时只断开 CDP 连接。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import requests


try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection

try:
    from .pdd_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        download_original_file,
        is_human_error_message,
        log as pdd_log,
    )
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from pdd_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        download_original_file,
        is_human_error_message,
        log as pdd_log,
    )

PROFILE_NAME = "PDD-拼多多-养颜轻食"
MMS_HOST = "mms.pinduoduo.com"
PROMOTION_HOST = "yingxiao.pinduoduo.com"
MMS_HOME_URL = "https://mms.pinduoduo.com/home"
PROMOTION_FINANCE_URL = "https://yingxiao.pinduoduo.com/mains/account/finance"
PROMOTION_REPORT_URL = "https://yingxiao.pinduoduo.com/mains/account/report"

PROMOTION_NAV_SELECTOR = (
    '#__msfe__side-nav_item_3516 '
    'a[href^="https://yingxiao.pinduoduo.com/mains/account/finance"]'
)
PROMOTION_NAV_XPATH = '//*[@id="__msfe__side-nav_item_3516"]/a/span'
FINANCE_FLOW_XPATH = (
    '//*[@id="page-container"]/div/div/div[1]/div/div[2]/ul/li[2]/span'
)
FUND_TYPE_INPUT = "#rc_select_0"
FLOW_TYPE_INPUT = "#rc_select_1"

QUERY_PATH = "/mms-gateway/reinhardt/invoice/getDailyInvoice"
EXPORT_PATH = "/mms-gateway/reinhardt/invoice/exportDailyInvoice"
QUERY_URL = f"https://{PROMOTION_HOST}{QUERY_PATH}"
EXPORT_URL = f"https://{PROMOTION_HOST}{EXPORT_PATH}"

TZ_CN = timezone(timedelta(hours=8))
DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})$")

# 只复用自然请求中确实出现的动态上下文；Cookie、Origin、Referer、Host 等
# 由浏览器 fetch 自动生成或由浏览器上下文携带，不从页面读取后手工伪造。
ALLOWED_DYNAMIC_HEADERS = {
    "anti-content",
    "x-fin-sherlock-passid",
    "passid",
    "accesstoken",
    "access-token",
    "verifyauthtoken",
}

SESSION_MARKERS = (
    "会话异常",
    "登录失效",
    "请先登录",
    "登录后继续",
    "未登录",
)
HUMAN_VERIFICATION_MARKERS = (
    "验证码",
    "安全验证",
    "风险验证",
    "滑块验证",
    "身份验证",
)


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any


@dataclass(frozen=True)
class NaturalQueryContext:
    payload: dict[str, Any]
    dynamic_headers: dict[str, str]
    response: ApiResponse


def log(stage: str, message: str) -> None:
    pdd_log("推广费", stage, message)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\ufeff", "").split())


def parse_json_text(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ApiError("接口响应不是合法 JSON") from exc


def parse_request_payload(post_data: str | None) -> dict[str, Any]:
    if not post_data:
        raise ApiError("自然查询请求缺少 POST 请求体")
    try:
        payload = json.loads(post_data)
    except (TypeError, ValueError) as exc:
        raise ApiError("自然查询请求体不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ApiError("自然查询请求体不是 JSON 对象")
    return payload


def normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items() if value}


def dynamic_headers_from_request(headers: dict[str, Any] | None) -> dict[str, str]:
    normalized = normalize_headers(headers)
    return {
        key: value
        for key, value in normalized.items()
        if key in ALLOWED_DYNAMIC_HEADERS
    }


def parse_date(value: str, *, option_name: str) -> date:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError(f"{option_name} 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{option_name} 不是有效日期：{value}") from exc


def date_to_timestamp(value: str, *, end_of_day: bool, milliseconds: bool) -> int:
    parsed = parse_date(value, option_name="API 日期")
    moment = datetime(
        parsed.year,
        parsed.month,
        parsed.day,
        23 if end_of_day else 0,
        59 if end_of_day else 0,
        59 if end_of_day else 0,
        tzinfo=TZ_CN,
    )
    timestamp = int(moment.timestamp())
    return timestamp * 1000 if milliseconds else timestamp


def _date_value_like(sample: Any, value: str, *, end_of_day: bool) -> Any:
    """按自然请求字段类型替换日期，兼容字符串、秒级和毫秒级时间戳。"""

    if isinstance(sample, bool):
        raise ValueError("自然查询日期字段类型异常")
    if isinstance(sample, int):
        return date_to_timestamp(
            value,
            end_of_day=end_of_day,
            milliseconds=abs(sample) >= 100_000_000_000,
        )
    if isinstance(sample, float):
        return float(
            date_to_timestamp(
                value,
                end_of_day=end_of_day,
                milliseconds=abs(sample) >= 100_000_000_000,
            )
        )
    if isinstance(sample, str):
        # 当前实测接口使用 YYYY-MM-DD；不把字符串日期转成时间戳。
        return value
    raise ValueError("自然查询日期字段类型异常")


def replace_date_fields(
    natural_payload: dict[str, Any], start_date: str, end_date: str
) -> dict[str, Any]:
    """保留自然请求所有字段，只替换 startDate/endDate。"""

    start = parse_date(start_date, option_name="开始日期")
    end = parse_date(end_date, option_name="结束日期")
    if start > end:
        raise ValueError(f"开始日期晚于结束日期：{start_date} > {end_date}")
    if "startDate" not in natural_payload or "endDate" not in natural_payload:
        raise ValueError("自然查询请求未捕获 startDate/endDate")
    payload = dict(natural_payload)
    payload["startDate"] = _date_value_like(
        natural_payload["startDate"], start_date, end_of_day=False
    )
    payload["endDate"] = _date_value_like(
        natural_payload["endDate"], end_date, end_of_day=True
    )
    return payload


def default_business_date() -> str:
    return (datetime.now(TZ_CN).date() - timedelta(days=1)).isoformat()


def natural_date_to_iso(value: Any, *, field_name: str) -> str:
    """把自然请求中的日期字段统一成日志和文件名使用的 YYYY-MM-DD。"""

    if isinstance(value, str):
        parse_date(value, option_name=field_name)
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        seconds = numeric / 1000 if abs(numeric) >= 100_000_000_000 else numeric
        try:
            return datetime.fromtimestamp(seconds, TZ_CN).date().isoformat()
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(f"{field_name} 时间戳无法转换为日期") from exc
    raise ValueError(f"{field_name} 不是可识别的日期字段")


def result_count(body: Any) -> int:
    """读取 getDailyInvoice 的 total，兼容 total 缺失时的结果数组。"""

    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, dict):
        total = result.get("total")
        if total is not None:
            try:
                count = int(total)
            except (TypeError, ValueError) as exc:
                raise ApiError("查询响应 total 不是整数") from exc
            if count < 0:
                raise ApiError("查询响应 total 为负数")
            return count
        rows = result.get("result")
        if isinstance(rows, list):
            return len(rows)
    if isinstance(result, list):
        return len(result)
    if isinstance(body, list):
        return len(body)
    raise ApiError("查询响应缺少 result.total/result 明细")


def ensure_api_success(response: ApiResponse, *, label: str) -> Any:
    if not 200 <= response.status < 300:
        raise ApiError(f"{label}接口 HTTP 状态异常：{response.status}")
    if not isinstance(response.body, dict) or response.body.get("success") is not True:
        message = (
            response.body.get("errorMsg")
            or response.body.get("message")
            or response.body.get("msg")
            if isinstance(response.body, dict)
            else None
        )
        if is_human_error_message(message):
            raise NeedsHumanError(str(message)[:160])
        error_code = (
            response.body.get("errorCode")
            if isinstance(response.body, dict)
            else None
        )
        suffix = f"，错误码={error_code}" if error_code is not None else ""
        raise ApiError(f"{label}接口返回失败{suffix}")
    return response.body


def extract_export_url(body: Any) -> str:
    value = body.get("result") if isinstance(body, dict) else None
    if not isinstance(value, str) or urlparse(value).scheme not in {"http", "https"}:
        raise ApiError("导出响应缺少有效原始文件地址")
    return value


def download_file_requests(
    signed_url: str,
    *,
    cookies: list[dict[str, Any]],
    user_agent: str,
    output_dir: Path,
    start_date: str,
    end_date: str,
    proxy: str | None = None,
) -> Path:
    """在浏览器同一登录态下保存 pfs 返回的原始文件。"""

    suffix = Path(urlparse(signed_url).path).suffix.lower()
    if suffix not in {".xls", ".xlsx", ".zip"}:
        suffix = ".xls"
    return download_original_file(
        signed_url,
        output_dir,
        f"PDD_promotion_fee_{start_date}_to_{end_date}{suffix}",
        headers={
            "Accept": "*/*",
            "Referer": PROMOTION_REPORT_URL,
            "User-Agent": user_agent or "Mozilla/5.0",
        },
        cookies=cookies,
        proxy=proxy,
        timeout=(15, 120),
    )


async def execute_api_chain(
    post: Callable[[str, dict[str, Any]], Awaitable[ApiResponse]],
    download: Callable[[str, str, str, Path], Awaitable[Path]],
    natural_payload: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    output_dir: Path,
) -> Path | None:
    """可测试的查询→0 条短路/导出→下载链路。"""

    payload = replace_date_fields(natural_payload, start_date, end_date)
    query_response = await post(QUERY_URL, payload)
    query_body = ensure_api_success(query_response, label="查询")
    count = result_count(query_body)
    log("查询", f"WebAPI 查询完成，现金支出={count}条")
    if count == 0:
        log("完成", "查询结果为 0 条，不创建导出任务")
        return None

    export_response = await post(EXPORT_URL, payload)
    export_body = ensure_api_success(export_response, label="导出")
    signed_url = extract_export_url(export_body)
    log("导出", "已取得原始文件地址，开始保存")
    return await download(signed_url, start_date, end_date, output_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="拼多多推广费 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument(
        "--ws-endpoint",
        "--cdp",
        dest="ws_endpoint",
        help="可选：显式传入本次 Profile 的 wsEndpoint；不传则按 --profile 自动获取",
    )
    endpoint.add_argument(
        "--debug-port",
        type=int,
        help="可选：显式传入当前 CDP 端口；不传则按 --profile 自动获取",
    )
    parser.add_argument(
        "--profile",
        default=PROFILE_NAME,
        help=f"Cloak Login Profile 完整名称，默认：{PROFILE_NAME}",
    )
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="可选：覆盖 Cloak Login MCP 地址；默认读取 CLOAK_MCP_URL 或本机 19610/mcp",
    )
    parser.add_argument(
        "--date-mode",
        "--mode",
        choices=("default", "yesterday"),
        default="yesterday",
        help="yesterday 将 API 日期替换为昨天；default 使用页面自然日期",
    )
    parser.add_argument("--start-date", "--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", "--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"原始 XLS/ZIP 保存目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="页面入口、自然查询和 API 请求的最长等待秒数，默认 60",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="保存原始文件时使用的 HTTP 代理，例如 http://127.0.0.1:7897",
    )
    args = parser.parse_args(argv)
    if (args.start_date is None) != (args.end_date is None):
        parser.error("--start-date 与 --end-date 必须同时提供")
    if args.start_date is not None and args.date_mode != "default":
        parser.error("指定 --start-date/--end-date 时不要同时使用 --date-mode")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.debug_port is not None and not 1 <= args.debug_port <= 65535:
        parser.error("--debug-port 必须在 1 到 65535 之间")
    if args.start_date is not None:
        try:
            start = parse_date(args.start_date, option_name="--start-date")
            end = parse_date(args.end_date, option_name="--end-date")
        except ValueError as exc:
            parser.error(str(exc))
        if start > end:
            parser.error("--start-date 不能晚于 --end-date")
    return args


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
    ).endpoint


def resolve_target_range(
    args: argparse.Namespace, natural_payload: dict[str, Any]
) -> tuple[str, str]:
    if args.start_date is not None and args.end_date is not None:
        return args.start_date, args.end_date
    if args.date_mode == "yesterday":
        yesterday = default_business_date()
        return yesterday, yesterday
    start = natural_date_to_iso(
        natural_payload.get("startDate"), field_name="自然开始日期"
    )
    end = natural_date_to_iso(
        natural_payload.get("endDate"), field_name="自然结束日期"
    )
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError(f"自然请求开始日期晚于结束日期：{start} > {end}")
    return start, end


def is_url_host(url: str, host: str) -> bool:
    return (urlparse(url).hostname or "").lower() == host


async def visible(locator: Any) -> bool:
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def first_visible(locator: Any) -> Any | None:
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible():
                return candidate
        except Exception:
            continue
    return None


async def click_compat(locator: Any, *, timeout: int = 10_000) -> None:
    try:
        await locator.click(timeout=timeout, no_wait_after=True)
        return
    except Exception as first_error:
        try:
            await locator.evaluate("element => element.click()")
            return
        except Exception:
            raise first_error


async def body_text(page: Any) -> str:
    try:
        return await page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


def human_marker(text: str) -> str | None:
    for marker in HUMAN_VERIFICATION_MARKERS:
        if marker in text:
            return marker
    return None


async def check_needs_human(page: Any) -> None:
    url = (page.url or "").lower()
    if "/login" in url:
        raise NeedsHumanError("当前拼多多 profile 未处于登录态")
    text = await body_text(page)
    for marker in SESSION_MARKERS:
        if marker in text:
            raise NeedsHumanError(f"页面提示“{marker}”，需要人工恢复登录态")
    verification = human_marker(text)
    if verification:
        raise NeedsHumanError(f"页面出现“{verification}”，需要人工完成安全验证")


async def query_button(page: Any) -> Any:
    button = page.get_by_role("button", name="查询", exact=True).last
    await button.wait_for(state="visible", timeout=30_000)
    return button


async def download_button(page: Any) -> Any:
    button = page.get_by_role("button", name="下载明细", exact=True).last
    await button.wait_for(state="visible", timeout=30_000)
    return button


async def report_controls_ready(page: Any, timeout: int = 60_000) -> None:
    await page.locator("#page-container").wait_for(state="visible", timeout=timeout)
    await page.locator(FUND_TYPE_INPUT).wait_for(state="attached", timeout=timeout)
    await page.locator(FLOW_TYPE_INPUT).wait_for(state="attached", timeout=timeout)
    await query_button(page)
    await download_button(page)


async def report_controls_probe(page: Any, timeout: int = 1_000) -> bool:
    try:
        await report_controls_ready(page, timeout=timeout)
        return True
    except Exception:
        return False


async def find_visible_option(page: Any, label: str) -> Any | None:
    candidates = (
        page.get_by_role("option", name=label, exact=True),
        page.locator('[role="listbox"] [role="option"]').filter(has_text=label),
        page.locator(
            ".anq-select-dropdown:not(.anq-select-dropdown-hidden) "
            ".anq-select-item-option"
        ).filter(has_text=label),
        page.locator(
            ".anq-select-dropdown:not(.anq-select-dropdown-hidden) li"
        ).filter(has_text=label),
    )
    for candidate_set in candidates:
        target = await first_visible(candidate_set)
        if target is not None:
            return target
    return None


async def choose_select_option(page: Any, input_selector: str, label: str) -> None:
    input_locator = page.locator(input_selector).first
    await input_locator.wait_for(state="attached", timeout=30_000)
    container = input_locator.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), "
        "' anq-select ')][1]"
    )
    selector = container.locator(".anq-select-selector").first
    last_error: Exception | None = None
    option = None
    for target in (input_locator, selector, container):
        try:
            await click_compat(target, timeout=5_000)
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                option = await find_visible_option(page, label)
                if option is not None:
                    break
                await asyncio.sleep(0.15)
            if option is not None:
                break
        except Exception as exc:
            last_error = exc
    if option is None:
        detail = f"；最后错误：{last_error}" if last_error else ""
        raise RuntimeError(f"选择框未找到选项“{label}”{detail}")
    await click_compat(option)
    selected = container.locator(".anq-select-selection-item").first
    selected_text = normalize_text(await selected.inner_text()) if await visible(selected) else ""
    if label not in selected_text:
        container_text = normalize_text(await container.inner_text())
        if label not in container_text:
            raise RuntimeError(f"选择框未确认选中“{label}”：{container_text}")


async def open_report_from_finance(context: Any, finance_page: Any, timeout: int) -> Any:
    if await report_controls_probe(finance_page, timeout=2_000):
        return finance_page
    await check_needs_human(finance_page)
    flow = finance_page.get_by_role("menuitem", name="财务流水", exact=True).last
    if not await visible(flow):
        flow = finance_page.locator("li.anq-menu-item").filter(has_text="财务流水").last
    if not await visible(flow):
        flow = finance_page.locator(FINANCE_FLOW_XPATH).first
    await flow.wait_for(state="visible", timeout=timeout * 1000)
    known_pages = set(context.pages)
    await click_compat(flow)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        candidates = [finance_page] + [
            page
            for page in context.pages
            if page not in known_pages and not page.is_closed()
        ]
        for candidate in candidates:
            if candidate.is_closed() or not is_url_host(candidate.url, PROMOTION_HOST):
                continue
            await check_needs_human(candidate)
            if await report_controls_probe(candidate, timeout=800):
                return candidate
        await asyncio.sleep(0.25)
    # 只有点击菜单超时才使用同一登录态的报告地址作兜底；入口仍然已经经过
    # 首页→推广账户→财务管理→财务流水的真实页面操作。
    await finance_page.goto(PROMOTION_REPORT_URL, wait_until="domcontentloaded", timeout=timeout * 1000)
    await report_controls_ready(finance_page, timeout=timeout * 1000)
    return finance_page


async def open_report_from_home(context: Any, home: Any, timeout: int) -> Any:
    if not is_url_host(home.url, MMS_HOST) or "/home" not in home.url:
        await home.goto(MMS_HOME_URL, wait_until="domcontentloaded", timeout=timeout * 1000)
    await check_needs_human(home)
    nav = home.locator(PROMOTION_NAV_SELECTOR).first
    if not await visible(nav):
        nav = home.locator(PROMOTION_NAV_XPATH).first
    if not await visible(nav):
        nav = home.get_by_role("link", name="推广账户", exact=True).first
    await nav.wait_for(state="visible", timeout=timeout * 1000)
    known_pages = set(context.pages)
    await click_compat(nav)
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        candidates = [home] + [
            page
            for page in context.pages
            if page not in known_pages and not page.is_closed()
        ]
        for candidate in candidates:
            if candidate.is_closed() or not is_url_host(candidate.url, PROMOTION_HOST):
                continue
            await check_needs_human(candidate)
            if await report_controls_probe(candidate, timeout=800):
                return candidate
            if "/mains/account/finance" in candidate.url:
                return await open_report_from_finance(context, candidate, timeout)
        await asyncio.sleep(0.25)
    raise RuntimeError("从商家后台点击“推广账户”后未进入拼多多推广平台")


async def choose_home_page(context: Any) -> Any:
    for page in context.pages:
        if not page.is_closed() and is_url_host(page.url, MMS_HOST) and "/home" in page.url:
            return page
    for page in context.pages:
        if not page.is_closed() and is_url_host(page.url, MMS_HOST):
            return page
    if context.pages:
        return context.pages[0]
    return await context.new_page()


def request_matches(request: Any, path: str, *, require_filtered: bool = False) -> bool:
    if request.method.upper() != "POST":
        return False
    parsed = urlparse(request.url)
    if parsed.hostname != PROMOTION_HOST or parsed.path != path:
        return False
    if not require_filtered:
        return True
    try:
        payload = parse_request_payload(request.post_data)
    except ApiError:
        return False
    return payload.get("flowType") == 2 and payload.get("fundType") == 1


def response_matches(response: Any, path: str) -> bool:
    try:
        return request_matches(response.request, path, require_filtered=True)
    except Exception:
        return False


async def response_to_api_response(response: Any) -> ApiResponse:
    try:
        text = await response.text()
    except Exception as exc:
        raise ApiError("无法读取自然查询响应") from exc
    return ApiResponse(status=int(response.status), body=parse_json_text(text))


async def capture_natural_query(page: Any, timeout: int) -> NaturalQueryContext:
    """点击一次查询并监听现金/支出对应的自然网络请求。"""

    query = await query_button(page)
    request_predicate = lambda request: request_matches(
        request, QUERY_PATH, require_filtered=True
    )
    response_predicate = lambda response: response_matches(response, QUERY_PATH)
    try:
        async with page.expect_request(
            request_predicate, timeout=timeout * 1000
        ) as request_info:
            async with page.expect_response(
                response_predicate, timeout=timeout * 1000
            ) as response_info:
                await click_compat(query)
        request = await request_info.value
        response = await response_info.value
    except Exception as exc:
        raise RuntimeError("点击查询后未捕获现金/支出 getDailyInvoice 请求") from exc

    payload = parse_request_payload(request.post_data)
    if payload.get("flowType") != 2 or payload.get("fundType") != 1:
        raise RuntimeError("自然查询请求未确认 flowType=2/fundType=1")
    dynamic_headers = dynamic_headers_from_request(request.headers)
    if not dynamic_headers:
        raise RuntimeError("自然查询请求未捕获动态请求头")
    api_response = await response_to_api_response(response)
    ensure_api_success(api_response, label="自然查询")
    if "startDate" not in payload or "endDate" not in payload:
        raise RuntimeError("自然查询请求未捕获开始和结束日期字段")
    start = payload["startDate"]
    end = payload["endDate"]
    log(
        "上下文",
        "已捕获自然 getDailyInvoice："
        f"日期字段={start}~{end}，动态请求头={','.join(sorted(dynamic_headers))}，"
        f"crawlerInfo={'有' if 'crawlerInfo' in payload else '无'}",
    )
    return NaturalQueryContext(
        payload=payload,
        dynamic_headers=dynamic_headers,
        response=api_response,
    )


async def browser_post_json(
    page: Any,
    url: str,
    payload: dict[str, Any],
    dynamic_headers: dict[str, str],
    timeout: int,
) -> ApiResponse:
    result = await page.evaluate(
        """
        async ({url, payload, dynamicHeaders, timeoutMs}) => {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), timeoutMs);
          try {
            const response = await fetch(url, {
              method: "POST",
              credentials: "include",
              headers: {
                "Accept": "*/*",
                "Content-Type": "application/json",
                ...dynamicHeaders
              },
              body: JSON.stringify(payload),
              signal: controller.signal
            });
            return {status: response.status, text: await response.text()};
          } finally {
            clearTimeout(timer);
          }
        }
        """,
        {
            "url": url,
            "payload": payload,
            "dynamicHeaders": dynamic_headers,
            "timeoutMs": timeout * 1000,
        },
    )
    if not isinstance(result, dict):
        raise ApiError("浏览器 WebAPI 返回结构异常")
    return ApiResponse(
        status=int(result.get("status", 0)),
        body=parse_json_text(result.get("text")),
    )


async def download_from_browser_context(
    page: Any,
    context: Any,
    signed_url: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    proxy: str | None,
) -> Path:
    cookies = await context.cookies()
    user_agent = await page.evaluate("() => navigator.userAgent")
    return await asyncio.to_thread(
        download_file_requests,
        signed_url,
        cookies=cookies,
        user_agent=str(user_agent or ""),
        output_dir=output_dir,
        start_date=start_date,
        end_date=end_date,
        proxy=proxy,
    )


async def run_async(args: argparse.Namespace) -> Path | None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("当前 .venv 未安装 playwright") from exc

    output_dir = Path(args.output_dir).expanduser().resolve()
    connection = resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
    )
    endpoint = connection.endpoint
    log("计划", f"Profile={args.profile}，输出目录={output_dir}")
    log("Profile", f"CDP 来源={'本次自动获取' if connection.profile_id else '显式参数'}")

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.connect_over_cdp(endpoint)
        except Exception as exc:
            raise RuntimeError(
                "无法连接当前拼多多 profile 的 CDP，请确认 profile/CDP 已启动"
            ) from exc
        try:
            if not browser.contexts:
                raise RuntimeError("CDP 浏览器没有可用 BrowserContext")
            context = browser.contexts[0]
            home = await choose_home_page(context)
            report_page = await open_report_from_home(context, home, args.timeout)
            await report_controls_ready(report_page, timeout=args.timeout * 1000)

            # 只操作两个业务筛选框；这里刻意不查找、不点击任何日期输入框。
            await choose_select_option(report_page, FUND_TYPE_INPUT, "现金")
            log("页面", "固定业务筛选：资金类型=现金")
            await choose_select_option(report_page, FLOW_TYPE_INPUT, "支出")
            log("页面", "固定业务筛选：流水类型=支出")

            natural = await capture_natural_query(report_page, args.timeout)
            start_date, end_date = resolve_target_range(args, natural.payload)
            if args.start_date is None and args.date_mode == "default":
                log("计划", f"使用自然请求日期={start_date}~{end_date}")
            elif args.start_date is None and args.date_mode == "yesterday":
                log("计划", f"默认昨天（仅替换 WebAPI 日期字段）={start_date}~{end_date}")
            else:
                log("计划", f"仅替换 WebAPI 日期字段={start_date}~{end_date}")

            async def post_with_context(
                url: str, payload: dict[str, Any]
            ) -> ApiResponse:
                nonlocal natural
                request_payload = replace_date_fields(
                    natural.payload, start_date, end_date
                )
                response = await browser_post_json(
                    report_page,
                    url,
                    request_payload,
                    natural.dynamic_headers,
                    args.timeout,
                )
                if response.status not in {401, 403}:
                    return response

                # 动态 Anti-Content 失效时，只重新点击一次查询来获得新的自然
                # 上下文，再重试当前接口；不读取或打印敏感响应体。
                log("上下文", f"{urlparse(url).path} 返回 {response.status}，重新监听自然查询上下文")
                natural = await capture_natural_query(report_page, args.timeout)
                retry_payload = replace_date_fields(
                    natural.payload, start_date, end_date
                )
                retry_response = await browser_post_json(
                    report_page,
                    url,
                    retry_payload,
                    natural.dynamic_headers,
                    args.timeout,
                )
                if retry_response.status in {401, 403}:
                    raise NeedsHumanError(
                        f"{urlparse(url).path} 刷新动态上下文后仍返回 "
                        f"HTTP {retry_response.status}，请检查登录态或安全验证"
                    )
                return retry_response

            async def download_callback(
                signed_url: str,
                requested_start: str,
                requested_end: str,
                requested_output_dir: Path,
            ) -> Path:
                return await download_from_browser_context(
                    report_page,
                    context,
                    signed_url,
                    requested_start,
                    requested_end,
                    requested_output_dir,
                    proxy=args.proxy,
                )

            return await execute_api_chain(
                post_with_context,
                download_callback,
                natural.payload,
                start_date=start_date,
                end_date=end_date,
                output_dir=output_dir,
            )
        finally:
            # 借用的是 Cloak 的远端浏览器；退出 Playwright 生命周期只释放
            # 本地连接，不能调用 browser.close() 关闭用户 profile。
            pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = asyncio.run(run_async(args))
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr)
        return 2
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[PDD][推广费][失败] 用户中断脚本", file=sys.stderr)
        return 130
    except (ApiError, RuntimeError, ValueError, OSError, requests.RequestException) as exc:
        print(f"[PDD][推广费][失败] {exc}", file=sys.stderr)
        return 1
    if result is None:
        log("完成", "无数据，未创建导出任务、未生成文件")
    else:
        log("完成", f"原始文件={result}（{result.stat().st_size} bytes）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
