#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快手结算单 WebAPI 下载。

先用页面自然请求取得查询上下文，再查询指定日期范围。只有服务端返回有
记录时才创建导出任务；随后按完整日期参数轮询导出任务，最后通过官方
``fileId`` 下载原始 ZIP，不解压、不猜测文件内容。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from contextlib import suppress
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script.kuaishou_webapi_common import (
        ApiError,
        BrowserApiSession,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        check_human_gate,
        clone_payload,
        date_to_ms,
        default_yesterday,
        download_original_file,
        log,
        open_kuaishou_report_page,
        parse_date_range,
        refresh_kuaishou_page,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from kuaishou_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        NaturalRequestCollector,
        as_int,
        check_human_gate,
        clone_payload,
        date_to_ms,
        default_yesterday,
        download_original_file,
        log,
        open_kuaishou_report_page,
        parse_date_range,
        refresh_kuaishou_page,
    )


SETTLEMENT_URL = "https://s.kwaixiaodian.com/zone/fund/accounting/payment-bill"
SETTLEMENT_PAGE_ROUTE = "/zone/fund/accounting/payment-bill"
API_ORIGIN = "https://s.kwaixiaodian.com"
QUERY_PATH = "/rest/app/tts/business/api/funds/financial/bill/pcpageorder/list"
CREATE_PATH = "/rest/app/tts/financial/center/create/bill/download"
LIST_PATH = "/rest/app/tts/financial/center/list/bill/download"
DOWNLOAD_PATH = "/rest/app/tts/financial/center/bill/download"
QUERY_URL = API_ORIGIN + QUERY_PATH
CREATE_URL = API_ORIGIN + CREATE_PATH
LIST_URL = API_ORIGIN + LIST_PATH
DOWNLOAD_URL = API_ORIGIN + DOWNLOAD_PATH
SETTLEMENT_TYPE = "SELLER_SETTLED_ORDER_V2"
BID_BIZ_TYPE = "seller_or_promoter"
CHANNELS = ("WECHAT", "ALIPAY_ZFT", "BALANCE", "PINGAN_JZB")


def build_query_payload(
    template: dict[str, Any] | None,
    start: date,
    end: date,
    *,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    payload = clone_payload(template or {})
    payload.update(
        {
            "limit": int(limit),
            "page": int(page),
            "settlementStatus": ["COMPLETED"],
            # 结算接口抓包使用整秒结束边界（.000），不能复用资金接口
            # 的 .999 边界。
            "settlementTimeGte": date_to_ms(start, end_of_day=False),
            "settlementTimeLte": date_to_ms(end, end_of_day=True, end_millisecond=0),
            "accountChannel": list(CHANNELS),
        }
    )
    return payload


def response_settlement_data(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("结算查询缺少 data 对象", body=body)
    if "total" not in data:
        raise ApiError("结算查询缺少 data.total", body=body)
    total = as_int(data.get("total"), -1)
    if total < 0:
        raise ApiError("结算查询 data.total 不是有效整数", body=body)
    orders = data.get("orders")
    if not isinstance(orders, list):
        raise ApiError("结算查询缺少 data.orders 数组", body=body)
    return total, data


def has_settlement_rows(body: dict[str, Any]) -> bool:
    total, _ = response_settlement_data(body)
    return total > 0


def build_create_payload(query_payload: dict[str, Any]) -> dict[str, Any]:
    required = ("settlementTimeGte", "settlementTimeLte")
    if any(key not in query_payload for key in required):
        raise ValueError("结算创建任务缺少日期边界")
    channels = query_payload.get("accountChannel")
    if not isinstance(channels, list) or not channels:
        raise ValueError("结算创建任务缺少账户渠道")
    ext_params = {
        "page": as_int(query_payload.get("page"), 1),
        "limit": as_int(query_payload.get("limit"), 10),
        "settlementTimeGte": as_int(query_payload.get("settlementTimeGte"), -1),
        "settlementTimeLte": as_int(query_payload.get("settlementTimeLte"), -1),
        "accountChannel": ",".join(str(item) for item in channels),
    }
    if ext_params["settlementTimeGte"] < 0 or ext_params["settlementTimeLte"] < 0:
        raise ValueError("结算创建任务日期边界无效")
    return {
        "extParams": json.dumps(ext_params, ensure_ascii=False, separators=(",", ":")),
        "type": SETTLEMENT_TYPE,
    }


def build_list_payload(*, page: int = 1, limit: int = 20) -> dict[str, Any]:
    return {
        "page": int(page),
        "limit": int(limit),
        "type": SETTLEMENT_TYPE,
        "bidBizType": BID_BIZ_TYPE,
    }


def parse_ext_param(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return clone_payload(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _task_time_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    text = str(value or "").strip()
    if not text:
        return 0
    with suppress(ValueError):
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000
    return 0


def _same_ext_params(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    keys = ("page", "limit", "settlementTimeGte", "settlementTimeLte", "accountChannel")
    return all(str(actual.get(key)) == str(expected.get(key)) for key in keys)


def select_settlement_task(
    file_items: list[dict[str, Any]],
    query_payload: dict[str, Any],
    *,
    submitted_after_ms: int = 0,
) -> dict[str, Any] | None:
    expected = parse_ext_param(build_create_payload(query_payload)["extParams"])
    if expected is None:
        raise ValueError("结算创建任务 extParams 生成失败")
    matches: list[dict[str, Any]] = []
    for item in file_items:
        if str(item.get("bizSubType") or "") != SETTLEMENT_TYPE:
            continue
        actual = parse_ext_param(item.get("extParam"))
        if actual is None or not _same_ext_params(actual, expected):
            continue
        created = _task_time_ms(item.get("createTime"))
        if submitted_after_ms and created and created < submitted_after_ms - 120_000:
            continue
        matches.append(item)
    matches.sort(key=lambda item: _task_time_ms(item.get("createTime")), reverse=True)
    if not matches:
        return None
    newest = matches[0]
    status = as_int(newest.get("status"), -1)
    if status == 30:
        return newest
    if status in {40, 50, -1}:
        reason = str(newest.get("failedReason") or "").strip()
        if reason:
            raise ApiError(f"结算导出任务失败：{reason}")
    return None


def file_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("fileItems")
    if not isinstance(value, list):
        raise ApiError("结算导出任务返回缺少 fileItems 数组", body=body)
    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value):
        raise ApiError("结算导出任务包含非对象记录", body=body)
    return items


def build_download_url(file_id: Any) -> str:
    value = str(file_id or "").strip()
    if not re.fullmatch(r"\d+", value):
        raise ApiError("结算导出任务缺少有效 fileId")
    return f"{DOWNLOAD_URL}?{urlencode({'fileId': value})}"


async def _poll_settlement_task(
    api: BrowserApiSession,
    query_payload: dict[str, Any],
    *,
    submitted_after_ms: int,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = await api.post_json(
            LIST_URL,
            build_list_payload(),
            label="结算导出任务查询",
            timeout=min(timeout, 60.0),
        )
        task = select_settlement_task(
            file_items(body),
            query_payload,
            submitted_after_ms=submitted_after_ms,
        )
        if task is not None:
            return task
        await asyncio.sleep(poll_interval)
    raise TimeoutError("结算导出任务等待超时")


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

    selection = parse_date_range(getattr(args, "date", None), option="--date")
    if selection is None:
        target = default_yesterday()
        start, end = target, target
    else:
        start, end = selection
    output_dir = Path(args.output_dir)
    timeout = float(getattr(args, "timeout", 600.0))
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
            log("结算", "计划", f"查询范围={start.isoformat()} 到 {end.isoformat()}")
            page = await open_kuaishou_report_page(context, SETTLEMENT_URL)
            await check_human_gate(page)

            async def refresh() -> None:
                await refresh_kuaishou_page(page, SETTLEMENT_URL)

            api = BrowserApiSession(
                page,
                collector,
                page_route=SETTLEMENT_PAGE_ROUTE,
                refresh=refresh,
            )
            query_template = await collector.wait_for_payload(
                "s.kwaixiaodian.com",
                QUERY_PATH,
                SETTLEMENT_PAGE_ROUTE,
                page,
                timeout=min(timeout, 30.0),
            )
            query_payload = build_query_payload(query_template, start, end)
            query_body = await api.post_json(
                QUERY_URL,
                query_payload,
                label="结算账单查询",
                timeout=timeout,
            )
            total, _ = response_settlement_data(query_body)
            log("结算", "查询", f"服务端记录数={total}")
            if total == 0:
                log("结算", "完成", "查询无记录，未创建导出任务")
                return None

            submitted_after_ms = int(time.time() * 1000)
            await api.post_json(
                CREATE_URL,
                build_create_payload(query_payload),
                label="结算导出任务创建",
                timeout=timeout,
            )
            task = await _poll_settlement_task(
                api,
                query_payload,
                submitted_after_ms=submitted_after_ms,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            download_url = build_download_url(task.get("id"))
            output_name = f"KS_settlement_{start.isoformat()}_to_{end.isoformat()}.zip"
            cookies = await context.cookies()
            output = await asyncio.to_thread(
                download_original_file,
                download_url,
                output_dir,
                output_name,
                cookies=cookies,
                referer=str(page.url),
            )
            log("结算", "完成", f"文件={output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            if page is not None:
                with suppress(Exception):
                    await page.close()


async def run_async(args: argparse.Namespace) -> Path | None:
    return await run_with_endpoint(args, resolve_endpoint(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="快手结算单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--date", help="结算范围：YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD；不填默认昨天")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=600.0, help="导出任务最长等待秒数，默认 600")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="导出任务轮询秒数，默认 2")
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
        print("[快手][结算][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[快手][结算][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("结算", "完成", "任务完成：查询无记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
