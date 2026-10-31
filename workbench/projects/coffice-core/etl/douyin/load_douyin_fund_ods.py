#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入抖音资金流水 CSV 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "动账时间",
    "动帐流水号",
    "动账方向",
    "动账金额",
    "动账账户",
    "动账场景",
    "计费类型",
    "子订单号",
    "订单号",
    "售后编号",
    "下单时间",
    "商品ID",
    "商品名称",
    "达人ID",
    "达人名称",
    "订单类型",
    "订单实付应结",
    "运费实付",
    "实际平台补贴_运费",
    "实际平台补贴",
    "其他平台补贴",
    "以旧换新抵扣",
    "政府补贴平台垫资",
    "实际达人补贴",
    "实际抖音支付补贴",
    "实际抖音月付营销补贴",
    "银行补贴",
    "订单退款",
    "平台服务费",
    "佣金",
    "服务商佣金",
    "渠道分成",
    "招商服务费",
    "站外推广费",
    "其他分成",
    "是否免佣",
    "免佣金额",
    "商户主体名称",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="douyin",
    platform_name="抖音",
    data_domain="fund",
    table_name="ods.ods_douyin_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将抖音资金流水 CSV 导入 PostgreSQL 的 ODS 表。")
