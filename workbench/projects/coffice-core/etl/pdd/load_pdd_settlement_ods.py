#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入拼多多结算/账务明细到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "商户订单号",
    "发生时间",
    "收入金额（+元）",
    "支出金额（-元）",
    "账务类型",
    "备注",
    "业务描述",
]


CONFIG = OdsLoadConfig(
    platform_code="pdd",
    platform_name="拼多多",
    data_domain="settlement",
    table_name="ods.ods_pdd_settlement_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=5,
    data_start_row_no=6,
    default_encoding_candidates=("gb2312", "gbk", "gb18030", "utf-8-sig", "utf-8"),
    stop_at_comment_rows=True,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将拼多多结算/账务明细 CSV 导入 PostgreSQL 的 ODS 表。")

