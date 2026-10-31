#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫支付宝账户资金明细 CSV 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "账务流水号",
    "业务流水号",
    "商户订单号",
    "商品名称",
    "发生时间",
    "对方账号",
    "收入金额（+元）",
    "支出金额（-元）",
    "账户余额（元）",
    "交易渠道",
    "业务类型",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="alipay_fund",
    table_name="ods.ods_tmall_alipay_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=5,
    data_start_row_no=6,
    stop_at_comment_rows=True,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫支付宝账户资金明细导入PostgreSQL ODS。")

