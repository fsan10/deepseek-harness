#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入快手结算单到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "商家ID",
    "订单号",
    "商品ID",
    "商品名称",
    "商品数量",
    "订单创建时间",
    "订单实付(元)",
    "政府补贴",
    "支付营销补贴",
    "平台补贴",
    "商家补贴(元)",
    "达人补贴",
    "达人补贴明细",
    "合计收入(元)",
    "订单退款(元)",
    "支付营销回退（元）",
    "技术服务费(元)",
    "预售增收技术服务费（元）",
    "达人ID",
    "MCN机构ID",
    "达人佣金(元)",
    "团长id",
    "团长佣金(元)",
    "佣金模式",
    "快赚客ID",
    "快赚客佣金(元)",
    "服务商ID",
    "服务商佣金(元)",
    "分账基数",
    "其他收费",
    "其他收费明细",
    "合计支出(元)",
    "实际结算金额(元)",
    "实际结算时间",
    "结算规则",
    "资金渠道",
    "账户名称",
    "结算商户号",
    "备注",
    "消费金信息",
    "运费",
]


CONFIG = OdsLoadConfig(
    platform_code="ks",
    platform_name="快手",
    data_domain="settlement",
    table_name="ods.ods_ks_settlement_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将快手结算单 XLSX 导入 PostgreSQL 的 ODS 表。")

