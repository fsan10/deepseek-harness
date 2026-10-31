#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫宝贝销售明细 CSV/XLSX 到子订单粒度 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
子订单编号
主订单编号
商品标题
购买数量
商品属性
订单状态
商家编码
买家应付货款
买家实付金额
退款状态
退款金额
订单创建时间
订单付款时间
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="order",
    table_name="ods.ods_tmall_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    strict_header=False,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫宝贝销售明细文件导入 PostgreSQL 子订单ODS。")
