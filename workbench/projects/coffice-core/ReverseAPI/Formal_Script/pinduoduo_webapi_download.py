#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拼多多订单、结算、推广费 WebAPI 统一下载入口。

调用方只需要提供 Cloak Login Profile；日期和报表类型均可省略：

* 不传 ``--report-type`` 时依次下载订单、结算、推广费；
* 订单默认下载最近 30 个自然日；
* 结算和推广费默认下载昨天；
* ``--date`` 支持 ``YYYY-MM-DD`` 或
  ``YYYY-MM-DD~YYYY-MM-DD``，传入后应用到选中的报表。

Profile/CDP 只解析一次，三个报表按顺序复用同一个实时 Profile。浏览器页面
负责真实入口、登录态和动态请求上下文，查询、导出、轮询和文件下载由各自
WebAPI 模块完成。拼多多没有资金报表，传入资金类型会明确报错。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import requests


try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script import (
        pdd_order_export_download as order_download,
        pdd_promotion_fee_webapi_download as promotion_download,
        pdd_settlement_webapi_download as settlement_download,
    )
    from ReverseAPI.Formal_Script.pdd_webapi_common import (
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    import pdd_order_export_download as order_download  # type: ignore[no-redef]
    import pdd_promotion_fee_webapi_download as promotion_download  # type: ignore[no-redef]
    import pdd_settlement_webapi_download as settlement_download  # type: ignore[no-redef]
    from pdd_webapi_common import (  # type: ignore[no-redef]
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
    )


CN_TZ = timezone(timedelta(hours=8))

ORDER = "order"
SETTLEMENT = "settlement"
PROMOTION = "promotion"
ALL_REPORTS = (ORDER, SETTLEMENT, PROMOTION)

REPORT_LABELS = {
    ORDER: "订单",
    SETTLEMENT: "结算",
    PROMOTION: "推广费",
}
REPORT_TYPES = {
    "订单": ORDER,
    "结算": SETTLEMENT,
    "推广费": PROMOTION,
    "全部": "all",
}
CANONICAL_REPORT_TYPES = tuple(REPORT_TYPES)
DATE_RANGE_SEPARATOR = re.compile(
    r"\s*(?:~|至|\.\.|,|，|:|\s+to\s+)\s*", re.IGNORECASE
)


@dataclass(frozen=True)
class DateSelection:
    start: date | None = None
    end: date | None = None


@dataclass(frozen=True)
class DownloadPlan:
    report_type: str
    start: date
    end: date
    period_text: str


def normalize_report_type(value: str | None) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ALL_REPORTS
    if raw == "资金":
        raise ValueError("拼多多没有资金报表，请选择订单、结算、推广费或全部")
    report_type = REPORT_TYPES.get(raw)
    if report_type == "all":
        return ALL_REPORTS
    if report_type is None:
        choices = "、".join(CANONICAL_REPORT_TYPES)
        raise ValueError(f"不支持的报表类型：{value!r}；可选：{choices}")
    return (report_type,)


def parse_date_selection(value: str | None) -> DateSelection:
    if value is None or not value.strip():
        return DateSelection()

    raw = value.strip()
    parts = DATE_RANGE_SEPARATOR.split(raw, maxsplit=1)
    if len(parts) == 1:
        try:
            parsed = date.fromisoformat(raw.replace("/", "-"))
        except ValueError as exc:
            raise ValueError(
                f"--date 必须使用 YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD：{value!r}"
            ) from exc
        return DateSelection(start=parsed, end=parsed)

    if any(not part.strip() for part in parts):
        raise ValueError(
            "--date 日期范围必须使用 YYYY-MM-DD~YYYY-MM-DD（或逗号、至、..、to）"
        )
    try:
        start = date.fromisoformat(parts[0].strip().replace("/", "-"))
        end = date.fromisoformat(parts[1].strip().replace("/", "-"))
    except ValueError as exc:
        raise ValueError(f"--date 日期格式错误：{value!r}") from exc
    if start > end:
        raise ValueError("--date 开始日期不能晚于结束日期")
    return DateSelection(start=start, end=end)


def _current_date(today: date | None) -> date:
    return today or datetime.now(CN_TZ).date()


def _period_text(start: date, end: date, reason: str) -> str:
    return (
        f"{start.isoformat()} 00:00:00 ~ {end.isoformat()} 23:59:59"
        f"（{reason}）"
    )


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    today: date | None = None,
) -> list[DownloadPlan]:
    """生成按订单、结算、推广费顺序执行的日期计划。"""

    selected = normalize_report_type(report_type)
    selection = parse_date_selection(date_value)
    current = _current_date(today)

    plans: list[DownloadPlan] = []
    for name in ALL_REPORTS:
        if name not in selected:
            continue
        if selection.start is not None:
            start = selection.start
            end = selection.end or selection.start
            reason = "指定日期"
        elif name == ORDER:
            start = current - timedelta(days=29)
            end = current
            reason = "默认近30天"
        else:
            start = end = current - timedelta(days=1)
            reason = "默认昨天"
        plans.append(
            DownloadPlan(
                report_type=name,
                start=start,
                end=end,
                period_text=_period_text(start, end, reason),
            )
        )
    return plans


def _child_args(
    plan: DownloadPlan,
    args: argparse.Namespace,
    connection: ProfileConnection,
) -> SimpleNamespace:
    common: dict[str, Any] = {
        "profile": args.profile,
        "ws_endpoint": connection.endpoint,
        "debug_port": None,
        "mcp_url": None,
        "output_dir": args.output_dir,
        "proxy": args.proxy,
        "timeout": args.timeout,
        "poll_interval": args.poll_interval,
        "date_source": (
            "指定日期"
            if args.date
            else "默认近30天" if plan.report_type == ORDER else "默认昨天"
        ),
    }
    if plan.report_type == ORDER:
        common.update(
            {
                "start": plan.start.isoformat(),
                "end": plan.end.isoformat(),
                "template": args.template,
                "manual_trigger": args.manual_trigger,
            }
        )
    elif plan.report_type == SETTLEMENT:
        common.update(
            {
                "start": plan.start.isoformat(),
                "end": plan.end.isoformat(),
            }
        )
    else:
        common.update(
            {
                "date_mode": "default",
                "start_date": plan.start.isoformat(),
                "end_date": plan.end.isoformat(),
            }
        )
    return SimpleNamespace(**common)


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., ProfileConnection] | None = None,
) -> list[Path]:
    plans = build_download_plans(args.report_type, args.date)
    log("统一", "计划", f"Profile={args.profile}")
    for plan in plans:
        log("统一", "计划", f"{REPORT_LABELS[plan.report_type]}：{plan.period_text}")
    log("统一", "计划", f"输出目录={Path(args.output_dir).expanduser().resolve()}")

    resolve = resolver or resolve_profile_connection
    connection = resolve(
        profile_name=args.profile,
        ws_endpoint=args.ws_endpoint,
        debug_port=args.debug_port,
        mcp_url=args.mcp_url,
        timeout=args.profile_timeout,
        poll_interval=args.profile_poll_interval,
    )
    if connection.profile_id:
        source = "本次启动" if connection.started_by_this_run else "复用已运行实例"
        log("统一", "Profile", f"{source}，已取得登录态浏览器")
    else:
        log("统一", "Profile", "使用显式 CDP 参数")

    modules = {
        ORDER: order_download,
        SETTLEMENT: settlement_download,
        PROMOTION: promotion_download,
    }
    outputs: list[Path] = []
    for plan in plans:
        label = REPORT_LABELS[plan.report_type]
        log("统一", "计划", f"开始下载{label}：{plan.period_text}")
        child_args = _child_args(plan, args, connection)
        if plan.report_type == ORDER:
            output = await asyncio.to_thread(modules[plan.report_type].run, child_args)
        elif plan.report_type == SETTLEMENT:
            output = await asyncio.to_thread(modules[plan.report_type].run, child_args)
        else:
            output = await modules[plan.report_type].run_async(child_args)
        if output is None:
            log("统一", "完成", f"{label}无数据：{plan.period_text}")
            continue
        output_path = Path(output)
        outputs.append(output_path)
        log("统一", "完成", f"{label}下载完成：{output_path}")

    log("统一", "完成", f"{len(outputs)}/{len(plans)} 个报表已生成文件")
    for output in outputs:
        log("统一", "完成", f"文件={output}")
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="拼多多订单、结算、推广费 WebAPI 统一下载"
    )
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument(
        "--ws-endpoint",
        "--cdp",
        dest="ws_endpoint",
        help="可选：显式传入当前 Profile 的 wsEndpoint",
    )
    endpoint.add_argument(
        "--debug-port",
        type=int,
        help="可选：显式传入当前 Profile 的 CDP 端口",
    )
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument(
        "--date",
        help="日期：YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD；不填按各报表默认日期",
    )
    parser.add_argument(
        "--report-type",
        dest="report_type",
        metavar="订单|结算|推广费|全部",
        help="报表类型：订单、结算、推广费或全部；不填则全部下载",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--timeout", type=int, default=240, help="单个报表最长等待秒数，默认 240")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="任务轮询间隔秒数，默认 2")
    parser.add_argument("--proxy", help="下载文件时使用的 HTTP 代理")
    parser.add_argument("--template", default="对账报表", help="订单导出模板，默认：对账报表")
    parser.add_argument(
        "--manual-trigger",
        action="store_true",
        help="订单导出时不自动点击按钮，改由用户在浏览器中手动触发",
    )
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument("--profile-timeout", type=float, default=30.0, help="Profile/CDP 发现最长等待秒数，默认 30")
    parser.add_argument("--profile-poll-interval", type=float, default=0.5, help="Profile/CDP 发现轮询秒数，默认 0.5")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.profile.strip():
        parser.error("--profile 不能为空")
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout 和 --poll-interval 必须大于 0")
    if args.profile_timeout <= 0 or args.profile_poll_interval <= 0:
        parser.error("--profile-timeout 和 --profile-poll-interval 必须大于 0")
    if args.debug_port is not None and not 1 <= args.debug_port <= 65535:
        parser.error("--debug-port 必须在 1 到 65535 之间")
    try:
        asyncio.run(run_async(args))
    except ProfileResolutionError as exc:
        print(f"NEEDS_HUMAN: Profile/CDP 自动获取失败：{exc}", file=sys.stderr, flush=True)
        return 2
    except NeedsHumanError as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[PDD][统一][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (RuntimeError, TimeoutError, ValueError, OSError, requests.RequestException) as exc:
        print(f"[PDD][统一][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
