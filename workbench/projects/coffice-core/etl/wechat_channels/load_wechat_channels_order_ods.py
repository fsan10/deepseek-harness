#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入视频号订单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
订单号
订单下单时间
订单发货时间
订单确认收货时间
订单完成结算时间
订单状态
发货方式
收件人姓名
收件人地址
省
市
区
收件人手机
买家备注
商家备注
打标颜色
商品总价
订单实际支付金额
订单实际收款金额
订单运费
商家优惠
平台优惠
跨店优惠
商品改价
积分抵扣
支付方式
支付时间
交易单号
物流公司
快递单号
技术服务费
技术服务费（将以人气卡形式返还）
运费险预计投保费用
带货方式
带货账号类型
带货账号昵称
带货ID
带货费用渠道
带货费用类型
带货费用
带货佣金率
企微企业ID
企微工号
导购最近分享时间
企业微信加密id
企微备注
礼物单号
商品名称
商品编码(平台)
商品编码(自定义)
SKU编码(自定义)
商品属性
商品价格(单件)
商品实际价格(单件)
商品实际价格(总共)
是否预售
商品数量
商品平台券优惠
商品平均运费
活动商家补贴
定制信息
定制预览图
商品发货
商品售后
商品已退款金额
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="wechat_channels",
    platform_name="视频号",
    data_domain="order",
    table_name="ods.ods_wechat_channels_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    # 视频号旧版订单文件使用“商品优惠”单列；新版拆分为“商家优惠”和“平台优惠”。
    # 旧字段仅作为商家优惠的兼容别名，平台优惠在旧文件中留空，原始ODS表不新增兼容层。
    optional_columns=("平台优惠",),
    header_aliases={"商品优惠": "商家优惠"},
)


if __name__ == "__main__":
    run_loader(CONFIG, "将视频号订单文件导入 PostgreSQL 的 ODS 表。")
