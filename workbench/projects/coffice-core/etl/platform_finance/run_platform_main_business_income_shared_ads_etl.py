#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立刷新并校验七平台共享主营收入 ADS。"""

try:
    from .run_douyin_ks_main_business_income_etl import build_parser, run_pipeline
except ImportError:  # 允许 Worker 以文件路径直接启动
    from run_douyin_ks_main_business_income_etl import build_parser, run_pipeline


def main() -> None:
    run_pipeline(build_parser().parse_args(), "shared")


if __name__ == "__main__":
    main()
