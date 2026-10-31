#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入小红书结算收入/订单结算表到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "订单号",
    "售后单号",
    "下单时间",
    "完成时间",
    "结算时间",
    "交易类型",
    "动账金额",
    "结算账户",
    "计佣基数",
    "商品实付/实退",
    "运费实付/实退",
    "商家优惠总额",
    "平台优惠补贴",
    "政府券优惠补贴",
    "平台佣金",
    "买手佣金",
    "花呗分期手续费",
]


CONFIG = OdsLoadConfig(
    platform_code="xhs",
    platform_name="小红书",
    data_domain="settlement",
    table_name="ods.ods_xhs_settlement_income_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_sheet_index=1,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将小红书结算收入/订单结算工作表导入 PostgreSQL 的 ODS 表。")

