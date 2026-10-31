CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_xhs_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" TEXT,
    "订单状态" TEXT,
    "售后状态" TEXT,
    "订单类型" TEXT,
    "订单标记" TEXT,
    "收件人姓名" TEXT,
    "收件人电话" TEXT,
    "收件人地址" TEXT,
    "省" TEXT,
    "市" TEXT,
    "区" TEXT,
    "区域编码" TEXT,
    "小红书编码" TEXT,
    "条形码" TEXT,
    "规格ID" TEXT,
    "达人ID" TEXT,
    "达人名称" TEXT,
    "SKU名称" TEXT,
    "SKU规格" TEXT,
    "SKU件数" TEXT,
    "是否为赠品" TEXT,
    "发票/Invoice" TEXT,
    "商品总价(元)" TEXT,
    "用户应付金额(元)" TEXT,
    "平台优惠(元)" TEXT,
    "店铺优惠(元)" TEXT,
    "支付渠道优惠(元)" TEXT,
    "SKU商家改价(元)" TEXT,
    "商家应收金额(元)（支付金额）" TEXT,
    "支付方式" TEXT,
    "支付渠道订单号" TEXT,
    "支付期数" TEXT,
    "利息费用" TEXT,
    "手续费承担方" TEXT,
    "支付时间" TEXT,
    "sku净重(kg)" TEXT,
    "包裹总净重(kg)" TEXT,
    "包裹总运费(元)" TEXT,
    "快递公司" TEXT,
    "快递单号" TEXT,
    "发货链接" TEXT,
    "大头笔/Paint Marker" TEXT,
    "集包地/Express Extend 1" TEXT,
    "三段码/Express Extend 2" TEXT,
    "订购人身份证姓名/ID Name" TEXT,
    "订购人身份证号/ID Number" TEXT,
    "收件人身份证姓名" TEXT,
    "收件人身份证号" TEXT,
    "订单创建时间" TEXT,
    "预售订单开始发货时间" TEXT,
    "预售订单截止发货时间" TEXT,
    "承诺发货时间" TEXT,
    "订单发货时间" TEXT,
    "订单完成时间" TEXT,
    "发货仓库" TEXT,
    "确认收货类型" TEXT,
    "是否延迟收货" TEXT,
    "用户备注" TEXT,
    "包裹备注标记" TEXT,
    "包裹备注信息" TEXT,
    "异常原因" TEXT,
    "店铺名称" TEXT,
    "用户编号" TEXT,
    "运费模版名称" TEXT,
    "物流方案名称" TEXT,
    "第三方机构订单号" TEXT,
    "国补模式" TEXT,
    "供应商id" TEXT,
    "供应商名称" TEXT,
    "商家编码" TEXT,
    "商品ID" TEXT,
    "商品名称" TEXT,
    "供货商ID" TEXT,
    "供货商名称" TEXT,
    "供货单号" TEXT,

    CONSTRAINT uk_ods_xhs_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_order_no ON ods.ods_xhs_order_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_product_id ON ods.ods_xhs_order_raw ("商品ID");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_sku_id ON ods.ods_xhs_order_raw ("规格ID");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_daren_id ON ods.ods_xhs_order_raw ("达人ID");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_source_file ON ods.ods_xhs_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_xhs_order_batch_id ON ods.ods_xhs_order_raw (batch_id);

COMMENT ON TABLE ods.ods_xhs_order_raw IS 'ODS小红书订单原始表，按平台导出订单文件表头原样保存。';
COMMENT ON COLUMN ods.ods_xhs_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_xhs_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_xhs_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_xhs_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_xhs_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_xhs_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_xhs_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."售后状态" IS '来源文件字段“售后状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单类型" IS '来源文件字段“订单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单标记" IS '来源文件字段“订单标记”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."收件人姓名" IS '来源文件字段“收件人姓名”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."收件人电话" IS '来源文件字段“收件人电话”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."收件人地址" IS '来源文件字段“收件人地址”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."省" IS '来源文件字段“省”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."市" IS '来源文件字段“市”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."区" IS '来源文件字段“区”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."区域编码" IS '来源文件字段“区域编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."小红书编码" IS '来源文件字段“小红书编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."条形码" IS '来源文件字段“条形码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."规格ID" IS '来源文件字段“规格ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."达人ID" IS '来源文件字段“达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."达人名称" IS '来源文件字段“达人名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."SKU名称" IS '来源文件字段“SKU名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."SKU规格" IS '来源文件字段“SKU规格”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."SKU件数" IS '来源文件字段“SKU件数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."是否为赠品" IS '来源文件字段“是否为赠品”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."发票/Invoice" IS '来源文件字段“发票/Invoice”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."商品总价(元)" IS '来源文件字段“商品总价(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."用户应付金额(元)" IS '来源文件字段“用户应付金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."平台优惠(元)" IS '来源文件字段“平台优惠(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."店铺优惠(元)" IS '来源文件字段“店铺优惠(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."支付渠道优惠(元)" IS '来源文件字段“支付渠道优惠(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."SKU商家改价(元)" IS '来源文件字段“SKU商家改价(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."商家应收金额(元)（支付金额）" IS '来源文件字段“商家应收金额(元)（支付金额）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."支付方式" IS '来源文件字段“支付方式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."支付渠道订单号" IS '来源文件字段“支付渠道订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."支付期数" IS '来源文件字段“支付期数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."利息费用" IS '来源文件字段“利息费用”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."手续费承担方" IS '来源文件字段“手续费承担方”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."支付时间" IS '来源文件字段“支付时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."sku净重(kg)" IS '来源文件字段“sku净重(kg)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."包裹总净重(kg)" IS '来源文件字段“包裹总净重(kg)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."包裹总运费(元)" IS '来源文件字段“包裹总运费(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."快递公司" IS '来源文件字段“快递公司”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."快递单号" IS '来源文件字段“快递单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."发货链接" IS '来源文件字段“发货链接”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."大头笔/Paint Marker" IS '来源文件字段“大头笔/Paint Marker”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."集包地/Express Extend 1" IS '来源文件字段“集包地/Express Extend 1”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."三段码/Express Extend 2" IS '来源文件字段“三段码/Express Extend 2”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订购人身份证姓名/ID Name" IS '来源文件字段“订购人身份证姓名/ID Name”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订购人身份证号/ID Number" IS '来源文件字段“订购人身份证号/ID Number”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."收件人身份证姓名" IS '来源文件字段“收件人身份证姓名”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."收件人身份证号" IS '来源文件字段“收件人身份证号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单创建时间" IS '来源文件字段“订单创建时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."预售订单开始发货时间" IS '来源文件字段“预售订单开始发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."预售订单截止发货时间" IS '来源文件字段“预售订单截止发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."承诺发货时间" IS '来源文件字段“承诺发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单发货时间" IS '来源文件字段“订单发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."订单完成时间" IS '来源文件字段“订单完成时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."发货仓库" IS '来源文件字段“发货仓库”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."确认收货类型" IS '来源文件字段“确认收货类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."是否延迟收货" IS '来源文件字段“是否延迟收货”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."用户备注" IS '来源文件字段“用户备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."包裹备注标记" IS '来源文件字段“包裹备注标记”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."包裹备注信息" IS '来源文件字段“包裹备注信息”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."异常原因" IS '来源文件字段“异常原因”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."店铺名称" IS '来源文件字段“店铺名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."用户编号" IS '来源文件字段“用户编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."运费模版名称" IS '来源文件字段“运费模版名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."物流方案名称" IS '来源文件字段“物流方案名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."第三方机构订单号" IS '来源文件字段“第三方机构订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."国补模式" IS '来源文件字段“国补模式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."供应商id" IS '来源文件字段“供应商id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."供应商名称" IS '来源文件字段“供应商名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."商家编码" IS '来源文件字段“商家编码”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."供货商ID" IS '来源文件字段“供货商ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."供货商名称" IS '来源文件字段“供货商名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_order_raw."供货单号" IS '来源文件字段“供货单号”，保留平台导出的原始值。';
