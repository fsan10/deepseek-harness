#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫万相台推广费资金流水到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="ad",
    table_name="ods.ods_tmall_wanxiangtai_promotion_expense_raw",
    expected_columns=[
        "记账时间",
        "交易日期",
        "收支类型",
        "交易类型",
        "操作金额(元)",
        "操作后余额(元)",
        "备注",
    ],
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫万相台推广费资金流水导入 PostgreSQL ODS。")
