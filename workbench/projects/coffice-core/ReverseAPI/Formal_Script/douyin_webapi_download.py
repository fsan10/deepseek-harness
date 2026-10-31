#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抖音资金、结算 WebAPI 统一下载入口。

统一入口只解析一次 Cloak Login Profile，随后按“资金 → 结算”顺序复用同一
个实时 CDP endpoint。页面负责登录态和安全上下文；两个子模块负责各自的
查询、导出任务、历史状态和签名文件下载。脚本不会停止 Profile。

示例：

    .venv\\Scripts\\python.exe -m ReverseAPI.Formal_Script.douyin_webapi_download \
        --profile "DY-抖音-MOCK禧饮咖啡专卖店" --date 2026-09-10

只下载一种报表时增加 ``--report-type 资金`` 或 ``--report-type 结算``；不
指定时两种都会串行下载。
"""

from __future__ import annotations

import argparse
import asyncio
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
    from ReverseAPI.Formal_Script.douyin_webapi_common import (
        ApiError,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
        parse_date_range,
        period_text,
    )
    from ReverseAPI.Formal_Script import (
        douyin_fund_webapi_download as fund_download,
        douyin_settlement_webapi_download as settlement_download,
    )
except ModuleNotFoundError:  # 支持从 ReverseAPI/Formal_Script 直接运行
    from profile_cdp import (  # type: ignore[no-redef]
        ProfileConnection,
        ProfileResolutionError,
        resolve_profile_connection,
    )
    from douyin_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        CN_TZ,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        log,
        parse_date_range,
        period_text,
    )
    import douyin_fund_webapi_download as fund_download  # type: ignore[no-redef]
    import douyin_settlement_webapi_download as settlement_download  # type: ignore[no-redef]


FUND = "fund"
SETTLEMENT = "settlement"
ALL_REPORTS = (FUND, SETTLEMENT)

REPORT_LABELS = {FUND: "资金", SETTLEMENT: "结算"}
REPORT_TYPES = {
    "资金": FUND,
    "fund": FUND,
    "结算": SETTLEMENT,
    "settlement": SETTLEMENT,
    "全部": "all",
    "all": "all",
}


@dataclass(frozen=True)
class DownloadPlan:
    report_type: str
    start: date
    end: date
    requested: str | None
    period_text: str


def normalize_report_type(value: str | None) -> tuple[str, ...]:
    raw = str(value or "").strip()
    if not raw:
        return ALL_REPORTS
    normalized = REPORT_TYPES.get(raw)
    if normalized == "all":
        return ALL_REPORTS
    if normalized is None:
        raise ValueError("不支持的报表类型；可选：资金、结算、全部")
    return (normalized,)


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    today: date | None = None,
) -> list[DownloadPlan]:
    """构建资金、结算的有序日期计划；省略日期时使用中国时区昨天。"""

    selected = normalize_report_type(report_type)
    if date_value is None or not str(date_value).strip():
        current = today or datetime.now(CN_TZ).date()
        start = end = current - timedelta(days=1)
        requested = None
        reason = "默认昨天"
    else:
        start, end = parse_date_range(date_value)
        requested = str(date_value).strip()
        reason = "指定日期"

    return [
        DownloadPlan(
            report_type=report_name,
            start=start,
            end=end,
            requested=requested,
            period_text=f"{period_text(start, end)}（{reason}）",
        )
        for report_name in selected
    ]


def _child_args(
    plan: DownloadPlan,
    args: argparse.Namespace,
    connection: ProfileConnection,
) -> argparse.Namespace:
    """把统一计划转换成单报表模块的标准参数。"""

    return SimpleNamespace(
        profile=args.profile,
        ws_endpoint=connection.endpoint,
        debug_port=None,
        mcp_url=None,
        date=None,
        start=plan.start.isoformat(),
        end=plan.end.isoformat(),
        shop=str(getattr(args, "shop", "") or ""),
        company=str(getattr(args, "company", "") or ""),
        output_dir=args.output_dir,
        timeout=float(args.timeout),
        poll_interval=float(args.poll_interval),
        profile_timeout=float(getattr(args, "profile_timeout", 30.0)),
        profile_poll_interval=float(getattr(args, "profile_poll_interval", 0.5)),
    )


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., ProfileConnection] | None = None,
) -> list[Path]:
    """解析一次 Profile 后按固定顺序执行所选报表。"""

    plans = build_download_plans(args.report_type, args.date)
    resolve = resolver or resolve_profile_connection
    connection = resolve(
        profile_name=args.profile,
        ws_endpoint=getattr(args, "ws_endpoint", None),
        debug_port=getattr(args, "debug_port", None),
        mcp_url=getattr(args, "mcp_url", None),
        timeout=float(getattr(args, "profile_timeout", 30.0)),
        poll_interval=float(getattr(args, "profile_poll_interval", 0.5)),
    )
    log("统一", "计划", f"Profile={args.profile}，共 {len(plans)} 个报表")

    modules: dict[str, Any] = {
        FUND: fund_download,
        SETTLEMENT: settlement_download,
    }
    outputs: list[Path] = []
    for plan in plans:
        label = REPORT_LABELS[plan.report_type]
        log("统一", "计划", f"开始下载{label}：{plan.period_text}")
        child_args = _child_args(plan, args, connection)
        output = await modules[plan.report_type].run_async(child_args)
        if output is None:
            log("统一", "完成", f"{label}无数据：{plan.period_text}")
            continue
        outputs.append(Path(output))
        log("统一", "完成", f"{label}已生成：{Path(output)}")

    log("统一", "完成", f"{len(outputs)}/{len(plans)} 个报表已生成文件")
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抖音资金、结算 WebAPI 统一下载")
    endpoint = parser.add_mutually_exclusive_group()
    endpoint.add_argument("--ws-endpoint", "--cdp", dest="ws_endpoint", help="可选：当前 Profile 的 wsEndpoint")
    endpoint.add_argument("--debug-port", type=int, help="可选：当前 Profile 的 CDP 端口")
    parser.add_argument("--profile", required=True, help="Cloak Login Profile 完整名称")
    parser.add_argument("--date", help="单日或闭区间：YYYY-MM-DD[~YYYY-MM-DD]；默认昨天")
    parser.add_argument("--report-type", metavar="资金|结算|全部", help="报表类型；不填则依次下载资金和结算")
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
    except (ProfileResolutionError, NeedsHumanError) as exc:
        print(f"NEEDS_HUMAN: {exc}", file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        print("[DY][统一][失败] 用户中断脚本", file=sys.stderr, flush=True)
        return 130
    except (ApiError, RuntimeError, TimeoutError, ValueError, OSError) as exc:
        print(f"[DY][统一][失败] {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
