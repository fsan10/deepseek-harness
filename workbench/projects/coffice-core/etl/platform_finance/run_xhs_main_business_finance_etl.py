#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立刷新小红书主营财务 ODS -> DWD -> DWS -> 费用ADS。"""

try:
    from .run_pdd_wechat_xhs_main_business_finance_etl import parser as build_parser, run_pipeline
except ImportError:  # 允许 Worker 以文件路径直接启动
    from run_pdd_wechat_xhs_main_business_finance_etl import parser as build_parser
    from run_pdd_wechat_xhs_main_business_finance_etl import run_pipeline


def main() -> None:
    run_pipeline(
        build_parser("刷新小红书主营业务收入与平台费用。").parse_args(),
        "xhs",
    )


if __name__ == "__main__":
    main()
