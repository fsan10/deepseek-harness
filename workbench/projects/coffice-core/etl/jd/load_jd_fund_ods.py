#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入京东资金单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "商户订单号",
    "交易订单号",
    "支出类型",
    "交易金额",
    "交易类型",
    "入账时间",
    "资金动账备注",
]


CONFIG = OdsLoadConfig(
    platform_code="jd",
    platform_name="京东",
    data_domain="fund",
    table_name="ods.ods_jd_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将京东资金单文件导入 PostgreSQL 的 ODS 表。")
