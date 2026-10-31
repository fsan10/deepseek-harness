#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过小红书结算账单 WebAPI 下载日账单或月度汇总单。

页面只用于真实入口、登录态和动态请求头；账单查询使用
``query_period_settle_bill_list``，下载地址使用 ``get_bill_download_url``。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from contextlib import suppress
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileResolutionError,
        resolve_profile_connection,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )


try:
    from ReverseAPI.Formal_Script.xhs_webapi_common import (
        ApiError,
        BrowserApiSession,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        PROJECT_ROOT,
        bounded_total_pages,
        check_human_gate,
        download_file,
        extract_download_url,
        parse_iso_date,
        parse_period_key,
        period_rows,
        reload_target_page,
        safe_filename,
        log,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from xhs_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        PROJECT_ROOT,
        bounded_total_pages,
        check_human_gate,
        download_file,
        extract_download_url,
        parse_iso_date,
        parse_period_key,
        period_rows,
        reload_target_page,
        safe_filename,
        log,
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auto_download.playwright.xiaohongshu_download_common import (  # noqa: E402,E501
    open_report_page,
)


PROFILE_NAME = "XHS-小红书-MOCK旗舰店"
SETTLEMENT_URL = "https://ark.xiaohongshu.com/app-finance/bill/settle/daily"
SETTLEMENT_PAGE_ROUTE = "/app-finance/bill/settle/daily"
PERIOD_SETTLEMENT_PATH = "/api/edith/settlebill/query_period_settle_bill_list"
GET_DOWNLOAD_URL_PATH = "/api/edith/settlebill/get_bill_download_url"
PERIOD_BILL_TYPE = "PERIOD_SETTLE_BILL"


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def parse_month(value: str) -> date:
    match = re.fullmatch(r"(20\d{2})[-/]?(\d{1,2})", value.strip())
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"--date 在 month 模式必须使用 YYYY-MM 或 YYYYMM：{value!r}")
    return date(int(match.group(1)), int(match.group(2)), 1)


def parse_requested_period(value: str | None, mode: str) -> date | None:
    if value is None:
        return None
    if mode == "day":
        return parse_iso_date(value, option="--date")
    return parse_month(value)


def query_range(mode: str, requested: date | None, today: date | None = None) -> tuple[str, str]:
    current = today or datetime.now(CN_TZ).date()
    if requested is not None:
        if mode == "day":
            end = requested + timedelta(days=1)
        else:
            next_year, next_month = add_months(requested.year, requested.month, 1)
            end = date(next_year, next_month, 1)
        return f"{requested.isoformat()} 00:00:00", f"{end.isoformat()} 00:00:00"

    if mode == "day":
        start = current - timedelta(days=90)
        end = current
    else:
        start_year, start_month = add_months(current.year, current.month, -12)
        start = date(start_year, start_month, 1)
        end = date(current.year, current.month, 1)
    return f"{start.isoformat()} 00:00:00", f"{end.isoformat()} 00:00:00"


def build_period_payload(
    mode: str,
    start_time: str,
    end_time: str,
    *,
    page_num: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return {
        "periodType": mode.upper(),
        "timeType": "SETTLE_TIME",
        "startTime": start_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
    }


def row_period_key(row: dict[str, Any], mode: str) -> str:
    start_key = parse_period_key(row.get("startTime"))
    bill_key = parse_period_key(row.get("billDate"))
    if mode == "month":
        return (start_key or bill_key)[:7]
    return start_key or bill_key


def select_period_row(
    rows: list[dict[str, Any]], mode: str, requested: date | None
) -> dict[str, Any] | None:
    expected = (
        requested.isoformat()
        if requested is not None and mode == "day"
        else requested.strftime("%Y-%m") if requested is not None else None
    )
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("periodType") or "").upper() != mode.upper():
            continue
        status = str(row.get("processStatus") or "").upper()
        if status and status not in {"SUCCESS", "SUCCEED", "FINISH", "FINISHED"}:
            continue
        if expected is not None and row_period_key(row, mode) != expected:
            continue
        if row.get("periodSettleNo"):
            candidates.append(row)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            row_period_key(row, mode),
            str(row.get("processFinishTime") or row.get("updateTime") or ""),
        ),
    )


async def query_all_period_rows(
    api: BrowserApiSession,
    mode: str,
    start_time: str,
    end_time: str,
) -> list[dict[str, Any]]:
    first = await api.post_json(
        PERIOD_SETTLEMENT_PATH,
        build_period_payload(mode, start_time, end_time),
        label="结算账单查询",
    )
    data = first.get("data") or {}
    rows = period_rows(first, label="结算账单查询")
    total_pages = bounded_total_pages(data, label="结算账单查询")
    for page_num in range(2, total_pages + 1):
        body = await api.post_json(
            PERIOD_SETTLEMENT_PATH,
            build_period_payload(mode, start_time, end_time, page_num=page_num),
            label="结算账单查询",
        )
        rows.extend(period_rows(body, label="结算账单查询"))
    return rows


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
    ).endpoint


async def run_async(args: argparse.Namespace) -> Path | None:
    from playwright.async_api import async_playwright

    endpoint = resolve_endpoint(args)
    requested = parse_requested_period(args.date, args.mode)
    start_time, end_time = query_range(args.mode, requested)
    collector = NaturalRequestCollector()
    owned_pages: list[Any] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器中没有可用上下文")
        context = browser.contexts[0]
        existing_pages = set(context.pages)
        collector.attach(context)
        page = None
        try:
            log("结算", "计划", f"Profile={args.profile}，mode={args.mode}")
            page = await open_report_page(context, SETTLEMENT_URL)
            if page not in existing_pages:
                owned_pages.append(page)
            await check_human_gate(page)

            async def refresh() -> None:
                await reload_target_page(page)

            api = BrowserApiSession(
                page,
                collector,
                page_route=SETTLEMENT_PAGE_ROUTE,
                refresh=refresh,
            )
            rows = await query_all_period_rows(api, args.mode, start_time, end_time)
            row = select_period_row(rows, args.mode, requested)
            if row is None:
                if requested is None:
                    log("结算", "完成", "查询无可下载账单")
                else:
                    log("结算", "完成", f"未找到指定账单：{args.date}")
                return None

            period_no = str(row.get("periodSettleNo") or "")
            url_body = await api.post_json(
                GET_DOWNLOAD_URL_PATH,
                {"periodSettleNo": period_no, "billType": PERIOD_BILL_TYPE},
                label="结算账单下载地址",
            )
            signed_url = extract_download_url(url_body, label="结算账单下载地址")
            business_key = row_period_key(row, args.mode).replace("-", "")
            output = download_file(
                signed_url,
                Path(args.output_dir),
                safe_filename(f"XHS_settlement_{args.mode}_{business_key}.xlsx"),
                referer=page.url,
            )
            log("结算", "查询", f"账单日期={row_period_key(row, args.mode)}")
            log("结算", "完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            for owned in owned_pages:
                with suppress(Exception):
                    await owned.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小红书结算账单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", default=PROFILE_NAME, help="Cloak Login Profile 名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--mode", choices=("day", "month"), default="day", help="日账单或月度汇总单，默认 day")
    parser.add_argument("--date", help="精确账单日期：day 使用 YYYY-MM-DD，month 使用 YYYY-MM 或 YYYYMM")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = asyncio.run(run_async(args))
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[XHS][结算][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[XHS][结算][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("结算", "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
