#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键刷新天猫订单源影响的GSV、运营成交、达人业绩和达人佣金补零链路。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.influencer_commission.run_influencer_commission_etl import (  # noqa: E402
    run_pipeline as run_commission_pipeline,
)
from etl.influencer_performance.run_multiplatform_influencer_performance_etl import (  # noqa: E402
    print_result as print_influencer_result,
    run_pipeline as run_influencer_pipeline,
)
from etl.operating_sales.run_operating_sales_etl import (  # noqa: E402
    run_pipeline as run_operating_pipeline,
)
from etl.tmall.run_tmall_gsv_etl import run_pipeline as run_gsv_pipeline  # noqa: E402


DEFAULT_PRODUCT_MAPPING_FILE = (
    PROJECT_ROOT / "data" / "产品分类" / "产品编码.xlsx"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="刷新所有依赖天猫订单ODS的指标链路。"
    )
    parser.add_argument(
        "--product-mapping-file",
        default=str(DEFAULT_PRODUCT_MAPPING_FILE),
    )
    parser.add_argument("--skip-product-mapping-load", action="store_true")
    parser.add_argument(
        "--enforce-current-file-baseline",
        action="store_true",
        help="仅在天猫ODS只包含当前1098行销售明细时启用固定基准。",
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def common_args(args: argparse.Namespace) -> dict:
    return {
        "host": args.host,
        "port": args.port,
        "dbname": args.dbname,
        "user": args.user,
        "password": args.password,
    }


def main() -> None:
    args = build_parser().parse_args()
    common = common_args(args)

    print("=== 1/4 天猫GSV ===")
    run_gsv_pipeline(
        SimpleNamespace(
            **common,
            enforce_current_file_baseline=args.enforce_current_file_baseline,
        )
    )

    print("=== 2/4 七平台运营成交及产品占比 ===")
    run_operating_pipeline(
        SimpleNamespace(
            **common,
            product_mapping_file=args.product_mapping_file,
            skip_product_mapping_load=args.skip_product_mapping_load,
            enforce_current_baseline=args.enforce_current_file_baseline,
        )
    )

    print("=== 3/4 七平台达人业绩 ===")
    influencer_args = SimpleNamespace(**common)
    influencer_result = run_influencer_pipeline(influencer_args)
    print_influencer_result(influencer_args, influencer_result)

    print("=== 4/4 八平台达人佣金 ===")
    run_commission_pipeline(SimpleNamespace(**common))

    print("天猫订单相关指标链路全部刷新完成。")


if __name__ == "__main__":
    main()
