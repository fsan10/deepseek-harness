#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过京东商家后台 WebAPI 下载日结算账单原始 ZIP。"""

from __future__ import annotations

import argparse
import asyncio
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
    from ReverseAPI.Formal_Script.jd_webapi_common import (
        ApiError,
        BrowserApiSession,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        check_human_gate,
        clone_payload,
        date_to_ms,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        refresh_jd_page,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from jd_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        check_human_gate,
        clone_payload,
        date_to_ms,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        refresh_jd_page,
    )


PROFILE_NAME = "JD-京东-MOCK饮品旗舰店"
SETTLEMENT_URL = "https://shop.jd.com/jdm/fin/billManage/DailyBill"
SETTLEMENT_PAGE_ROUTE = "/jdm/fin/billManage/DailyBill"
SFF_URL_PREFIX = "https://sff.jd.com/api?v=1.0&appId=QDWB4GJVETRIFPT7RHSL&api="
QUERY_PATH = "/api"
QUERY_API = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.queryDailyBillByPage"
DETAIL_API = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.downloadDailyBillDetail"
QUERY_URL = f"{SFF_URL_PREFIX}{QUERY_API}"
DETAIL_URL = f"{SFF_URL_PREFIX}{DETAIL_API}"


def build_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page_num: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    payload = clone_payload(template)
    query = payload.setdefault("daybillMo", {})
    query.update(
        {
            "setDateBegin": f"{start.isoformat()} 00:00:00",
            "setDateEnd": f"{end.isoformat()} 23:59:59",
            "pageNum": page_num,
            "pageSize": page_size,
        }
    )
    return payload


def build_detail_payload(
    query_payload: dict[str, Any],
    row_id: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    query = query_payload.get("daybillMo")
    if not isinstance(query, dict):
        raise ValueError("结算账单查询模板缺少 daybillMo")
    detail = clone_payload(query_payload)
    detail_query = detail.setdefault("daybillMo", {})
    detail_query.update(
        {
            "setDateBegin": date_to_ms(start, end_of_day=False),
            "setDateEnd": date_to_ms(end, end_of_day=True),
            "pageNum": 1,
            "pageSize": 10,
            "ids": [int(row_id)],
        }
    )
    return detail


def row_business_date(row: dict[str, Any]) -> str:
    for key in ("accDate", "accountDate", "businessDate", "setDate"):
        value = str(row.get(key) or "")
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
        if len(value) == 10 and value[4] == "-":
            return value
    return ""


def select_settlement_row(
    rows: list[dict[str, Any]], requested: date | None
) -> dict[str, Any] | None:
    expected = requested.isoformat() if requested is not None else None
    candidates = [
        row
        for row in rows
        if row_business_date(row)
        and (expected is None or row_business_date(row) == expected)
        and row.get("id") not in (None, "")
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (row_business_date(row), str(row.get("accDate") or "")),
    )


def response_settlement_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("结算账单查询缺少 data 对象", body=body)
    rows = data.get("content")
    if not isinstance(rows, list):
        raise ApiError("结算账单查询缺少 data.content", body=body)
    return [row for row in rows if isinstance(row, dict)], data


def _query_window(requested: date | None) -> tuple[date, date]:
    today = datetime.now(CN_TZ).date()
    if requested is None:
        return today - timedelta(days=90), today + timedelta(days=1)
    # 结算行的 accDate 比 setDate 通常晚一天；给接口留出两天前后窗口，
    # 最终仍按业务日期精确匹配，避免误取相邻账单。
    return requested - timedelta(days=2), requested + timedelta(days=1)


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
        timeout=getattr(args, "profile_timeout", 30.0),
        poll_interval=getattr(args, "profile_poll_interval", 0.5),
    ).endpoint


async def run_with_endpoint(args: argparse.Namespace, endpoint: str) -> Path | None:
    from playwright.async_api import async_playwright

    requested_range = parse_date_range(getattr(args, "date", None), option="--date")
    if requested_range is not None and requested_range[0] != requested_range[1]:
        raise ValueError("京东结算只支持单日 --date，不支持跨日范围")
    requested = requested_range[0] if requested_range is not None else None
    window_start, window_end = _query_window(requested)
    output_dir = Path(args.output_dir)
    timeout = float(getattr(args, "timeout", 240.0))
    collector = NaturalRequestCollector()
    page: Any | None = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器中没有可用上下文")
        context = browser.contexts[0]
        collector.attach(context)
        try:
            log(
                "结算",
                "计划",
                f"查询窗口={window_start.isoformat()} 到 {window_end.isoformat()}"
                + (f"，精确业务日={requested.isoformat()}" if requested else "，自动取最新业务日"),
            )
            page = await open_jd_report_page(context, SETTLEMENT_URL)
            await check_human_gate(page)

            async def refresh() -> None:
                await refresh_jd_page(page, SETTLEMENT_URL)

            api = BrowserApiSession(
                page,
                collector,
                page_route=SETTLEMENT_PAGE_ROUTE,
                refresh=refresh,
            )
            template = await collector.wait_for_payload(
                "sff.jd.com",
                QUERY_PATH,
                SETTLEMENT_PAGE_ROUTE,
                page,
                api_name=QUERY_API,
                timeout=min(timeout, 30.0),
            )
            query_body = await api.post_json(
                QUERY_URL,
                build_query_payload(template, window_start, window_end),
                label="结算账单查询",
                timeout=timeout,
            )
            rows, data = response_settlement_rows(query_body)
            total = as_int(data.get("totalElements"), len(rows))
            row = select_settlement_row(rows, requested)
            log("结算", "查询", f"服务端总行数={total}，窗口匹配行数={len(rows)}")
            if row is None:
                log("结算", "完成", "没有匹配的结算账单，未创建下载任务")
                return None

            row_id = as_int(row.get("id"), 0)
            business_date = row_business_date(row)
            if not row_id or not business_date:
                raise ApiError("结算账单行缺少 id 或业务日期", body=row)
            detail_body = await api.post_json(
                DETAIL_URL,
                build_detail_payload(template, row_id, window_start, window_end),
                label="结算明细下载地址",
                timeout=timeout,
            )
            signed_url = extract_download_url(detail_body, label="结算明细下载地址")
            output = await asyncio.to_thread(
                download_original_file,
                signed_url,
                output_dir,
                f"JD_settlement_{business_date}_to_{business_date}.zip",
                referer=str(page.url),
            )
            log("结算", "完成", f"业务日期={business_date}，下载完成：{output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            if page is not None:
                with suppress(Exception):
                    await page.close()


async def run_async(args: argparse.Namespace) -> Path | None:
    return await run_with_endpoint(args, resolve_endpoint(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="京东结算账单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", default=PROFILE_NAME, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--date", help="精确业务日期 YYYY-MM-DD；不填则自动取查询窗口内最新账单")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=240.0, help="请求最长等待秒数，默认 240")
    parser.add_argument("--profile-timeout", type=float, default=30.0, help="Profile/CDP 自动获取超时秒数")
    parser.add_argument("--profile-poll-interval", type=float, default=0.5, help="Profile/CDP 轮询秒数")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    try:
        output = asyncio.run(run_async(args))
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[JD][结算][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[JD][结算][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("结算", "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
