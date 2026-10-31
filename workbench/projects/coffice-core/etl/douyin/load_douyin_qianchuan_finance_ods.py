#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入抖音千川财务流水Excel到ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "日期",
    "余额总消耗(元)",
    "非赠款消耗(元)",
    "赠款消耗(元)",
    "消返红包消耗(元)",
    "立减红包消耗(元)",
    "共享钱包消耗(元)",
    "共享赠款消耗(元)",
    "总存入(元)",
    "总转入(元)",
    "总转出(元)",
    "总余额(元)",
    "赠款余额(元)",
    "非赠款余额(元)",
]


CONFIG = OdsLoadConfig(
    platform_code="douyin",
    platform_name="抖音",
    data_domain="ad",
    table_name="ods.ods_douyin_qianchuan_finance_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=3,
    csv_data_start_row_no=2,
    default_sheet_name="data",
    header_aliases={"共享赠款消耗": "共享赠款消耗(元)"},
)


if __name__ == "__main__":
    run_loader(CONFIG, "将抖音千川财务流水Excel导入PostgreSQL的ODS表。")
