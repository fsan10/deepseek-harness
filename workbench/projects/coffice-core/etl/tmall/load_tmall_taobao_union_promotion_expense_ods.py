#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入天猫淘宝联盟推广费日数据到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


CONFIG = OdsLoadConfig(
    platform_code="tmall",
    platform_name="天猫",
    data_domain="ad",
    table_name="ods.ods_tmall_taobao_union_promotion_expense_raw",
    expected_columns=[
        "日期",
        "点击量(即进店量)",
        "点击人数(即进店人数)",
        "推广商品数",
        "优惠券领取量",
        "付款金额(元)",
        "付款笔数",
        "付款人数",
        "付款件数",
        "结算人数",
        "点击转化率(即付款转化率)",
        "确认收货人数",
        "确认收货金额",
        "确认收货笔数",
        "添加购物车量",
        "收藏宝贝量",
        "结算金额(元)",
        "结算笔数",
        "付款佣金支出(元)",
        "付款服务费支出(元)",
        "付款支出费用(元)",
        "付款佣金率",
        "付款服务费率",
        "单件商品付款支出费用(元)",
        "结算佣金支出(元)",
        "结算服务费支出(元)",
        "结算支出费用(元)",
        "结算佣金率",
        "结算服务费率",
        "预估预售整单佣金(元)",
        "预估预售整单佣金率",
        "预售定金笔数",
        "预售定金金额(元)",
        "预估预售尾款金额(元)",
        "预估预售整单金额(元)",
        "付款营销服务费支出(元)",
        "结算营销服务费支出(元)",
    ],
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将天猫淘宝联盟推广费日数据导入 PostgreSQL ODS。")
