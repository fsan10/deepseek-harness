#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫结算收入表到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "账期",
    "账单大类",
    "业务大类",
    "业务小类",
    "订单号",
    "子订单号",
    "下单时间",
    "确认收货时间",
    "商品ID",
    "sku",
    "商品名称",
    "数量",
    "单价（元）",
    "订单实际金额（元）",
    "退款单号",
    "退款金额（元）",
    "收/付渠道",
    "业务流水号",
    "商户订单号",
    "打款时间",
    "打款更新时间",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="settlement",
    table_name="ods.ods_tmall_settlement_income_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_encoding_candidates=("gb2312", "gbk", "gb18030", "utf-8-sig", "utf-8"),
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫结算收入 CSV 导入 PostgreSQL 的 ODS 表。")

