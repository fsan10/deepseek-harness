#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入小红书其他服务款/结算支出表到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "订单号",
    "业务款项",
    "业务单号",
    "结算时间",
    "结算账户",
    "动账金额",
    "佣金金额",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="xhs",
    platform_name="小红书",
    data_domain="settlement",
    table_name="ods.ods_xhs_settlement_expense_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_index=2,
    optional_columns=("佣金金额",),
)


if __name__ == "__main__":
    run_loader(CONFIG, "将小红书其他服务款/结算支出工作表导入 PostgreSQL 的 ODS 表。")
