#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入京东结算单到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, infer_date_from_file, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "订单编号",
    "单据编号",
    "单据类型",
    "商品编号",
    "商户订单号",
    "商品名称",
    "费用发生时间",
    "费用计费时间",
    "费用结算时间",
    "费用项",
    "金额",
    "币种",
    "商家应收/应付",
    "钱包结算备注",
    "店铺号",
    "京东门店编号",
    "品牌门店编号",
    "门店名称",
    "备注",
    "收支方向",
    "账单日期",
    "商品数量",
]


def fill_bill_date(row_map, args, path):
    if row_map.get("账单日期"):
        return row_map
    inferred = args.bill_date or infer_date_from_file(path)
    if not inferred:
        inferred = __import__("datetime").datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    row_map["账单日期"] = inferred
    return row_map


CONFIG = OdsLoadConfig(
    platform_code="jd",
    platform_name="京东",
    data_domain="settlement",
    table_name="ods.ods_jd_settlement_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_encoding_candidates=("gb2312", "gbk", "gb18030", "utf-8-sig", "utf-8"),
    optional_columns=("账单日期",),
    custom_row_transform=fill_bill_date,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将京东结算单 CSV 导入 PostgreSQL 的 ODS 表。")
