#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过京准通页面 WebAPI 下载京东联盟和京东通推广费原始报表。"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
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
        bounded_total_pages,
        check_human_gate,
        clone_payload,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        recent_30_day_range,
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
        bounded_total_pages,
        check_human_gate,
        clone_payload,
        default_yesterday,
        download_original_file,
        extract_download_url,
        log,
        open_jd_report_page,
        parse_date_range,
        recent_30_day_range,
        refresh_jd_page,
    )


PROFILE_NAME = "JD-京东-MOCK饮品旗舰店"

UNION_URL = "https://jzt.jd.com/jtk/#/account-bill"
UNION_PAGE_ROUTE = "/jtk/"
UNION_HOST = "jzt-api.jd.com"
UNION_QUERY_PATH = "/union/pop/account/list/billList"
UNION_GENERATE_PATH = "/union/pop/asyncDownload/generateTask"
UNION_TASK_PATH = "/union/pop/asyncDownload/getTaskList"
UNION_DOWNLOAD_PATH = "/union/pop/asyncDownload/downloadReport"
UNION_QUERY_URL = f"https://{UNION_HOST}{UNION_QUERY_PATH}?requestFrom=0"
UNION_GENERATE_URL = f"https://{UNION_HOST}{UNION_GENERATE_PATH}?requestFrom=0"
UNION_TASK_URL = f"https://{UNION_HOST}{UNION_TASK_PATH}?requestFrom=0"
UNION_DOWNLOAD_URL = f"https://{UNION_HOST}{UNION_DOWNLOAD_PATH}?requestFrom=0"
UNION_REPORT_NAME = "结算信息"
UNION_MODULE_TYPE = 2

TONG_URL = "https://jzt.jd.com/account/#/financialRecord"
TONG_PAGE_ROUTE = "/account/"
TONG_CONSUMPTION_XPATH = (
    '//*[@id="my-app"]/div/div/div/div/div[2]/div[1]/div/div[2]/div/div/div[2]/div[4]/span'
)
TONG_HOST = "atoms-api.jd.com"
TONG_QUERY_PATH = "/financecore/subaccount/cashconsume/list"
TONG_EXPORT_PATH = "/financecore/subaccount/cashconsume/export/async"
TONG_REPORT_PATH = "/api/download/common/asyn/download/reportInfo/list"
TONG_QUERY_URL = f"https://{TONG_HOST}{TONG_QUERY_PATH}"
TONG_EXPORT_URL = f"https://{TONG_HOST}{TONG_EXPORT_PATH}"
TONG_REPORT_URL = f"https://{TONG_HOST}{TONG_REPORT_PATH}"
TONG_REPORT_NAME = "财务记录_消费记录_现金"
TONG_REPORT_TYPE = 24


def promotion_period(value: str | None) -> tuple[date, date]:
    requested = parse_date_range(value, option="--date")
    if requested is not None:
        return requested
    return recent_30_day_range()


def build_union_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page_index: int = 1,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "dateType": 2,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "endDateForSubmit": end.isoformat(),
            "billStatus": 2,
            "pageIndex": page_index,
            "pageSize": 10,
            "withDailyData": 0,
        }
    )
    return payload


def build_union_generate_payload(start: date, end: date) -> dict[str, Any]:
    return {
        "moduleType": UNION_MODULE_TYPE,
        "reportName": UNION_REPORT_NAME,
        "payStatus": 2,
        "withDailyData": 0,
        "finishStartTime": start.isoformat(),
        "finishEndTime": end.isoformat(),
    }


def build_union_task_payload(page_index: int = 1) -> dict[str, Any]:
    return {"pageIndex": page_index, "pageSize": 10}


def build_union_download_payload(pk: int) -> dict[str, Any]:
    return {"pk": int(pk)}


def union_query_total(body: dict[str, Any]) -> int:
    content = body.get("content")
    if not isinstance(content, dict):
        content = body.get("data")
    if not isinstance(content, dict):
        raise ApiError("京东联盟推广费查询缺少 content/data 对象", body=body)
    return as_int(content.get("total"), 0)


def union_task_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content = body.get("content")
    if not isinstance(content, dict):
        content = body.get("data")
    if not isinstance(content, dict):
        raise ApiError("京东联盟任务列表缺少 content/data 对象", body=body)
    rows = content.get("data")
    if not isinstance(rows, list):
        raise ApiError("京东联盟任务列表缺少 data 数组", body=body)
    return [row for row in rows if isinstance(row, dict)], content


def select_union_task(
    rows: list[dict[str, Any]],
    *,
    submitted_after_ms: int,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("reportName") or "") == UNION_REPORT_NAME
        and as_int(row.get("moduleType"), -1) == UNION_MODULE_TYPE
        and as_int(row.get("insertTime"), 0) >= submitted_after_ms - 60_000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: as_int(row.get("insertTime"), 0))


def build_tong_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page: int = 1,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "beginDate": start.isoformat(),
            "endDate": end.isoformat(),
            "page": page,
            "pageSize": 10,
            "timeFilterType": 1,
            "invoiceApplyType": 0,
        }
    )
    return payload


def build_tong_export_payload(query_payload: dict[str, Any]) -> dict[str, Any]:
    payload = clone_payload(query_payload)
    payload["downloadName"] = TONG_REPORT_NAME
    return payload


def build_tong_report_payload(end: date) -> dict[str, Any]:
    # 报表历史页只需覆盖最近半年即可找到刚创建的任务；最终仍按精确
    # 报表名称、类型、起止日期和创建时间匹配。
    start = end - timedelta(days=184)
    return {
        "page": 1,
        "pageSize": 10,
        "startDay": start.isoformat(),
        "endDay": end.isoformat(),
        "nameLike": "",
        "type": TONG_REPORT_TYPE,
    }


def tong_report_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("京东通报表列表缺少 data 对象", body=body)
    rows = data.get("datas")
    if not isinstance(rows, list):
        raise ApiError("京东通报表列表缺少 datas 数组", body=body)
    return [row for row in rows if isinstance(row, dict)], data


def _created_ms(value: Any) -> int:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
    except ValueError:
        return 0
    return int(parsed.timestamp() * 1000)


def select_tong_report(
    rows: list[dict[str, Any]],
    *,
    start: date,
    end: date,
    submitted_after_ms: int,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("reportName") or "") == TONG_REPORT_NAME
        and as_int(row.get("type"), -1) == TONG_REPORT_TYPE
        and str(row.get("startDay") or "") == start.isoformat()
        and str(row.get("endDay") or "") == end.isoformat()
        and _created_ms(row.get("createdTime")) >= submitted_after_ms - 60_000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _created_ms(row.get("createdTime")))


async def wait_for_union_report(
    api: BrowserApiSession,
    *,
    submitted_after_ms: int,
    timeout: float,
    poll_interval: float,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    last_status = ""
    while asyncio.get_running_loop().time() < deadline:
        first = await api.post_json(
            UNION_TASK_URL,
            build_union_task_payload(),
            label="京东联盟推广费任务查询",
            timeout=timeout,
        )
        rows, data = union_task_rows(first)
        total_pages = bounded_total_pages(data, label="京东联盟推广费任务查询")
        for page_index in range(2, total_pages + 1):
            body = await api.post_json(
                UNION_TASK_URL,
                build_union_task_payload(page_index),
                label="京东联盟推广费任务查询",
                timeout=timeout,
            )
            page_rows, _ = union_task_rows(body)
            rows.extend(page_rows)
        task = select_union_task(rows, submitted_after_ms=submitted_after_ms)
        if task is not None:
            status = as_int(task.get("generateStatus"), -1)
            if status == 2:
                pk = as_int(task.get("pk"), 0)
                if not pk:
                    raise ApiError("京东联盟就绪任务缺少 pk", body=task)
                download_body = await api.post_json(
                    UNION_DOWNLOAD_URL,
                    build_union_download_payload(pk),
                    label="京东联盟推广费下载地址",
                    timeout=timeout,
                )
                return extract_download_url(download_body, label="京东联盟推广费下载地址")
            if status in {4, 5, -1}:
                raise RuntimeError(f"京东联盟推广费任务失败，状态={status}")
            current = str(status)
            if current != last_status:
                log("推广费", "联盟任务", f"报表生成中，状态={current}")
                last_status = current
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"等待京东联盟推广费报表超时，最后状态={last_status or '未找到任务'}")


async def wait_for_tong_report(
    api: BrowserApiSession,
    *,
    start: date,
    end: date,
    submitted_after_ms: int,
    timeout: float,
    poll_interval: float,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    last_status = ""
    while asyncio.get_running_loop().time() < deadline:
        body = await api.post_json(
            TONG_REPORT_URL,
            build_tong_report_payload(end),
            label="京东通推广费任务查询",
            timeout=timeout,
        )
        rows, data = tong_report_rows(body)
        task = select_tong_report(
            rows,
            start=start,
            end=end,
            submitted_after_ms=submitted_after_ms,
        )
        if task is not None:
            status = as_int(task.get("status"), -1)
            signed_url = task.get("downloadUrl")
            if status == 2 and isinstance(signed_url, str) and signed_url.startswith(("http://", "https://")):
                return signed_url
            if status in {3, 4, 5}:
                raise RuntimeError(f"京东通推广费任务失败，状态={status}")
            current = str(status)
            if current != last_status:
                log("推广费", "京东通任务", f"报表生成中，状态={current}")
                last_status = current
        del data
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"等待京东通推广费报表超时，最后状态={last_status or '未找到任务'}")


async def _run_union(
    page: Any,
    api: BrowserApiSession,
    collector: NaturalRequestCollector,
    args: argparse.Namespace,
    start: date,
    end: date,
) -> Path | None:
    template = await collector.wait_for_payload(
        UNION_HOST,
        UNION_QUERY_PATH,
        UNION_PAGE_ROUTE,
        page,
        timeout=min(float(getattr(args, "timeout", 240.0)), 30.0),
    )
    query_body = await api.post_json(
        UNION_QUERY_URL,
        build_union_query_payload(template, start, end),
        label="京东联盟推广费查询",
        timeout=float(getattr(args, "timeout", 240.0)),
    )
    total = union_query_total(query_body)
    log("推广费", "联盟查询", f"匹配行数={total}")
    if total <= 0:
        log("推广费", "联盟完成", "指定日期无数据，未创建导出任务")
        return None

    submitted_after_ms = int(time.time() * 1000)
    await api.post_json(
        UNION_GENERATE_URL,
        build_union_generate_payload(start, end),
        label="京东联盟推广费任务创建",
        timeout=float(getattr(args, "timeout", 240.0)),
    )
    signed_url = await wait_for_union_report(
        api,
        submitted_after_ms=submitted_after_ms,
        timeout=float(getattr(args, "timeout", 240.0)),
        poll_interval=float(getattr(args, "poll_interval", 2.0)),
    )
    output = await asyncio.to_thread(
        download_original_file,
        signed_url,
        Path(args.output_dir),
        f"JD_union_promotion_fee_{start.isoformat()}_to_{end.isoformat()}.xlsx",
        referer=str(page.url),
    )
    log("推广费", "联盟完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
    return output


async def _run_tong(
    page: Any,
    api: BrowserApiSession,
    collector: NaturalRequestCollector,
    args: argparse.Namespace,
    start: date,
    end: date,
) -> Path | None:
    template = await collector.wait_for_payload(
        TONG_HOST,
        TONG_QUERY_PATH,
        TONG_PAGE_ROUTE,
        page,
        timeout=min(float(getattr(args, "timeout", 240.0)), 30.0),
    )
    query_payload = build_tong_query_payload(template, start, end)
    query_body = await api.post_json(
        TONG_QUERY_URL,
        query_payload,
        label="京东通推广费查询",
        timeout=float(getattr(args, "timeout", 240.0)),
    )
    data = query_body.get("data")
    nested = data.get("data") if isinstance(data, dict) else None
    paginator = data.get("paginator") if isinstance(data, dict) else None
    total = as_int(paginator.get("total"), 0) if isinstance(paginator, dict) else 0
    if not isinstance(nested, dict):
        raise ApiError("京东通推广费查询缺少 data.data", body=query_body)
    log("推广费", "京东通查询", f"匹配行数={total}")
    if total <= 0:
        log("推广费", "京东通完成", "指定日期无数据，未创建导出任务")
        return None

    submitted_after_ms = int(time.time() * 1000)
    await api.post_json(
        TONG_EXPORT_URL,
        build_tong_export_payload(query_payload),
        label="京东通推广费任务创建",
        timeout=float(getattr(args, "timeout", 240.0)),
    )
    signed_url = await wait_for_tong_report(
        api,
        start=start,
        end=end,
        submitted_after_ms=submitted_after_ms,
        timeout=float(getattr(args, "timeout", 240.0)),
        poll_interval=float(getattr(args, "poll_interval", 2.0)),
    )
    output = await asyncio.to_thread(
        download_original_file,
        signed_url,
        Path(args.output_dir),
        f"JD_tong_promotion_fee_{start.isoformat()}_to_{end.isoformat()}.xls",
        referer=str(page.url),
    )
    log("推广费", "京东通完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
    return output


async def _open_tong_consumption_tab(page: Any) -> None:
    """复用现有 DOM 流程切到“消费记录”，触发现金流水自然请求。"""

    exact = page.locator(f"xpath={TONG_CONSUMPTION_XPATH}")
    if await exact.count():
        target = exact.last
    else:
        fallback = page.get_by_text("消费记录", exact=True)
        if not await fallback.count():
            raise RuntimeError("京东通页面未找到“消费记录”页签")
        target = fallback.last
    await target.wait_for(state="visible", timeout=45_000)
    await target.click()
    with suppress(Exception):
        await page.wait_for_timeout(1_000)


async def run_one_with_endpoint(
    args: argparse.Namespace,
    endpoint: str,
    kind: str,
) -> Path | None:
    from playwright.async_api import async_playwright

    if kind not in {"union", "tong"}:
        raise ValueError(f"推广费子报表必须是 union 或 tong：{kind!r}")
    start, end = promotion_period(getattr(args, "date", None))
    url = UNION_URL if kind == "union" else TONG_URL
    page_route = UNION_PAGE_ROUTE if kind == "union" else TONG_PAGE_ROUTE
    label = "联盟" if kind == "union" else "京东通"
    collector = NaturalRequestCollector()
    page: Any | None = None

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(endpoint)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器中没有可用上下文")
        context = browser.contexts[0]
        collector.attach(context)
        try:
            log("推广费", "计划", f"{label}：{start.isoformat()} 到 {end.isoformat()}")
            page = await open_jd_report_page(context, url)
            await check_human_gate(page)
            if kind == "tong":
                await _open_tong_consumption_tab(page)

            async def refresh() -> None:
                await refresh_jd_page(page, url)

            api = BrowserApiSession(
                page,
                collector,
                page_route=page_route,
                refresh=refresh,
            )
            if kind == "union":
                return await _run_union(page, api, collector, args, start, end)
            return await _run_tong(page, api, collector, args, start, end)
        finally:
            collector.detach()
            if page is not None:
                with suppress(Exception):
                    await page.close()


async def run_all_with_endpoint(args: argparse.Namespace, endpoint: str) -> list[Path]:
    outputs: list[Path] = []
    for kind in ("union", "tong"):
        output = await run_one_with_endpoint(args, endpoint, kind)
        if output is not None:
            outputs.append(output)
    return outputs


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
        timeout=getattr(args, "profile_timeout", 30.0),
        poll_interval=getattr(args, "profile_poll_interval", 0.5),
    ).endpoint


async def run_async(args: argparse.Namespace) -> Path | None:
    endpoint = resolve_endpoint(args)
    if getattr(args, "report", "all") == "all":
        outputs = await run_all_with_endpoint(args, endpoint)
        return outputs[0] if outputs else None
    return await run_one_with_endpoint(args, endpoint, args.report)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="京东联盟和京东通推广费 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", default=PROFILE_NAME, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--report", choices=("all", "union", "tong"), default="all", help="推广费子报表，默认 all")
    parser.add_argument("--date", help="指定日期或范围：YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD；默认近30天")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=600.0, help="导出任务最长等待秒数，默认 600")
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
        print("[JD][推广费][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[JD][推广费][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("推广费", "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
