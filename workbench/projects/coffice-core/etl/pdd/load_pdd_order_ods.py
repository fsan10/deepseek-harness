#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入拼多多订单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
商品
订单号
订单状态
商品总价(元)
邮费(元)
店铺优惠折扣(元)
平台优惠折扣(元)
多多支付立减金额(元)
用户实付金额(元)
商家实收金额(元)
商品数量(件)
发货时间
确认收货时间
商品id
商品规格
样式ID
商家编码-规格维度
商家编码-商品维度
商家备注
售后状态
快递单号
快递公司
订单成交时间
是否分期
分期期数
手续费承担方
分期方式
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="pdd",
    platform_name="拼多多",
    data_domain="order",
    table_name="ods.ods_pdd_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将拼多多订单文件导入 PostgreSQL 的 ODS 表。")
