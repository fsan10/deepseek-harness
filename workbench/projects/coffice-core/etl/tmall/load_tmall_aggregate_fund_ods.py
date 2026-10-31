#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫聚合账户资金明细 XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "商家昵称",
    "入帐日期",
    "入帐时间",
    "支付流水号",
    "主订单id",
    "子订单id",
    "入帐类型",
    "收入金额(元)",
    "支出金额(元)",
    "业务描述",
    "备注",
    "收/付渠道",
    "数据创建时间",
    "数据修改时间",
]


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="aggregate_fund",
    table_name="ods.ods_tmall_aggregate_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_name="sheet1",
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫聚合账户资金明细导入PostgreSQL ODS。")

