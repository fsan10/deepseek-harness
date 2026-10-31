#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入抖音结算单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "结算时间",
    "订单号",
    "子订单号",
    "结算金额",
    "结算账户",
    "结算单类型",
    "有结算前退款",
    "下单时间",
    "商品ID",
    "商品名称",
    "商品数量",
    "达人ID",
    "达人名称",
    "业务类型",
    "订单类型",
    "订单总价",
    "商品总价",
    "运费",
    "店铺券",
    "政府补贴商家垫资",
    "结算前退款金额",
    "平台补贴",
    "其他平台补贴",
    "政府补贴平台垫资",
    "达人补贴",
    "抖音支付补贴",
    "抖音月付营销补贴",
    "银行补贴",
    "以旧换新抵扣",
    "平台补贴运费",
    "用户实付",
    "收入合计",
    "平台服务费",
    "达人佣金",
    "服务商佣金",
    "渠道分成",
    "招商服务费",
    "站外推广费",
    "其他分成",
    "其他分成说明",
    "支出合计",
    "是否免佣",
    "免佣金额",
    "商户主体名称",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="douyin",
    platform_name="抖音",
    data_domain="settlement",
    table_name="ods.ods_douyin_settlement_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=3,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将抖音结算单文件导入 PostgreSQL 的 ODS 表。")
