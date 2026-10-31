#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通过抖店真实 WebAPI 下载结算账单明细 CSV。

页面只负责进入已经登录的抖店结算账单上下文；查询、生成导出任务、历史
任务轮询和签名文件下载均使用结算页实际调用的接口。默认下载昨天，
``--date`` 支持单日或闭区间日期。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script.douyin_webapi_common import (
        ApiError,
        BrowserApiSession,
        CN_TZ,
        CREATE_DOWNLOAD_PATH,
        DEFAULT_OUTPUT_DIR,
        DOWNLOAD_URL_PATH,
        HISTORY_URL,
        NeedsHumanError,
        QUERY_ITEM_PATH,
        SETTLEMENT_URL,
        SHOP_CONFIG_PATH,
        extract_download_id,
        extract_shop_id,
        extract_signed_url,
        format_api_time,
        is_human_error_message,
        log,
        parse_data_rows,
        period_text,
        read_total,
        resolve_date_range,
        wait_for_history_task,
        download_file,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from douyin_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        BrowserApiSession,
        CN_TZ,
        CREATE_DOWNLOAD_PATH,
        DEFAULT_OUTPUT_DIR,
        DOWNLOAD_URL_PATH,
        HISTORY_URL,
        NeedsHumanError,
        QUERY_ITEM_PATH,
        SETTLEMENT_URL,
        SHOP_CONFIG_PATH,
        extract_download_id,
        extract_shop_id,
        extract_signed_url,
        format_api_time,
        is_human_error_message,
        log,
        parse_data_rows,
        period_text,
        read_total,
        resolve_date_range,
        wait_for_history_task,
        download_file,
    )


REPORT_LABEL = "结算"
DOWNLOAD_TYPE = "SHOP_SETTLE_ORDERS"
TIME_TYPE = "SETTLE"


def build_query_payload(
    start_time: str,
    end_time: str,
    *,
    page: int = 0,
    size: int = 50,
) -> dict[str, Any]:
    """构造结算汇总查询 payload。"""

    return {
        "start_time": start_time,
        "end_time": end_time,
        "request_type": 1,
        "page": page,
        "size": size,
        "query_type": "SHOP_SETTLE_BILLS",
    }


def build_export_payload(start_time: str, end_time: str) -> dict[str, Any]:
    return {
        "start_time": start_time,
        "end_time": end_time,
        "download_type": DOWNLOAD_TYPE,
        "time_type": TIME_TYPE,
    }


def resolve_endpoint(args: argparse.Namespace) -> str:
    return resolve_profile_connection(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
        timeout=float(getattr(args, "profile_timeout", 30.0)),
        poll_interval=float(getattr(args, "profile_poll_interval", 0.5)),
    ).endpoint


async def _wait_business_dom(page: Any, url: str = SETTLEMENT_URL) -> None:
    try:
        selector = "body" if url == HISTORY_URL else ".auxo-tabs-nav"
        await page.wait_for_selector(selector, timeout=30_000)
    except Exception as exc:
        raise RuntimeError("抖店结算账单页面未加载业务 DOM") from exc


async def _goto_with_login(page: Any, url: str, shop: str, *, company: str) -> str:
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from scripts.auto_download.playwright.douyin_login import (
        DouyinCaptchaRequired,
        goto_with_douyin_login,
    )

    try:
        return await goto_with_douyin_login(
            page,
            url,
            shop,
            platform="抖音",
            company=company,
        )
    except DouyinCaptchaRequired as exc:
        raise NeedsHumanError("抖音页面出现人机验证，请人工完成后重新运行") from exc


async def _navigate(page: Any, args: argparse.Namespace, url: str) -> None:
    shop = str(getattr(args, "shop", "") or "").strip()
    company = str(getattr(args, "company", "") or "").strip()
    # 已认证会话在创建导出任务后直接切换历史页，避免登录恢复模块把
    # 当前状态误判成待选店铺；只有直接导航失败时才尝试完整恢复。
    if url == HISTORY_URL:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if "/login/" not in str(page.url or ""):
                await _wait_business_dom(page, url)
                return
        except Exception:
            pass

    try:
        await _goto_with_login(page, url, shop, company=company)
        await _wait_business_dom(page, url)
    except NeedsHumanError:
        raise
    except Exception as exc:
        if is_human_error_message(str(exc)) or not shop:
            raise NeedsHumanError(
                "抖音登录态或目标店铺需要人工处理；如需自动选店请补充 --shop/--company"
            ) from exc
        raise


try:
    from ReverseAPI.Formal_Script.douyin_webapi_common import PROJECT_ROOT as _PROJECT_ROOT
except ModuleNotFoundError:  # pragma: no cover - direct-file compatibility
    from douyin_webapi_common import PROJECT_ROOT as _PROJECT_ROOT  # type: ignore[no-redef]


class suppress_async_errors:
    """只用于关闭本次创建的页面，不影响主异常。"""

    def __enter__(self) -> "suppress_async_errors":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is not None


def safe_settlement_filename(start: date, end: date) -> str:
    return f"DY_settlement_{start.strftime('%Y%m%d')}_to_{end.strftime('%Y%m%d')}.csv"


async def run_async(
    args: argparse.Namespace,
    *,
    endpoint: str | None = None,
) -> Path | None:
    """执行一次结算报表下载；空账期返回 ``None``。"""

    from playwright.async_api import async_playwright

    start_date, end_date = resolve_date_range(args)
    start_time = format_api_time(start_date, end_of_day=False)
    end_time = format_api_time(end_date, end_of_day=True)
    actual_endpoint = endpoint or resolve_endpoint(args)
    timeout = float(args.timeout)
    poll_interval = float(args.poll_interval)

    log(REPORT_LABEL, "计划", f"Profile={args.profile}，时间={period_text(start_date, end_date)}")
    owned_page = False
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(actual_endpoint)
        if not browser.contexts:
            raise RuntimeError("CDP 浏览器中没有可用上下文")

        try:
            if str(_PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(_PROJECT_ROOT))
            from scripts.auto_download.playwright.douyin_login import (
                find_or_create_douyin_page,
            )

            page, owned_page = await find_or_create_douyin_page(browser)
            current_url = SETTLEMENT_URL

            async def navigate(url: str) -> None:
                nonlocal current_url
                await _navigate(page, args, url)
                current_url = url

            async def refresh() -> None:
                await navigate(current_url)

            await navigate(SETTLEMENT_URL)
            api = BrowserApiSession(page, refresh=refresh)

            shop_config = await api.get_json(
                SHOP_CONFIG_PATH,
                label="结算店铺配置",
                timeout=timeout,
            )
            shop_id = extract_shop_id(shop_config)
            if shop_id is None:
                log(REPORT_LABEL, "查询", "店铺配置未返回 ShopID，历史任务将继续按任务 ID校验")

            query_body = await api.post_json(
                QUERY_ITEM_PATH,
                build_query_payload(start_time, end_time),
                label="结算账单查询",
                timeout=timeout,
            )
            parse_data_rows(query_body, label="结算账单查询")
            total = read_total(query_body, label="结算账单查询")
            log(REPORT_LABEL, "查询", f"账单行数={total}")
            if total == 0:
                log(REPORT_LABEL, "完成", "指定账期无可下载结算账单")
                return None

            created_after = datetime.now(CN_TZ) - timedelta(seconds=5)
            create_body = await api.post_json(
                CREATE_DOWNLOAD_PATH,
                build_export_payload(start_time, end_time),
                label="结算账单导出",
                timeout=timeout,
            )
            download_id = extract_download_id(create_body, label="结算账单导出")
            log(REPORT_LABEL, "导出", "已创建结算账单任务，等待历史任务完成")

            await navigate(HISTORY_URL)
            task = await wait_for_history_task(
                api,
                label=REPORT_LABEL,
                start_time=start_time,
                end_time=end_time,
                download_type=DOWNLOAD_TYPE,
                time_type=TIME_TYPE,
                download_id=download_id,
                shop_id=shop_id,
                created_after=created_after,
                timeout=timeout,
                poll_interval=poll_interval,
            )
            task_id = extract_download_id(task, label="结算账单历史任务")
            url_body = await api.get_json(
                DOWNLOAD_URL_PATH,
                {"download_id": task_id},
                label="结算账单下载地址",
                timeout=timeout,
            )
            signed_url = extract_signed_url(url_body, label="结算账单下载地址")
            output = download_file(
                signed_url,
                Path(args.output_dir),
                safe_settlement_filename(start_date, end_date),
                referer=HISTORY_URL,
            )
            log(REPORT_LABEL, "完成", f"下载完成：{output}（{output.stat().st_size} bytes）")
            return output
        finally:
            if owned_page:
                with suppress_async_errors():
                    await page.close()  # type: ignore[has-type]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抖音结算账单 WebAPI 下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="可选：当前 Profile 的 wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="可选：当前 Profile 的 CDP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--date", help="单日或日期范围：YYYY-MM-DD[~YYYY-MM-DD]")
    parser.add_argument("--start", "--start-date", dest="start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", "--end-date", dest="end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--shop", default="", help="登录恢复时的目标店铺，可选")
    parser.add_argument("--company", default="", help="登录恢复时的公司，可选")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=180.0, help="导出任务最长等待秒数，默认 180")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="历史任务轮询秒数，默认 2")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--profile-timeout", type=float, default=30.0, help="Profile/CDP 获取最长等待秒数，默认 30")
    parser.add_argument("--profile-poll-interval", type=float, default=0.5, help="Profile/CDP 获取轮询秒数，默认 0.5")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.date and (args.start or args.end):
        parser.error("--date 不能与 --start/--end 同时使用")
    if bool(args.start) != bool(args.end):
        parser.error("--start 与 --end 必须同时提供")
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout 和 --poll-interval 必须大于 0")
    if args.profile_timeout <= 0 or args.profile_poll_interval <= 0:
        parser.error("--profile-timeout 和 --profile-poll-interval 必须大于 0")
    try:
        output = asyncio.run(run_async(args))
    except (ProfileResolutionError, NeedsHumanError) as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[DY][结算][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[DY][结算][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    if output is None:
        log(REPORT_LABEL, "完成", "任务完成：无数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
