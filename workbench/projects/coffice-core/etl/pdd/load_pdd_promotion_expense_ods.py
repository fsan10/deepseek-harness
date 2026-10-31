#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入拼多多推广费资金流水到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


CONFIG = OdsLoadConfig(
    platform_code="pdd",
    platform_name="拼多多",
    data_domain="ad",
    table_name="ods.ods_pdd_promotion_expense_raw",
    expected_columns=[
        "时间",
        "资金类型",
        "流水类型",
        "店铺名称",
        "交易金额",
        "余额",
        "交易摘要",
    ],
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_name="Sheet0",
)


if __name__ == "__main__":
    run_loader(CONFIG, "将拼多多推广费资金流水导入 PostgreSQL ODS。")
