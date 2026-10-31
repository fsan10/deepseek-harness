#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入小红书订单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
订单号
订单状态
售后状态
订单类型
订单标记
收件人姓名
收件人电话
收件人地址
省
市
区
区域编码
小红书编码
条形码
规格ID
达人ID
达人名称
SKU名称
SKU规格
SKU件数
是否为赠品
发票/Invoice
商品总价(元)
用户应付金额(元)
平台优惠(元)
店铺优惠(元)
支付渠道优惠(元)
SKU商家改价(元)
商家应收金额(元)（支付金额）
支付方式
支付渠道订单号
支付期数
利息费用
手续费承担方
支付时间
sku净重(kg)
包裹总净重(kg)
包裹总运费(元)
快递公司
快递单号
发货链接
大头笔/Paint Marker
集包地/Express Extend 1
三段码/Express Extend 2
订购人身份证姓名/ID Name
订购人身份证号/ID Number
收件人身份证姓名
收件人身份证号
订单创建时间
预售订单开始发货时间
预售订单截止发货时间
承诺发货时间
订单发货时间
订单完成时间
发货仓库
确认收货类型
是否延迟收货
用户备注
包裹备注标记
包裹备注信息
异常原因
店铺名称
用户编号
运费模版名称
物流方案名称
第三方机构订单号
国补模式
供应商id
供应商名称
商家编码
商品ID
商品名称
供货商ID
供货商名称
供货单号
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="xhs",
    platform_name="小红书",
    data_domain="order",
    table_name="ods.ods_xhs_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将小红书订单文件导入 PostgreSQL 的 ODS 表。")
