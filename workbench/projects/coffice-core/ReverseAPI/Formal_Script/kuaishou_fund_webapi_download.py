#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快手资金日账单/月账单 WebAPI 下载。

流程：进入资金页并监听自然查询 -> 取得可用资金账户 -> 通过资金统计接口
精确选择日/月 -> 创建导出任务 -> 优先使用创建接口返回的当前短效下载地址；
若接口异步返回空地址，则轮询导出任务并在已认证页面的导出记录中接收文件。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
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
    from ReverseAPI.Formal_Script.kuaishou_webapi_common import (
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
        download_browser_url,
        log,
        open_kuaishou_report_page,
        parse_iso_date,
        refresh_kuaishou_page,
        response_payload,
        save_playwright_download,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from kuaishou_webapi_common import (  # type: ignore[no-redef]
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
        download_browser_url,
        log,
        open_kuaishou_report_page,
        parse_iso_date,
        refresh_kuaishou_page,
        response_payload,
        save_playwright_download,
    )


FUND_URL = "https://s.kwaixiaodian.com/zone/fund/accounting/account-bill"
FUND_PAGE_ROUTE = "/zone/fund/accounting/account-bill"
EXPORT_LIST_URL = "https://s.kwaixiaodian.com/zone/fund/accounting/export-list"
API_ORIGIN = "https://s.kwaixiaodian.com"
SUB_ACCOUNT_PATH = "/rest/app/tts/business/api/funds/wallet/sub/query/info"
STATISTIC_PATH = "/rest/app/tts/business/api/funds/wallet/query/account/bill/statistic"
CREATE_TASK_PATH = "/rest/app/tts/business/api/funds/wallet/create/export/task"
LIST_TASK_PATH = "/rest/app/tts/business/api/funds/wallet/list/export/task"
SUB_ACCOUNT_URL = API_ORIGIN + SUB_ACCOUNT_PATH
STATISTIC_URL = API_ORIGIN + STATISTIC_PATH
CREATE_TASK_URL = API_ORIGIN + CREATE_TASK_PATH
LIST_TASK_URL = API_ORIGIN + LIST_TASK_PATH

ACCOUNT_TYPE = "ACCOUNT_TYPE_WALLET_PINGAN"
ACCOUNT_ROLE = "ACCOUNT_ROLE_SELLER"
BID_BIZ_TYPE = "seller_or_promoter"
TASK_KIND = 10000
DAY_BILL_TYPE = "BY_DAY"
MONTH_BILL_TYPE = "BY_MONTH"

DAY_KEY_RE = re.compile(r"^\d{8}$")
MONTH_KEY_RE = re.compile(r"^\d{6}$")


def _shift_month(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(month_index, 12)
    return date(year, month_index + 1, 1)


def _month_end(value: date) -> date:
    return _shift_month(value.replace(day=1), 1) - timedelta(days=1)


def parse_fund_period(value: str | None, mode: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip().replace("/", "-")
    if mode == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", raw):
            raise ValueError("月账单 --date 必须使用 YYYY-MM 格式")
        try:
            return datetime.strptime(raw, "%Y-%m").date().replace(day=1)
        except ValueError as exc:
            raise ValueError(f"月账单日期无效：{value!r}") from exc
    return parse_iso_date(raw, option="--date")


def fund_period_key(value: date, mode: str) -> str:
    return value.strftime("%Y%m" if mode == "month" else "%Y%m%d")


def fund_period_bounds(value: date, mode: str) -> tuple[date, date]:
    if mode == "month":
        start = value.replace(day=1)
        return start, _month_end(start)
    return value, value


def fund_query_window(
    mode: str,
    requested: date | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """生成页面实际使用的可服务查询窗口。

    日账单按目标日向前 30 天查询；月账单按目标月份及之前最多六个完整
    月份查询。最终仍按 period key 精确匹配，避免相邻账单被误取。
    """

    current = today or datetime.now(CN_TZ).date()
    if mode == "day":
        target = requested or (current - timedelta(days=1))
        return target - timedelta(days=30), target
    target = requested or _shift_month(current.replace(day=1), -1)
    start = _shift_month(target.replace(day=1), -5)
    return start, _month_end(target)


def build_statistic_payload(
    template: dict[str, Any],
    mode: str,
    start: date,
    end: date,
    sub_mch_id: str,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "accountType": ACCOUNT_TYPE,
            "accountRole": ACCOUNT_ROLE,
            "billType": DAY_BILL_TYPE if mode == "day" else MONTH_BILL_TYPE,
            "subMchId": str(sub_mch_id),
            "startTime": date_to_ms(start, end_of_day=False),
            "endTime": date_to_ms(end, end_of_day=True, end_millisecond=999),
            "bidBizType": BID_BIZ_TYPE,
        }
    )
    return payload


def fund_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = response_payload(body, label="资金统计")
    if not isinstance(value, list):
        raise ApiError("资金统计返回的 data 不是数组", body=body)
    rows = [item for item in value if isinstance(item, dict)]
    if len(rows) != len(value):
        raise ApiError("资金统计返回包含非对象账单行", body=body)
    return rows


def row_period_key(row: dict[str, Any], mode: str) -> str:
    value = str(row.get("date") or "").strip()
    pattern = MONTH_KEY_RE if mode == "month" else DAY_KEY_RE
    return value if pattern.fullmatch(value) else ""


def select_fund_row(
    rows: list[dict[str, Any]],
    mode: str,
    requested: date | None,
) -> dict[str, Any] | None:
    expected = fund_period_key(requested, mode) if requested is not None else None
    candidates = [
        row
        for row in rows
        if row_period_key(row, mode)
        and (expected is None or row_period_key(row, mode) == expected)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row_period_key(row, mode))


def select_account(
    accounts: list[dict[str, Any]],
    explicit_sub_mch_id: str | None = None,
) -> dict[str, Any]:
    candidates = [
        account
        for account in accounts
        if isinstance(account, dict) and str(account.get("subMchId") or "").strip()
    ]
    if explicit_sub_mch_id:
        expected = str(explicit_sub_mch_id).strip()
        matches = [item for item in candidates if str(item.get("subMchId")) == expected]
        if not matches:
            raise ApiError(f"资金账户中不存在指定二级商户号：{expected}")
        return matches[0]

    enabled = [
        item
        for item in candidates
        if str(item.get("bindState") or "").upper() == "ENABLE"
        and str(item.get("accountState") or "").upper() == "NORMAL"
    ]
    if len(enabled) == 1:
        return enabled[0]
    if len(enabled) > 1:
        ids = ", ".join(str(item.get("subMchId")) for item in enabled)
        raise ApiError(f"当前 Profile 有多个可用资金账户，请使用 --sub-mch-id 指定：{ids}")
    if len(candidates) == 1:
        return candidates[0]
    raise ApiError("未找到唯一可用资金账户，请检查权限或使用 --sub-mch-id 指定")


def extract_operator_name(text: str) -> str:
    match = re.search(r"(?:账号?\s*)?ID\s*[：:]\s*(\d+)", text or "", flags=re.IGNORECASE)
    if not match:
        raise ApiError("快手资金页未识别当前操作员 ID，无法安全创建导出任务")
    return match.group(1)


def build_create_task_payload(
    account: dict[str, Any],
    operator_name: str,
    period_start: date,
    period_end: date,
    mode: str,
) -> dict[str, Any]:
    sub_mch_id = str(account.get("subMchId") or "").strip()
    if not sub_mch_id:
        raise ValueError("资金账户缺少 subMchId")
    export_config = {
        "startTime": date_to_ms(period_start, end_of_day=False),
        "endTime": date_to_ms(period_end, end_of_day=True, end_millisecond=999),
        "subMchId": sub_mch_id,
        "dateType": 1 if mode == "day" else 2,
    }
    return {
        "accountType": ACCOUNT_TYPE,
        "accountRole": ACCOUNT_ROLE,
        "operatorName": str(operator_name),
        "taskKind": TASK_KIND,
        "exportConfig": json.dumps(export_config, ensure_ascii=False, separators=(",", ":")),
        "bidBizType": BID_BIZ_TYPE,
    }


def build_list_task_payload(sub_mch_id: str) -> dict[str, Any]:
    return {
        "accountType": ACCOUNT_TYPE,
        "accountRole": ACCOUNT_ROLE,
        "subMchId": str(sub_mch_id),
        "size": 10,
        "page": 1,
        "taskKind": TASK_KIND,
        "bidBizType": BID_BIZ_TYPE,
    }


def parse_export_config(value: Any) -> dict[str, Any] | None:
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
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        with suppress(ValueError):
            return int(
                datetime.strptime(text[:19], fmt)
                .replace(tzinfo=CN_TZ)
                .timestamp()
                * 1000
            )
    with suppress(ValueError):
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000
    return 0


def fund_task_records(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("exportTaskRecord")
    if not isinstance(value, list):
        raise ApiError("资金导出任务返回缺少 exportTaskRecord 数组", body=body)
    records = [item for item in value if isinstance(item, dict)]
    if len(records) != len(value):
        raise ApiError("资金导出任务包含非对象记录", body=body)
    return records


def select_fund_task(
    records: list[dict[str, Any]],
    expected_period: str,
    *,
    submitted_after_ms: int = 0,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for record in records:
        if as_int(record.get("taskKind"), -1) != TASK_KIND:
            continue
        config = parse_export_config(record.get("exportConfig"))
        if not config:
            continue
        if str(config.get("startTime") or "") != expected_period:
            continue
        if str(config.get("endTime") or "") != expected_period:
            continue
        created = _task_time_ms(record.get("createTime"))
        if submitted_after_ms and created and created < submitted_after_ms - 120_000:
            continue
        matches.append(record)
    matches.sort(key=lambda item: _task_time_ms(item.get("createTime")), reverse=True)
    if not matches:
        return None
    newest = matches[0]
    status = as_int(newest.get("status"), -1)
    if status == 2:
        return newest
    if status in {3, 4, 5, -1} and str(newest.get("failedReason") or "").strip():
        raise ApiError(f"资金导出任务失败：{newest.get('failedReason')}")
    return None


def fund_download_url(body: dict[str, Any]) -> str | None:
    value = body.get("downloadUrl")
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ApiError("资金创建任务返回了无效下载地址", body=body)
    return value


async def _download_from_history(
    page: Any,
    expected_period: str,
    output_dir: Path,
    filename: str,
    *,
    timeout: float,
) -> Path:
    await page.goto(EXPORT_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
    await check_human_gate(page)
    target = f"账单日期：{expected_period}"
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        cards = page.locator("div.container___mBlUU").filter(has_text=target)
        if await cards.count():
            card = cards.first
            button = card.get_by_role("button", name=re.compile(r"^\s*下\s*载\s*$"))
            if await button.count() and await button.first.is_visible():
                async with page.expect_download(timeout=120_000) as info:
                    await button.first.click()
                return await save_playwright_download(await info.value, output_dir, filename)
        await page.reload(wait_until="domcontentloaded")
        await asyncio.sleep(1.0)
    raise RuntimeError(f"资金导出记录未生成：{expected_period}")


async def _poll_fund_task(
    api: BrowserApiSession,
    sub_mch_id: str,
    expected_period: str,
    *,
    submitted_after_ms: int,
    timeout: float,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = await api.post_json(
            LIST_TASK_URL,
            build_list_task_payload(sub_mch_id),
            label="资金导出任务查询",
            timeout=min(timeout, 60.0),
        )
        task = select_fund_task(
            fund_task_records(body),
            expected_period,
            submitted_after_ms=submitted_after_ms,
        )
        if task is not None:
            return task
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"资金导出任务等待超时：{expected_period}")


async def _wait_statistic_template(
    page: Any,
    collector: NaturalRequestCollector,
    mode: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    """取得真实页面统计模板；必要时只点击一次查询触发自然请求。"""

    if mode == "month":
        month_tab = page.get_by_role("tab", name="月账单", exact=True)
        if await month_tab.count() and await month_tab.first.is_visible():
            await month_tab.first.click()
    try:
        return await collector.wait_for_payload(
            "s.kwaixiaodian.com",
            STATISTIC_PATH,
            FUND_PAGE_ROUTE,
            page,
            timeout=min(timeout, 5.0),
        )
    except RuntimeError:
        query_button = page.get_by_role("button", name=re.compile(r"^\s*查\s*询\s*$"))
        if not await query_button.count():
            raise
        await query_button.first.click()
        return await collector.wait_for_payload(
            "s.kwaixiaodian.com",
            STATISTIC_PATH,
            FUND_PAGE_ROUTE,
            page,
            timeout=min(timeout, 30.0),
        )


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

    mode = str(getattr(args, "mode", "day") or "day").strip().lower()
    if mode not in {"day", "month"}:
        raise ValueError("资金 mode 只允许 day 或 month")
    requested = parse_fund_period(getattr(args, "date", None), mode)
    window_start, window_end = fund_query_window(mode, requested)
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
            log(
                "资金",
                "计划",
                f"模式={'月账单' if mode == 'month' else '日账单'}，查询窗口="
                f"{window_start.isoformat()} 到 {window_end.isoformat()}"
                + (f"，精确账期={fund_period_key(requested, mode)}" if requested else "，自动取最新账期"),
            )
            page = await open_kuaishou_report_page(context, FUND_URL)
            await check_human_gate(page)

            async def refresh() -> None:
                await refresh_kuaishou_page(page, FUND_URL)

            api = BrowserApiSession(
                page,
                collector,
                page_route=FUND_PAGE_ROUTE,
                refresh=refresh,
            )
            statistic_template = await _wait_statistic_template(
                page,
                collector,
                mode,
                timeout=timeout,
            )
            account_body = await api.post_json(
                SUB_ACCOUNT_URL,
                {
                    "accountRole": ACCOUNT_ROLE,
                    "accountType": ACCOUNT_TYPE,
                    "bidBizType": BID_BIZ_TYPE,
                },
                label="资金账户查询",
                timeout=timeout,
            )
            account_data = response_payload(account_body, label="资金账户查询")
            if not isinstance(account_data, list):
                raise ApiError("资金账户查询返回的 data 不是数组", body=account_body)
            account = select_account(account_data, getattr(args, "sub_mch_id", None))
            sub_mch_id = str(account["subMchId"])

            query_body = await api.post_json(
                STATISTIC_URL,
                build_statistic_payload(
                    statistic_template,
                    mode,
                    window_start,
                    window_end,
                    sub_mch_id,
                ),
                label="资金统计查询",
                timeout=timeout,
            )
            row = select_fund_row(fund_rows(query_body), mode, requested)
            if row is None:
                log("资金", "完成", "没有匹配的资金账期，未创建导出任务")
                return None
            selected_key = row_period_key(row, mode)
            selected_period = (
                datetime.strptime(selected_key, "%Y%m").date().replace(day=1)
                if mode == "month"
                else datetime.strptime(selected_key, "%Y%m%d").date()
            )
            period_start, period_end = fund_period_bounds(selected_period, mode)
            body_text = await page.locator("body").inner_text(timeout=5_000)
            operator_name = extract_operator_name(body_text)
            submitted_after_ms = int(time.time() * 1000)
            create_body = await api.post_json(
                CREATE_TASK_URL,
                build_create_task_payload(
                    account,
                    operator_name,
                    period_start,
                    period_end,
                    mode,
                ),
                label="资金导出任务创建",
                timeout=timeout,
            )
            direct_url = fund_download_url(create_body)
            period_name = selected_period.strftime("%Y-%m") if mode == "month" else selected_period.isoformat()
            output_name = f"KS_fund_{'month' if mode == 'month' else 'day'}_{period_name}.csv"
            if direct_url:
                output = await download_browser_url(page, direct_url, output_dir, output_name)
                log("资金", "完成", f"账期={selected_key}，文件={output}（{output.stat().st_size} bytes）")
                return output

            task = await _poll_fund_task(
                api,
                sub_mch_id,
                selected_key,
                submitted_after_ms=submitted_after_ms,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            del task  # 任务已按账期、类型和提交时间精确校验
            output = await _download_from_history(
                page,
                selected_key,
                output_dir,
                output_name,
                timeout=timeout,
            )
            log("资金", "完成", f"账期={selected_key}，文件={output}（{output.stat().st_size} bytes）")
            return output
        finally:
            collector.detach()
            if page is not None:
                with suppress(Exception):
                    await page.close()


async def run_async(args: argparse.Namespace) -> Path | None:
    return await run_with_endpoint(args, resolve_endpoint(args))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="快手资金日/月账单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--mode", choices=("day", "month"), default="day", help="账单模式，默认 day")
    parser.add_argument("--date", help="精确账期：日账单 YYYY-MM-DD；月账单 YYYY-MM")
    parser.add_argument("--sub-mch-id", help="可选：显式指定资金账户二级商户号")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=240.0, help="接口和导出任务最长等待秒数，默认 240")
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
        print("[快手][资金][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[快手][资金][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log("资金", "完成", "任务完成：无匹配账期")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
