#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书订单、资金、结算 WebAPI 统一下载入口。

调用方只需要提供 Cloak Login Profile；日期和报表类型均可省略：

* 不传 ``--report-type`` 时依次下载订单、资金、结算；
* 订单默认下载最近 30 个自然日；
* 资金和结算默认下载昨天的日账单；
* ``--date`` 支持 ``YYYY-MM-DD``，订单还支持
  ``YYYY-MM-DD~YYYY-MM-DD``；资金/结算使用 ``YYYY-MM`` 时下载月度汇总单。

Profile/CDP 只解析一次，三个报表按顺序复用同一个实时 Profile。浏览器页面
负责真实入口、登录态和动态请求上下文，查询、导出、轮询和文件下载由各自
WebAPI 模块完成。脚本不会关闭用户原有的 Profile。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


try:
    from ReverseAPI.Formal_Script.profile_cdp import (
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from ReverseAPI.Formal_Script.xhs_webapi_common import (
        ApiError,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
        parse_iso_date,
    )
    from ReverseAPI.Formal_Script import (
        xiaohongshu_fund_webapi_download as fund_download,
        xiaohongshu_order_webapi_download as order_download,
        xiaohongshu_settlement_webapi_download as settlement_download,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行文件
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from xhs_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
        parse_iso_date,
    )
    import xiaohongshu_fund_webapi_download as fund_download  # type: ignore[no-redef]
    import xiaohongshu_order_webapi_download as order_download  # type: ignore[no-redef]
    import xiaohongshu_settlement_webapi_download as settlement_download  # type: ignore[no-redef]


ORDER = "order"
FUND = "fund"
SETTLEMENT = "settlement"
ALL_REPORTS = (ORDER, FUND, SETTLEMENT)

REPORT_LABELS = {
    ORDER: "订单",
    FUND: "资金",
    SETTLEMENT: "结算",
}
REPORT_TYPES = {
    "订单": ORDER,
    "资金": FUND,
    "结算": SETTLEMENT,
    "全部": "all",
}
CANONICAL_REPORT_TYPES = tuple(REPORT_TYPES)
MONTH_PATTERN = re.compile(r"20\d{2}[-/]?\d{1,2}")
DATE_RANGE_SEPARATOR = re.compile(r"\s*(?:~|至|\.\.|,|，|:|\s+to\s+)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class DateSelection:
    """解析后的统一日期参数。"""

    start: date | None = None
    end: date | None = None
    month: date | None = None

    @property
    def is_month(self) -> bool:
        return self.month is not None


@dataclass(frozen=True)
class DownloadPlan:
    """一个报表实际要传给底层 WebAPI 的日期计划。"""

    report_type: str
    start: date
    end: date
    mode: str
    requested: str | None
    period_text: str


def normalize_report_type(value: str | None) -> tuple[str, ...]:
    """把中文报表类型统一为底层模块使用的名称。"""

    raw = str(value or "").strip()
    if not raw:
        return ALL_REPORTS
    report_type = REPORT_TYPES.get(raw)
    if report_type == "all":
        return ALL_REPORTS
    if report_type is None:
        choices = "、".join(CANONICAL_REPORT_TYPES)
        raise ValueError(f"不支持的报表类型：{value!r}；可选：{choices}")
    return (report_type,)


def _parse_month(value: str) -> date:
    normalized = value.strip().replace("/", "-")
    match = re.fullmatch(r"(20\d{2})-?(\d{1,2})", normalized)
    if not match or not 1 <= int(match.group(2)) <= 12:
        raise ValueError(f"--date 月份必须使用 YYYY-MM 或 YYYYMM：{value!r}")
    return date(int(match.group(1)), int(match.group(2)), 1)


def parse_date_selection(value: str | None) -> DateSelection:
    """解析单日、订单日期范围或资金/结算月份。"""

    if value is None or not value.strip():
        return DateSelection()
    raw = value.strip()
    if MONTH_PATTERN.fullmatch(raw):
        return DateSelection(month=_parse_month(raw))

    parts = DATE_RANGE_SEPARATOR.split(raw, maxsplit=1)
    if len(parts) == 1:
        parsed = parse_iso_date(raw.replace("/", "-"), option="--date")
        return DateSelection(start=parsed, end=parsed)
    if any(not part.strip() for part in parts):
        raise ValueError(
            "--date 日期范围必须使用 YYYY-MM-DD~YYYY-MM-DD（或逗号、至、..、to）"
        )
    start = parse_iso_date(parts[0].replace("/", "-"), option="--date 开始日期")
    end = parse_iso_date(parts[1].replace("/", "-"), option="--date 结束日期")
    if start > end:
        raise ValueError("--date 开始日期不能晚于结束日期")
    return DateSelection(start=start, end=end)


def _current_date(today: date | None) -> date:
    return today or datetime.now(CN_TZ).date()


def _period_text(start: date, end: date, *, mode: str, reason: str) -> str:
    if mode == "month":
        actual = start.strftime("%Y-%m")
    else:
        actual = (
            f"{start.isoformat()} 00:00:00 ~ "
            f"{end.isoformat()} 23:59:59"
        )
    return f"{actual}（{reason}）" if reason else f"{actual}（指定日期）"


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    today: date | None = None,
) -> list[DownloadPlan]:
    """根据统一入口参数生成有序下载计划。

    ``today`` 只用于测试和可重复预览；实际运行默认使用中国时区当天日期。
    """

    selected = normalize_report_type(report_type)
    selection = parse_date_selection(date_value)
    current = _current_date(today)

    if selection.is_month and ORDER in selected:
        raise ValueError("订单只支持 YYYY-MM-DD 或日期范围，不能使用 YYYY-MM 月份")
    if (
        selection.start is not None
        and selection.end is not None
        and selection.start != selection.end
        and any(item in selected for item in (FUND, SETTLEMENT))
    ):
        raise ValueError("资金和结算只支持单日或单月，不能使用跨日范围")

    plans: list[DownloadPlan] = []
    if ORDER in selected:
        if selection.start is None:
            start, end = current - timedelta(days=29), current
            reason = "默认近30天"
        else:
            start, end = selection.start, selection.end or selection.start
            reason = "指定日期"
        plans.append(
            DownloadPlan(
                report_type=ORDER,
                start=start,
                end=end,
                mode="range",
                requested=None,
                period_text=_period_text(start, end, mode="day", reason=reason),
            )
        )

    for report_type_name in (FUND, SETTLEMENT):
        if report_type_name not in selected:
            continue
        if selection.is_month:
            assert selection.month is not None
            month = selection.month
            plans.append(
                DownloadPlan(
                    report_type=report_type_name,
                    start=month,
                    end=month,
                    mode="month",
                    requested=month.strftime("%Y-%m"),
                    period_text=_period_text(
                        month, month, mode="month", reason="指定月份"
                    ),
                )
            )
            continue

        requested = selection.start or (current - timedelta(days=1))
        reason = "指定日期" if selection.start is not None else "默认昨天"
        plans.append(
            DownloadPlan(
                report_type=report_type_name,
                start=requested,
                end=requested,
                mode="day",
                requested=requested.isoformat(),
                period_text=_period_text(
                    requested, requested, mode="day", reason=reason
                ),
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
    }
    if plan.report_type == ORDER:
        common.update(
            {
                "start_date": plan.start.isoformat(),
                "end_date": plan.end.isoformat(),
                "timeout": args.timeout,
                "poll_interval": args.poll_interval,
            }
        )
    else:
        common.update({"mode": plan.mode, "date": plan.requested})
    return SimpleNamespace(**common)


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., ProfileConnection] | None = None,
) -> list[Path]:
    """解析一次 Profile，并串行执行选中的报表计划。"""

    plans = build_download_plans(args.report_type, args.date)
    log("统一", "计划", f"Profile={args.profile}")
    for plan in plans:
        log("统一", "计划", f"{REPORT_LABELS[plan.report_type]}：{plan.period_text}")
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
    if connection.profile_id:
        source = "本次启动" if connection.started_by_this_run else "复用已运行实例"
        log("统一", "Profile", f"{source}，已取得登录态浏览器")
    else:
        log("统一", "Profile", "使用显式 CDP 参数")

    outputs: list[Path] = []
    modules = {
        ORDER: order_download,
        FUND: fund_download,
        SETTLEMENT: settlement_download,
    }
    for plan in plans:
        label = REPORT_LABELS[plan.report_type]
        log("统一", "计划", f"开始下载{label}：{plan.period_text}")
        output = await modules[plan.report_type].run_async(
            _child_args(plan, args, connection)
        )
        if output is not None:
            outputs.append(Path(output))
        else:
            log("统一", "完成", f"{label}无数据：{plan.period_text}")

    log("统一", "完成", f"{len(outputs)}/{len(plans)} 个报表已生成文件")
    for output in outputs:
        log("统一", "完成", f"文件={output}")
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="小红书订单、资金、结算 WebAPI 统一下载"
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
        help=(
            "日期：订单使用 YYYY-MM-DD 或 YYYY-MM-DD~YYYY-MM-DD；"
            "资金/结算使用 YYYY-MM-DD 或 YYYY-MM 月份"
        ),
    )
    parser.add_argument(
        "--report-type",
        dest="report_type",
        metavar="订单|资金|结算|全部",
        help="报表类型：订单、资金、结算或全部；不填则全部下载",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"下载目录，默认：{DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument("--timeout", type=float, default=240.0, help="订单导出最长等待秒数，默认 240")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="订单导出状态轮询秒数，默认 2")
    parser.add_argument("--mcp-url", help="Cloak Login MCP 地址，默认读取 CLOAK_MCP_URL")
    parser.add_argument(
        "--profile-timeout",
        type=float,
        default=30.0,
        help="启动/发现 Profile 的最长等待秒数，默认 30",
    )
    parser.add_argument(
        "--profile-poll-interval",
        type=float,
        default=0.5,
        help="发现 Profile CDP 的轮询秒数，默认 0.5",
    )
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
        print("[XHS][统一][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[XHS][统一][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
