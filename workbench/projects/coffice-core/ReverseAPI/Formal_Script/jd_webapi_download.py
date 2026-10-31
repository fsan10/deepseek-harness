#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东资金、结算、推广费 WebAPI 统一下载入口。

Profile/CDP 只解析一次，资金、结算、推广费按固定顺序串行执行并复用同一
实时 endpoint。推广费内部再按京东联盟、京东通顺序执行两个原始报表任务。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script.jd_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_yesterday,
        log,
        parse_date_range,
        recent_30_day_range,
    )
    from ReverseAPI.Formal_Script import (
        jd_fund_webapi_download as fund_download,
        jd_promotion_fee_webapi_download as promotion_download,
        jd_settlement_webapi_download as settlement_download,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from jd_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_yesterday,
        log,
        parse_date_range,
        recent_30_day_range,
    )
    import jd_fund_webapi_download as fund_download  # type: ignore[no-redef]
    import jd_promotion_fee_webapi_download as promotion_download  # type: ignore[no-redef]
    import jd_settlement_webapi_download as settlement_download  # type: ignore[no-redef]


PROFILE_NAME = "JD-京东-MOCK饮品旗舰店"
FUND = "资金"
SETTLEMENT = "结算"
PROMOTION = "推广费"
ALL_REPORTS = (FUND, SETTLEMENT, PROMOTION)
REPORT_TYPES = {FUND: FUND, SETTLEMENT: SETTLEMENT, PROMOTION: PROMOTION, "全部": "all"}


@dataclass(frozen=True)
class DownloadPlan:
    report_type: str
    date_text: str | None
    description: str


def normalize_report_type(value: str | None) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ALL_REPORTS
    mapped = REPORT_TYPES.get(raw)
    if mapped == "all":
        return ALL_REPORTS
    if mapped is None:
        raise ValueError("不支持的报表类型；只允许：资金、结算、推广费、全部")
    return (mapped,)


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    today: date | None = None,
) -> list[DownloadPlan]:
    selected = normalize_report_type(report_type)
    selection = parse_date_range(date_value, option="--date")
    current = today or date.today()
    plans: list[DownloadPlan] = []

    if FUND in selected:
        if selection is None:
            requested = current - timedelta(days=1)
            text = requested.isoformat()
            description = f"资金：默认昨天 {text}"
        else:
            text = (
                selection[0].isoformat()
                if selection[0] == selection[1]
                else f"{selection[0].isoformat()}~{selection[1].isoformat()}"
            )
            description = f"资金：指定日期 {text}"
        plans.append(DownloadPlan(FUND, text, description))

    if SETTLEMENT in selected:
        if selection is not None and selection[0] != selection[1]:
            raise ValueError("结算只支持单日 --date，不支持跨日范围")
        text = selection[0].isoformat() if selection is not None else None
        description = f"结算：指定业务日 {text}" if text else "结算：自动取最新可用业务日"
        plans.append(DownloadPlan(SETTLEMENT, text, description))

    if PROMOTION in selected:
        if selection is None:
            start, end = current - timedelta(days=29), current
            text = None
            description = f"推广费：默认近30天 {start.isoformat()}~{end.isoformat()}"
        else:
            text = (
                selection[0].isoformat()
                if selection[0] == selection[1]
                else f"{selection[0].isoformat()}~{selection[1].isoformat()}"
            )
            description = f"推广费：指定日期 {text}"
        plans.append(DownloadPlan(PROMOTION, text, description))
    return plans


def _child_args(plan: DownloadPlan, args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        profile=args.profile,
        ws_endpoint=None,
        debug_port=None,
        mcp_url=None,
        date=plan.date_text,
        output_dir=args.output_dir,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        profile_timeout=args.profile_timeout,
        profile_poll_interval=args.profile_poll_interval,
        report="all",
    )


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., ProfileConnection] | None = None,
) -> list[Path]:
    plans = build_download_plans(args.report_type, args.date)
    if not plans:
        raise ValueError("没有可执行的报表计划")
    log("统一", "计划", f"Profile={args.profile}")
    for plan in plans:
        log("统一", "计划", plan.description)
    log("统一", "计划", f"输出目录={Path(args.output_dir).expanduser().resolve()}")

    resolve = resolver or resolve_profile_connection
    connection = resolve(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=args.mcp_url,
        timeout=args.profile_timeout,
        poll_interval=args.profile_poll_interval,
    )
    source = "本次启动" if connection.started_by_this_run else "复用已运行实例"
    log("统一", "Profile", f"{source}，已取得登录态浏览器")

    outputs: list[Path] = []
    for plan in plans:
        child = _child_args(plan, args)
        log("统一", "开始", plan.description)
        if plan.report_type == FUND:
            output = await fund_download.run_with_endpoint(child, connection.endpoint)
            if output is not None:
                outputs.append(Path(output))
        elif plan.report_type == SETTLEMENT:
            output = await settlement_download.run_with_endpoint(child, connection.endpoint)
            if output is not None:
                outputs.append(Path(output))
        else:
            outputs.extend(
                await promotion_download.run_all_with_endpoint(child, connection.endpoint)
            )
        log("统一", "完成", plan.report_type)

    log("统一", "完成", f"本次生成 {len(outputs)} 个原始文件")
    for output in outputs:
        log("统一", "文件", str(output))
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="京东资金、结算、推广费 WebAPI 统一下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="可选：当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="可选：当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--report-type", metavar="资金|结算|推广费|全部", help="报表类型；不填则按资金、结算、推广费顺序全部下载")
    parser.add_argument("--date", help="指定单日或范围：YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD")
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
        asyncio.run(run_async(args))
    except (NeedsHumanError, ProfileResolutionError) as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[JD][统一][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[JD][统一][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
