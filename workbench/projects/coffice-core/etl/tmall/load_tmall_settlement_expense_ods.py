#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫结算支出/服务费表到 ODS 字段超集表。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "账期",
    "资金方向",
    "账单大类",
    "业务大类",
    "业务小类",
    "支出项目",
    "扣费日期",
    "扣费交易金额",
    "扣费金额",
    "佣金率",
    "订单日期",
    "交易主订单号",
    "交易子订单号",
    "商品名称",
    "数量",
    "单价",
    "支付宝商户订单号(新增)",
    "报名id(新增)",
    "收/付渠道描述",
    "扣费金额(元)",
    "退款金额(元)",
    "确认收货日期",
    "交易主单号",
    "订单金额",
    "扣费基数",
    "本月付款",
    "费率",
    "支付渠道商户订单号",
    "支付宝商户订单号",
    "报名id",
    "退款金额（元）",
    "扣款交易金额",
    "扣费交易金额（元）",
    "支出金额（元）",
    "扣费金额（元）",
    "单价（元）(新增)",
    "数量(新增)",
    "商品名称(新增)",
    "交易主订单号_2",
    "订单日期_2",
    "佣金率_2",
    "交易子订单号_2",
]


REQUIRED_COLUMNS = (
    "账期",
    "资金方向",
    "账单大类",
    "业务大类",
    "业务小类",
    "支出项目",
)


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="settlement",
    table_name="ods.ods_tmall_settlement_expense_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_encoding_candidates=("gb2312", "gbk", "gb18030", "utf-8-sig", "utf-8"),
    optional_columns=tuple(column for column in EXPECTED_COLUMNS if column not in REQUIRED_COLUMNS),
    strict_header=False,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫结算支出/服务费 CSV 导入 PostgreSQL 的 ODS 表。")

