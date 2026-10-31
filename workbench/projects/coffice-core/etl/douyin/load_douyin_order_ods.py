#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入抖音订单 CSV 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = [
    "主订单编号",
    "子订单编号",
    "选购商品",
    "商品规格",
    "商品数量",
    "商品ID",
    "商家编码",
    "商品单价",
    "订单应付金额",
    "运费",
    "优惠总金额",
    "平台优惠",
    "商家优惠",
    "达人优惠",
    "商家改价",
    "支付优惠",
    "红包抵扣",
    "支付方式",
    "手续费",
    "收件人",
    "收件人手机号",
    "省",
    "市",
    "区",
    "街道",
    "详细地址",
    "是否修改过地址",
    "地址修改时段",
    "买家留言",
    "订单提交时间",
    "旗帜颜色",
    "商家备注",
    "订单完成时间",
    "支付完成时间",
    "APP渠道",
    "流量来源",
    "订单状态",
    "承诺发货时间",
    "订单类型",
    "鲁班落地页ID",
    "达人ID",
    "达人昵称",
    "所属门店ID",
    "售后状态",
    "取消原因",
    "预约发货时间",
    "仓库ID",
    "仓库名称",
    "是否安心购",
    "广告渠道",
    "流量类型",
    "流量体裁",
    "流量渠道",
    "发货主体",
    "发货主体明细",
    "发货时间",
    "降价类优惠",
    "平台实际承担优惠金额",
    "商家实际承担优惠金额",
    "达人实际承担优惠金额",
    "预计送达时间",
    "是否平台仓自流转",
    "车型",
    "商品69码",
    "发货SN码",
    "发货IMEI码1",
    "发货IMEI码2",
    "是否福袋订单",
    "福袋采购订单号",
    "福袋采购订单状态",
    "福袋采购订单采购方ID",
    "福袋采购订单采购方名称",
    "福袋采购订单创建时间",
    "福袋采购订单支付时间",
    "福袋采购订单订单应付金额",
    "福袋采购订单订单实际付款金额",
    "福袋采购订单订单优惠金额",
    "福袋采购订单商品ID",
    "福袋采购订单商品名称",
    "福袋采购订单商品单价",
    "福袋采购订单商品数量",
    "福袋采购订单核销数量",
    "福袋采购订单结算数量",
    "预约送达时间",
    "建议发货时间（起）",
    "建议发货时间（止）",
    "物流SN码",
    "物流IMEI码1",
    "物流IMEI码2",
]

# 抖音订单导出存在两个版本：旧版不包含福袋订单扩展字段，新版会带出这
# 16 列。ODS 仍保留完整字段定义，但这些列缺失时应按 NULL 入库，而不是
# 拒绝整份订单文件。
OPTIONAL_COLUMNS = (
    "是否福袋订单",
    "福袋采购订单号",
    "福袋采购订单状态",
    "福袋采购订单采购方ID",
    "福袋采购订单采购方名称",
    "福袋采购订单创建时间",
    "福袋采购订单支付时间",
    "福袋采购订单订单应付金额",
    "福袋采购订单订单实际付款金额",
    "福袋采购订单订单优惠金额",
    "福袋采购订单商品ID",
    "福袋采购订单商品名称",
    "福袋采购订单商品单价",
    "福袋采购订单商品数量",
    "福袋采购订单核销数量",
    "福袋采购订单结算数量",
)

SENSITIVE_ORDER_COLUMNS = (
    "收件人",
    "收件人手机号",
    "详细地址",
)


def mask_sensitive_order_fields(
    source_map: dict[str, str | None],
    _args,
    _path: Path,
) -> dict[str, str | None]:
    """Mask unused recipient data before the row hash is calculated."""
    for column_name in SENSITIVE_ORDER_COLUMNS:
        if source_map.get(column_name) is not None:
            source_map[column_name] = "***"
    return source_map


CONFIG = OdsLoadConfig(
    platform_code="douyin",
    platform_name="抖音",
    data_domain="order",
    table_name="ods.ods_douyin_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    optional_columns=OPTIONAL_COLUMNS,
    custom_row_transform=mask_sensitive_order_fields,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将抖音订单 CSV 导入 PostgreSQL 的 ODS 表。")
