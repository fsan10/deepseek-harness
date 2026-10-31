#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入京东订单 CSV/XLSX 到 ODS。"""

from __future__ import annotations

import sys
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ods_file_loader import OdsLoadConfig, run_loader  # noqa: E402


EXPECTED_COLUMNS = """
订单号
商品ID
商品名称
订购数量
支付方式
下单时间
京东价
订单金额
商家应收
余额支付
应付金额
订单状态
订单类型
订单标签
下单帐号
订单备注
发票类型
发票抬头
发票内容
纳税人识别号
名称（个人）
单位地址
单位电话
开户银行
银行账号
商家备注
商家备注等级（等级1-5为由高到低）
运费金额
付款确认时间
货号
订单完成时间
订单来源
订单渠道
送装服务
服务费
仓库id
仓库名称
商家SKUID
邮箱地址
邮政编码
是否为品牌商订单
是否为toplife订单
业务类型
履约门店ID
下单门店Id
门店名称
门店联系人
门店联系电话
门店地址
导购员账号
延迟报备类型
订单出库时间
客户类型
KA订单发货需提供单据
KA订单客户收货要求
正品鉴定校验结果
正品鉴定补充说明
正品鉴定不合格原因
正品鉴定图片链接
企配订单
需上传SN码
SN码
SN码有效状态
SN码激活状态
SN码补贴状态
百补满赠
买一试三
最晚/承诺发货时间（仅当日发/明日达为承诺时间）
款项名称
项目ID
指数订单编号
是否为以旧换新订单
主体ID
主体名称
采购价
采购订单号
敏感信息超额
""".strip().splitlines()


CONFIG = OdsLoadConfig(
    platform_code="jd",
    platform_name="京东",
    data_domain="order",
    table_name="ods.ods_jd_order_raw",
    expected_columns=EXPECTED_COLUMNS,
    header_row_no=1,
    data_start_row_no=2,
)


if __name__ == "__main__":
    run_loader(CONFIG, "将京东订单文件导入 PostgreSQL 的 ODS 表。")
