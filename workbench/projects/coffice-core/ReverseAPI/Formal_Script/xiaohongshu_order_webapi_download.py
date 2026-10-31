#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过小红书订单 WebAPI 查询并下载订单 XLSX。

浏览器只负责从小红书真实商家入口建立登录态和动态请求头；订单查询、
导出任务创建、状态轮询与短效文件下载均走已抓包确认的业务接口。

示例（从项目根目录执行）：

    .venv\\Scripts\\python.exe -m ReverseAPI.Formal_Script.xiaohongshu_order_webapi_download \\
        --ws-endpoint "<当前 Profile 的 wsEndpoint>" \\
        --profile "XHS-小红书-MOCK旗舰店"

指定日期范围时，同时传入 ``--start-date`` 和 ``--end-date``；不传时使用
最近 30 个自然日。脚本不会关闭用户原有的 Profile 或页面。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import suppress
from datetime import date
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
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        PROJECT_ROOT,
        XHS_HOME_URL,
        as_int,
        check_human_gate,
        date_to_ms,
        download_file,
        extract_download_url,
        parse_iso_date,
        recent_order_range,
        reload_target_page,
        response_data,
        safe_filename,
        log,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from xhs_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        PROJECT_ROOT,
        XHS_HOME_URL,
        as_int,
        check_human_gate,
        date_to_ms,
        download_file,
        extract_download_url,
        parse_iso_date,
        recent_order_range,
        reload_target_page,
        response_data,
        safe_filename,
        log,
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auto_download.playwright.xiaohongshu_order_download import (  # noqa: E402
    open_home_page,
    open_order_management,
)


PROFILE_NAME = "XHS-小红书-MOCK旗舰店"
ORDER_PAGE_ROUTE = "/app-order/order/query"
ORDER_PAGE_PATH = "/api/edith/fulfillment/order/page"
START_EXPORT_PATH = "/api/edith/fulfillment/tool/file/start_export"
WATCH_EXPORT_PATH = "/api/edith/fulfillment/tool/file/watch_export"
SOURCE_DATA_BEAN = "OrderQueryPackageFileBuilder"


def build_order_page_payload(start: date, end: date, *, page_size: int = 20) -> dict[str, Any]:
    """生成当前订单页使用的查询 Payload，只替换日期范围。"""

    return {
        "page_no": 1,
        "page_size": page_size,
        "multi_search_field": "",
        "order_tag_list": [],
        "order_type_list": [],
        "promise_ship_time_type_list": [],
        "after_sale_status_list": [],
        "status": [],
        "time_range_list": [
            {
                "time_type": 3,
                "start_time": date_to_ms(start, end_of_day=False),
                "end_time": date_to_ms(end, end_of_day=True),
            }
        ],
        "seller_mark_priority_list": [],
        "seller_mark_note_status_list": [],
        "overdue_status": -2,
        "sort_by": {"sort_field": "ordered_at", "desc": True},
        "need_declare_info": True,
        "need_declare_times": True,
        "allow_es_fallback": True,
    }


def build_export_condition(start: date, end: date) -> dict[str, Any]:
    """生成 start_export 的 data_condition 对象。"""

    return {
        "multi_search_field": "",
        "order_tag_list": [],
        "order_type_list": [],
        "promise_ship_time_type_list": [],
        "after_sale_status_list": [],
        "time_range_list": [
            {
                "timeType": "ordered",
                "startTime": date_to_ms(start, end_of_day=False),
                "endTime": date_to_ms(end, end_of_day=True),
            }
        ],
        "seller_mark_priority_list": [],
        "seller_mark_note_status_list": [],
        "overdue_status": -2,
        "status_list": [],
        "sort_by": {"sortField": "ordered_at", "desc": True},
        "package_ids": [],
        "need_declare_info": True,
        "need_declare_times": True,
    }


def build_start_export_payload(start: date, end: date) -> dict[str, str]:
    condition = json.dumps(
        build_export_condition(start, end),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "data_condition": condition,
        "source_data_bean": SOURCE_DATA_BEAN,
    }


def task_download_url(task: dict[str, Any]) -> str | None:
    for key in ("file_url", "fileUrl", "downloadUrl", "download_url"):
        value = task.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


async def poll_export(
    api: BrowserApiSession,
    task_id: str,
    *,
    timeout: float,
    interval: float,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    last_state: tuple[Any, ...] | None = None
    while asyncio.get_running_loop().time() < deadline:
        body = await api.post_json(
            WATCH_EXPORT_PATH,
            {"task_id": task_id},
            label="订单导出状态",
            timeout=min(60.0, max(10.0, interval * 5)),
        )
        task = response_data(body, label="订单导出状态").get("task")
        if not isinstance(task, dict):
            raise ApiError("订单导出状态返回缺少 task", path=WATCH_EXPORT_PATH, body=body)

        state = str(task.get("state") or task.get("status") or "").lower()
        progress = as_int(task.get("progress"), -1)
        message = str(task.get("message") or "")
        current = (state, progress, message)
        if current != last_state:
            log(
                "订单",
                "轮询",
                f"状态={state or '-'}，进度={progress if progress >= 0 else '-'}%",
            )
            last_state = current

        if any(word in state for word in ("fail", "error", "cancel")):
            raise RuntimeError(f"小红书订单导出任务失败：{message or state}")
        url = task_download_url(task)
        if url and (state in {"finish", "finished", "success", "complete", "completed"} or progress >= 100):
            return url
        if url and state not in {"preparing", "process", "processing", "running"}:
            return url
        await asyncio.sleep(interval)
    raise TimeoutError(f"等待小红书订单导出任务完成超时（{timeout:g} 秒）")


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
    ).endpoint


def resolve_dates(args: argparse.Namespace) -> tuple[date, date]:
    if (args.start_date is None) != (args.end_date is None):
        raise ValueError("--start-date 和 --end-date 必须同时提供")
    if args.start_date and args.end_date:
        start = parse_iso_date(args.start_date, option="--start-date")
        end = parse_iso_date(args.end_date, option="--end-date")
        if start > end:
            raise ValueError("--start-date 不能晚于 --end-date")
        return start, end
    return recent_order_range()


async def run_async(args: argparse.Namespace) -> Path | None:
    from playwright.async_api import async_playwright

    endpoint = resolve_endpoint(args)
    start, end = resolve_dates(args)
    output_dir = Path(args.output_dir)
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
            log("订单", "计划", f"Profile={args.profile}")
            log("订单", "页面", "从小红书商家后台首页进入订单管理")
            page = await open_home_page(context, args.profile)
            page = await open_order_management(page)
            if page not in existing_pages:
                owned_pages.append(page)
            await check_human_gate(page)

            async def refresh() -> None:
                await reload_target_page(page)

            api = BrowserApiSession(
                page,
                collector,
                page_route=ORDER_PAGE_ROUTE,
                refresh=refresh,
            )
            await collector.wait_for_context(ORDER_PAGE_PATH, ORDER_PAGE_ROUTE, page)
            query_body = await api.post_json(
                ORDER_PAGE_PATH,
                build_order_page_payload(start, end),
                label="订单查询",
            )
            query_data = response_data(query_body, label="订单查询")
            total = as_int(query_data.get("total"), -1)
            if total < 0:
                packages = query_data.get("packages")
                if not isinstance(packages, list):
                    raise ApiError(
                        "订单查询结果缺少 total 或 packages 明细数组",
                        path=ORDER_PAGE_PATH,
                        body=query_body,
                    )
                total = len(packages)
            log("订单", "查询", f"查询完成：{total} 条")
            if total == 0:
                log("订单", "完成", "查询无数据，跳过导出任务创建")
                return None

            start_body = await api.post_json(
                START_EXPORT_PATH,
                build_start_export_payload(start, end),
                label="订单创建导出任务",
            )
            start_data = response_data(start_body, label="订单创建导出任务")
            task_id = str(start_data.get("task_id") or start_data.get("taskId") or "")
            if not task_id:
                raise ApiError(
                    "订单创建导出任务未返回 task_id",
                    path=START_EXPORT_PATH,
                    body=start_body,
                )
            log("订单", "导出", f"已创建本次导出任务，task_id={task_id}")
            signed_url = await poll_export(
                api,
                task_id,
                timeout=args.timeout,
                interval=args.poll_interval,
            )
            output = download_file(
                signed_url,
                output_dir,
                f"XHS_order_{start.isoformat()}_to_{end.isoformat()}.xlsx",
                referer=f"{XHS_HOME_URL}/",
            )
            log("订单", "完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            for owned in owned_pages:
                with suppress(Exception):
                    await owned.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小红书订单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", default=PROFILE_NAME, help="Cloak Login Profile 名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--start-date", help="查询开始日期 YYYY-MM-DD；需与 --end-date 同时提供")
    parser.add_argument("--end-date", help="查询结束日期 YYYY-MM-DD；需与 --start-date 同时提供")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=240.0, help="导出任务最长等待秒数，默认 240")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="导出状态轮询秒数，默认 2")
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
        print("[XHS][订单][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[XHS][订单][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("订单", "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
