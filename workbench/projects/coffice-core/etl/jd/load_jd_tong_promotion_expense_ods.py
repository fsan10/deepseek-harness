#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入京东通推广费流水到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


CONFIG = OdsLoadConfig(
    platform_code="jd",
    platform_name="京东",
    data_domain="ad",
    table_name="ods.ods_jd_tong_promotion_expense_raw",
    expected_columns=[
        "流水单号",
        "投放账户名称",
        "投放账户ID",
        "投放日期",
        "交易类型",
        "支出",
        "秒送门店ID",
        "结算时间",
        "结余",
        "开票方式",
    ],
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_name="sheet1",
)


if __name__ == "__main__":
    run_loader(CONFIG, "将京东通推广费流水导入 PostgreSQL ODS。")
