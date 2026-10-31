#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入视频号动账流水到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "流水单号",
    "记账时间",
    "动帐类型",
    "收支类型",
    "收支金额",
    "账户余额",
    "关联订单号",
    "关联售后单号",
    "关联提现单号",
    "关联保单号",
    "关联礼物单号",
    "详情",
]


CONFIG = OdsLoadConfig(
    platform_code="wechat_channels",
    platform_name="视频号",
    data_domain="settlement",
    table_name="ods.ods_wechat_channels_settlement_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将视频号动账流水 XLSX 导入 PostgreSQL 的 ODS 表。")

