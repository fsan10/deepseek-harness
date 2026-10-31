#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫资金单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "日期",
    "明细笔数",
    "收入金额（元）",
    "收入笔数",
    "支出金额（元）",
    "支出笔数",
    "期末余额（元）",
]


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="fund",
    table_name="ods.ods_tmall_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫资金单文件导入 PostgreSQL 的 ODS 表。")
