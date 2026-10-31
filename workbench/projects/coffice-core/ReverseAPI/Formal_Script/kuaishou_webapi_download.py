#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快手资金、结算单 WebAPI 统一下载入口。

Profile/CDP 只解析一次，资金和结算单按固定顺序串行执行并复用同一实时
浏览器 endpoint。单项脚本仍可独立运行，统一入口只负责计划编排。
"""

from __future__ import annotations

import argparse
import asyncio
import re
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
    from ReverseAPI.Formal_Script.kuaishou_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_yesterday,
        log,
        parse_date_range,
    )
    from ReverseAPI.Formal_Script import (
        kuaishou_fund_webapi_download as fund_download,
        kuaishou_settlement_webapi_download as settlement_download,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from kuaishou_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_yesterday,
        log,
        parse_date_range,
    )
    import kuaishou_fund_webapi_download as fund_download  # type: ignore[no-redef]
    import kuaishou_settlement_webapi_download as settlement_download  # type: ignore[no-redef]


FUND = "资金"
SETTLEMENT = "结算"
ALL_REPORTS = (FUND, SETTLEMENT)
REPORT_TYPES = {FUND: FUND, SETTLEMENT: SETTLEMENT, "全部": "all"}


@dataclass(frozen=True)
class DownloadPlan:
    report_type: str
    date_text: str | None
    mode: str = "day"
    description: str = ""


def normalize_report_type(value: str | None) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ALL_REPORTS
    mapped = REPORT_TYPES.get(raw)
    if mapped == "all":
        return ALL_REPORTS
    if mapped is None:
        raise ValueError("不支持的报表类型；只允许：资金、结算、全部")
    return (mapped,)


def _month_value(value: str | None) -> date | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip().replace("/", "-")
    if not re.fullmatch(r"\d{4}-\d{2}", raw):
        return None
    try:
        year, month = (int(item) for item in raw.split("-"))
        return date(year, month, 1)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"--date 月份无效：{value!r}") from exc


def _date_text(selection: tuple[date, date] | None) -> str | None:
    if selection is None:
        return None
    if selection[0] == selection[1]:
        return selection[0].isoformat()
    return f"{selection[0].isoformat()}~{selection[1].isoformat()}"


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    mode: str = "day",
    today: date | None = None,
) -> list[DownloadPlan]:
    selected = normalize_report_type(report_type)
    if mode not in {"day", "month"}:
        raise ValueError("--mode 只允许 day 或 month")
    month = _month_value(date_value)
    selection = None if month is not None else parse_date_range(date_value, option="--date")
    current = today or date.today()
    plans: list[DownloadPlan] = []

    if FUND in selected:
        if month is not None:
            if mode != "month":
                raise ValueError("--date 使用 YYYY-MM 时，资金 --mode 必须为 month")
            plans.append(DownloadPlan(FUND, month.strftime("%Y-%m"), "month", f"资金：指定月份 {month:%Y-%m}"))
        elif selection is None:
            default_date = current - timedelta(days=1)
            if mode == "month":
                plans.append(DownloadPlan(FUND, None, "month", "资金：自动取最新月账单"))
            else:
                plans.append(DownloadPlan(FUND, default_date.isoformat(), "day", f"资金：默认昨天 {default_date.isoformat()}"))
        else:
            if selection[0] != selection[1]:
                raise ValueError("资金只支持单日或单月，不支持日期范围")
            if mode == "month":
                raise ValueError("资金月账单 --date 必须使用 YYYY-MM 格式")
            plans.append(DownloadPlan(FUND, selection[0].isoformat(), "day", f"资金：指定日期 {selection[0].isoformat()}"))

    if SETTLEMENT in selected:
        if month is not None:
            raise ValueError("结算单只支持 YYYY-MM-DD 日期或日期范围")
        text = _date_text(selection)
        description = f"结算：指定范围 {text}" if text else "结算：默认昨天"
        plans.append(DownloadPlan(SETTLEMENT, text, "day", description))

    return plans


def _child_args(plan: DownloadPlan, args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        profile=args.profile,
        ws_endpoint=None,
        debug_port=None,
        mcp_url=None,
        date=plan.date_text,
        mode=plan.mode,
        sub_mch_id=getattr(args, "sub_mch_id", None),
        output_dir=args.output_dir,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        profile_timeout=args.profile_timeout,
        profile_poll_interval=args.profile_poll_interval,
    )


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., ProfileConnection] | None = None,
) -> list[Path]:
    plans = build_download_plans(args.report_type, args.date, mode=args.mode)
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
        else:
            output = await settlement_download.run_with_endpoint(child, connection.endpoint)
        if output is not None:
            outputs.append(Path(output))
        log("统一", "完成", plan.report_type)

    log("统一", "完成", f"本次生成 {len(outputs)} 个原始文件")
    for output in outputs:
        log("统一", "文件", str(output))
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="快手资金、结算单 WebAPI 统一下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="可选：当前 Profile 的 browser CDP wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="可选：当前 Profile 的 CDP HTTP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--report-type", metavar="资金|结算|全部", help="报表类型；不填则按资金、结算顺序全部下载")
    parser.add_argument("--mode", choices=("day", "month"), default="day", help="资金账单模式，默认 day")
    parser.add_argument("--date", help="资金日账单 YYYY-MM-DD、月账单 YYYY-MM，或结算日期范围 YYYY-MM-DD~YYYY-MM-DD")
    parser.add_argument("--sub-mch-id", help="可选：资金账户二级商户号")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--timeout", type=float, default=600.0, help="接口和导出任务最长等待秒数，默认 600")
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
        asyncio.run(run_async(args))
    except (NeedsHumanError, ProfileResolutionError) as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[快手][统一][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[快手][统一][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
