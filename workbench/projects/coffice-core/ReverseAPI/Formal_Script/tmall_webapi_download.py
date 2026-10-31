#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天猫资金单、订单、推广费 WebAPI 统一入口。

天猫的订单/聚合资金使用普通店铺 Profile，支付宝资金/淘宝联盟/万相台
使用财务 Profile。两个 Profile 各自只解析一次，报表在各自 CDP 上下文
内串行执行，避免跨账号串 Cookie。
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

try:
    from .profile_cdp import ProfileResolutionError, resolve_profile_connection
    from .tmall_webapi_common import (
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_business_date,
        parse_date,
        parse_date_range,
        recent_month_range,
    )
    from . import tmall_fund_webapi_download as fund_download
    from . import tmall_order_webapi_download as order_download
    from . import tmall_promotion_webapi_download as promotion_download
except ImportError:  # 兼容直接执行 Formal_Script 下的文件
    from profile_cdp import ProfileResolutionError, resolve_profile_connection
    from tmall_webapi_common import (  # type: ignore[no-redef]
        ApiError,
        DEFAULT_OUTPUT_DIR,
        NeedsHumanError,
        default_business_date,
        parse_date,
        parse_date_range,
        recent_month_range,
    )
    import tmall_fund_webapi_download as fund_download  # type: ignore[no-redef]
    import tmall_order_webapi_download as order_download  # type: ignore[no-redef]
    import tmall_promotion_webapi_download as promotion_download  # type: ignore[no-redef]


REGULAR_PROFILE = "TMALL-天猫-MOCK旗舰店"
FINANCE_PROFILE = "TMALL-天猫-MOCK旗舰店-财务账号"
ORDER = "订单"
FUND = "资金单"
PROMOTION = "推广费"
ALL = "全部"


@dataclass(frozen=True)
class DownloadPlan:
    report_type: str
    start: date
    end: date
    period_text: str


def normalize_report_type(value: str) -> tuple[str, ...]:
    if value == ALL:
        return (ORDER, FUND, PROMOTION)
    if value in {ORDER, FUND, PROMOTION}:
        return (value,)
    raise ValueError(f"不支持的报表类型：{value}")


def build_download_plans(
    report_type: str | None,
    date_value: str | None,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    today: date | None = None,
) -> list[DownloadPlan]:
    selected = normalize_report_type(report_type or ALL)
    if date_value or start_date or end_date:
        start_text, end_text = parse_date_range(
            date_value,
            start_date=start_date,
            end_date=end_date,
            default="yesterday",
            today=today,
        )
        start, end = parse_date(start_text, option_name="开始日期"), parse_date(
            end_text, option_name="结束日期"
        )
        period = f"指定日期 {start_text} 至 {end_text}"
    else:
        current = today or date.today()
        start_text, end_text = recent_month_range(current)
        start, end = parse_date(start_text), parse_date(end_text)
        period = "默认近30天"
    plans: list[DownloadPlan] = []
    for kind in selected:
        if kind != ORDER and start != end:
            if date_value or start_date or end_date:
                raise ValueError(f"{kind} WebAPI 当前只支持单日，请传 YYYY-MM-DD")
            one = parse_date(default_business_date(today), option_name="昨天")
            plans.append(DownloadPlan(kind, one, one, "默认昨天"))
        else:
            plans.append(DownloadPlan(kind, start, end, period))
    return plans


def _profile_options(args: argparse.Namespace, prefix: str) -> dict[str, Any]:
    return {
        "profile_name": getattr(args, f"{prefix}_profile"),
        "ws_endpoint": getattr(args, f"{prefix}_ws_endpoint"),
        "debug_port": getattr(args, f"{prefix}_debug_port"),
        "mcp_url": args.mcp_url,
        "timeout": args.profile_timeout,
        "poll_interval": args.profile_poll_interval,
    }


async def run_async(
    args: argparse.Namespace,
    *,
    resolver: Callable[..., Any] = resolve_profile_connection,
) -> list[Path]:
    plans = build_download_plans(
        args.report_type,
        args.date,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    selected = {plan.report_type for plan in plans}
    need_regular = ORDER in selected or FUND in selected
    need_finance = FUND in selected or PROMOTION in selected
    connections: dict[str, Any] = {}

    def resolve_once(prefix: str) -> Any:
        profile_name = getattr(args, f"{prefix}_profile")
        if profile_name not in connections:
            connections[profile_name] = resolver(**_profile_options(args, prefix))
        return connections[profile_name]

    regular = resolve_once("order") if need_regular else None
    finance = resolve_once("finance") if need_finance else None
    output_dir = Path(args.output_dir)
    outputs: list[Path] = []

    for plan in plans:
        if plan.report_type == ORDER:
            result = await order_download.run_with_endpoint(
                regular.endpoint,
                start_date=plan.start.isoformat(),
                end_date=plan.end.isoformat(),
                output_dir=output_dir,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
                username=args.username,
                password_env=args.password_env,
            )
            if result is not None:
                outputs.append(result)
        elif plan.report_type == FUND:
            aggregate = await fund_download.run_with_endpoint(
                regular.endpoint,
                kind="聚合账户资金",
                target_date=plan.start.isoformat(),
                output_dir=output_dir,
                username=args.username,
                password_env=args.password_env,
            )
            if aggregate is not None:
                outputs.append(aggregate)
            alipay = await fund_download.run_with_endpoint(
                finance.endpoint,
                kind="支付宝账户资金",
                target_date=plan.start.isoformat(),
                output_dir=output_dir,
                username=args.username,
                password_env=args.password_env,
            )
            if alipay is not None:
                outputs.append(alipay)
        elif plan.report_type == PROMOTION:
            union = await promotion_download.run_with_endpoint(
                finance.endpoint,
                kind="淘宝联盟推广费",
                target_date=plan.start.isoformat(),
                output_dir=output_dir,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
            )
            if union is not None:
                outputs.append(union)
            wanxiang = await promotion_download.run_with_endpoint(
                finance.endpoint,
                kind="万相台推广费",
                target_date=plan.start.isoformat(),
                output_dir=output_dir,
            )
            if wanxiang is not None:
                outputs.append(wanxiang)
    return outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="天猫资金单、订单、推广费 WebAPI 统一下载")
    parser.add_argument("--report-type", choices=(ORDER, FUND, PROMOTION, ALL), default=ALL)
    parser.add_argument("--date", help="单日 YYYY-MM-DD；不传时订单默认近30天，其余默认昨天")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--profile", dest="order_profile", default=REGULAR_PROFILE)
    parser.add_argument("--finance-profile", default=FINANCE_PROFILE)
    parser.add_argument("--order-ws-endpoint")
    parser.add_argument("--finance-ws-endpoint")
    parser.add_argument("--order-debug-port", type=int)
    parser.add_argument("--finance-debug-port", type=int)
    parser.add_argument("--mcp-url", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    parser.add_argument("--username", default="MOCK旗舰店")
    parser.add_argument("--password-env", default="TMALL_LOGIN_PASSWORD")
    parser.add_argument("--profile-timeout", type=float, default=30.0)
    parser.add_argument("--profile-poll-interval", type=float, default=0.5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        outputs = asyncio.run(run_async(args))
        for output in outputs:
            print(f"output={output}")
        return 0
    except (NeedsHumanError, ProfileResolutionError) as exc:
        print(f"NEEDS_HUMAN: {exc}")
        return 2
    except KeyboardInterrupt:
        return 130
    except (ApiError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
