#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过京东商家后台 WebAPI 下载资金流水账单。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script.jd_webapi_common import (
        ApiError,
        BrowserApiSession,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        bounded_total_pages,
        check_human_gate,
        clone_payload,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        refresh_jd_page,
        sff_utc_bounds,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from jd_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        bounded_total_pages,
        check_human_gate,
        clone_payload,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        refresh_jd_page,
        sff_utc_bounds,
    )


PROFILE_NAME = "JD-京东-MOCK饮品旗舰店"
FUND_URL = "https://shop.jd.com/jdm/finance/billManage/foundFlow?formCeconciiFlag=true"
FUND_PAGE_ROUTE = "/jdm/finance/billManage/foundFlow"
SFF_URL_PREFIX = "https://sff.jd.com/api?v=1.0&appId=QDWB4GJVETRIFPT7RHSL&api="
QUERY_PATH = "/api"
QUERY_API = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.queryCapitalFlowPage"
CREATE_API = "dsm.pop.finance.vendor.spi.export.ExportTaskDsmProvider.createTask"
TASK_LIST_API = "dsm.pop.finance.vendor.spi.export.ExportTaskDsmProvider.queryForPage"
QUERY_URL = f"{SFF_URL_PREFIX}{QUERY_API}"
CREATE_URL = f"{SFF_URL_PREFIX}{CREATE_API}"
TASK_LIST_URL = f"{SFF_URL_PREFIX}{TASK_LIST_API}"
TASK_TYPE = 13


def _date_period(value: str | None) -> tuple[date, date]:
    requested = parse_date_range(value, option="--date")
    if requested is not None:
        return requested
    yesterday = default_yesterday()
    return yesterday, yesterday


def build_query_payload(template: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    """保留页面自然请求中的店铺上下文，只替换日期和分页。"""

    payload = clone_payload(template)
    query = payload.setdefault("capitalFlowQueryMo", {})
    query.update(
        {
            "pageNo": 1,
            "pageSize": 10,
            "startDate": f"{start.isoformat()} 00:00:00",
            "endDate": f"{end.isoformat()} 23:59:59",
            "beginEndDate": sff_utc_bounds(start, end),
        }
    )
    payload.setdefault("accessContext", {"source": "web"})
    return payload


def build_create_payload(query_payload: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    query = query_payload.get("capitalFlowQueryMo")
    if not isinstance(query, dict):
        raise ValueError("资金流水查询模板缺少 capitalFlowQueryMo")
    condition = {
        "exportType": str(TASK_TYPE),
        "orgCode": query.get("orgCode"),
        "outTradeNo": None,
        "startDate": None,
        "tradeNo": None,
        "endDate": None,
        "beginEndDate": sff_utc_bounds(start, end, with_milliseconds=True),
        "startTime": f"{start.isoformat()} 00:00:00",
        "endTime": f"{end.isoformat()} 23:59:59",
    }
    return {
        "request": {
            "data": {
                "conditionBody": json.dumps(
                    condition,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "taskType": TASK_TYPE,
                "terminal": 1,
            }
        },
        "accessContext": {"source": "web"},
    }


def build_task_list_payload(page_num: int = 1) -> dict[str, Any]:
    return {
        "request": {
            "data": {
                "pageNum": page_num,
                "pageSize": 10,
                "taskType": TASK_TYPE,
            }
        },
        "accessContext": {"source": "web"},
    }


def response_task_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("资金导出任务列表缺少 data 对象", body=body)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ApiError("资金导出任务列表缺少 data.data", body=body)
    return [row for row in rows if isinstance(row, dict)], data


def select_task(
    rows: list[dict[str, Any]],
    *,
    task_id: str,
    condition_body: str,
) -> dict[str, Any] | None:
    exact = [row for row in rows if str(row.get("id") or "") == task_id]
    if exact:
        return exact[0]
    candidates = [
        row
        for row in rows
        if int(row.get("taskType") or 0) == TASK_TYPE
        and str(row.get("conditionBody") or "") == condition_body
    ]
    return candidates[0] if candidates else None


async def wait_for_task(
    api: BrowserApiSession,
    *,
    task_id: str,
    condition_body: str,
    timeout: float,
    poll_interval: float,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    last_status = ""
    while asyncio.get_running_loop().time() < deadline:
        first = await api.post_json(
            TASK_LIST_URL,
            build_task_list_payload(),
            label="资金导出任务查询",
        )
        rows, data = response_task_rows(first)
        total_pages = bounded_total_pages(data, label="资金导出任务查询")
        for page_num in range(2, total_pages + 1):
            body = await api.post_json(
                TASK_LIST_URL,
                build_task_list_payload(page_num),
                label="资金导出任务查询",
            )
            page_rows, _ = response_task_rows(body)
            rows.extend(page_rows)

        task = select_task(rows, task_id=task_id, condition_body=condition_body)
        if task is not None:
            signed_url = task.get("downloadUrl")
            status = as_int(task.get("taskStatus"), -1)
            if isinstance(signed_url, str) and signed_url.startswith(("http://", "https://")):
                return signed_url
            if status in {3, 4, 5, -1}:
                raise RuntimeError(f"资金导出任务失败，状态={status}")
            next_status = str(status)
            if next_status != last_status:
                log("资金", "任务", f"导出任务处理中，状态={next_status}")
                last_status = next_status
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"等待资金导出任务超时，最后状态={last_status or '未找到任务'}")


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

    start, end = _date_period(getattr(args, "date", None))
    output_dir = Path(args.output_dir)
    timeout = float(getattr(args, "timeout", 240.0))
    poll_interval = float(getattr(args, "poll_interval", 2.0))
    collector = NaturalRequestCollector()
    page: Any | None = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器中没有可用上下文")
        context = browser.contexts[0]
        collector.attach(context)
        try:
            log("资金", "计划", f"日期={start.isoformat()} 到 {end.isoformat()}")
            page = await open_jd_report_page(context, FUND_URL)
            await check_human_gate(page)

            async def refresh() -> None:
                await refresh_jd_page(page, FUND_URL)

            api = BrowserApiSession(
                page,
                collector,
                page_route=FUND_PAGE_ROUTE,
                refresh=refresh,
            )
            template = await collector.wait_for_payload(
                "sff.jd.com",
                QUERY_PATH,
                FUND_PAGE_ROUTE,
                page,
                api_name=QUERY_API,
                timeout=min(timeout, 30.0),
            )
            query_payload = build_query_payload(template, start, end)
            query_body = await api.post_json(
                QUERY_URL,
                query_payload,
                label="资金流水查询",
                timeout=timeout,
            )
            data = query_body.get("data")
            if not isinstance(data, dict):
                raise ApiError("资金流水查询缺少 data 对象", body=query_body)
            total = as_int(data.get("totalCount"), 0)
            log("资金", "查询", f"匹配行数={total}")
            if total <= 0:
                log("资金", "完成", "指定日期无可下载数据，未创建导出任务")
                return None

            create_payload = build_create_payload(query_payload, start, end)
            condition_body = str(create_payload["request"]["data"]["conditionBody"])
            submitted = int(time.time() * 1000)
            create_body = await api.post_json(
                CREATE_URL,
                create_payload,
                label="资金导出任务创建",
                timeout=timeout,
            )
            create_data = create_body.get("data")
            if not isinstance(create_data, dict):
                raise ApiError("资金导出任务创建缺少任务对象", body=create_body)
            task_id = str(create_data.get("id") or "")
            if not task_id:
                raise ApiError("资金导出任务创建未返回任务 ID", body=create_body)
            signed_url = await wait_for_task(
                api,
                task_id=task_id,
                condition_body=condition_body,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            del submitted  # 仅用于说明任务创建发生在查询之后，不落盘动态值。
            output = await asyncio.to_thread(
                download_original_file,
                signed_url,
                output_dir,
                f"JD_fund_{start.isoformat()}_to_{end.isoformat()}.csv",
                referer=str(page.url),
            )
            log("资金", "完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            if page is not None:
                with suppress(Exception):
                    await page.close()


async def run_async(args: argparse.Namespace) -> Path | None:
    return await run_with_endpoint(args, resolve_endpoint(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="京东资金流水 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", default=PROFILE_NAME, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--date", help="指定日期或范围：YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD；默认昨天")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=240.0, help="导出任务最长等待秒数，默认 240")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="任务轮询秒数，默认 2")
    parser.add_argument("--profile-timeout", type=float, default=30.0, help="Profile/CDP 自动获取超时秒数")
    parser.add_argument("--profile-poll-interval", type=float, default=0.5, help="Profile/CDP 轮询秒数")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout 和 --poll-interval 必须大于 0")
    try:
        output = asyncio.run(run_async(args))
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[JD][资金][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[JD][资金][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("资金", "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
