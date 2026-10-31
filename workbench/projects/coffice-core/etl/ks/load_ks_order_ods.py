#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入快手订单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
订单号
赠品订单号
活动订单编号
订单创建时间
订单支付时间
预售定金支付时间
订单状态
实付款
快递费
店铺优惠
平台补贴
主播补贴
混资活动优惠
支付优惠
支付方式
成交数量
买家留言
账号类型
账号明细
订单备注
旗帜颜色
售后状态
活动订单
预售/承诺发货时间
订单载体
商品名称
商品ID
商品规格
SKU编码
商品单价
渠道
CPS达人ID
CPS达人昵称
预估推广佣金
预估推广者分佣比例
团长ID
团长昵称
快赚客ID
快赚客昵称
授权推广者ID
授权推广者昵称
收货人姓名
收货人电话
收货地址-省
收货地址-市
收货地址-区
收货地址-街道
收货地址
发货时间
快递公司
快递单号
物流信息
集运类型
直邮类型
仓库名称
仓库地址
发货类型
实名姓名
服务门店ID
服务门店名称
服务门店地址
国补/类国补/消费券
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="ks",
    platform_name="快手",
    data_domain="order",
    table_name="ods.ods_ks_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
    # 快手订单导出会随版本增加非业务字段；ODS 只按字段名抽取已定义列，
    # 保留必填字段校验但允许额外列插入，避免平台导出格式小幅扩展导致整批失败。
    strict_header=False,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将快手订单文件导入 PostgreSQL 的 ODS 表。")
