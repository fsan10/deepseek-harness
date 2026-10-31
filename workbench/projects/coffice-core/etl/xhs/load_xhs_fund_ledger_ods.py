#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入小红书资金账单明细 XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "动账时间",
    "业务单号",
    "动账场景",
    "动账方向",
    "动账金额",
    "动账账户",
    "动账后余额",
]


CONFIG = OdsLoadConfig(
    platform_code="xhs",
    platform_name="小红书",
    data_domain="fund",
    table_name="ods.ods_xhs_fund_ledger_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_name="资金账单明细",
)


if __name__ == "__main__":
    run_loader(CONFIG, "将小红书资金账单明细文件导入 PostgreSQL 的 ODS 表。")
