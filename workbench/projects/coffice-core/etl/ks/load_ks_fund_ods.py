#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入快手资金单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "账务流水号",
    "关联业务单号",
    "入账时间",
    "账务方向",
    "发生额（元）",
    "期末余额（元）",
    "业务类型",
    "描述",
    "备注",
]


CONFIG = OdsLoadConfig(
    platform_code="ks",
    platform_name="快手",
    data_domain="fund",
    table_name="ods.ods_ks_fund_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    default_encoding_candidates=("gb18030", "gbk", "gb2312", "utf-8-sig", "utf-8"),
)


if __name__ == "__main__":
    run_loader(CONFIG, "将快手资金单文件导入 PostgreSQL 的 ODS 表。")
