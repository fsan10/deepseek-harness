CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_pdd_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "商品" TEXT,
    "订单号" TEXT,
    "订单状态" TEXT,
    "商品总价(元)" TEXT,
    "邮费(元)" TEXT,
    "店铺优惠折扣(元)" TEXT,
    "平台优惠折扣(元)" TEXT,
    "多多支付立减金额(元)" TEXT,
    "用户实付金额(元)" TEXT,
    "商家实收金额(元)" TEXT,
    "商品数量(件)" TEXT,
    "发货时间" TEXT,
    "确认收货时间" TEXT,
    "商品id" TEXT,
    "商品规格" TEXT,
    "样式ID" TEXT,
    "商家编码-规格维度" TEXT,
    "商家编码-商品维度" TEXT,
    "商家备注" TEXT,
    "售后状态" TEXT,
    "快递单号" TEXT,
    "快递公司" TEXT,
    "订单成交时间" TEXT,
    "是否分期" TEXT,
    "分期期数" TEXT,
    "手续费承担方" TEXT,
    "分期方式" TEXT,

    CONSTRAINT uk_ods_pdd_order_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_pdd_order_order_no ON ods.ods_pdd_order_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_pdd_order_product_id ON ods.ods_pdd_order_raw ("商品id");
CREATE INDEX IF NOT EXISTS idx_ods_pdd_order_style_id ON ods.ods_pdd_order_raw ("样式ID");
CREATE INDEX IF NOT EXISTS idx_ods_pdd_order_source_file ON ods.ods_pdd_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_pdd_order_batch_id ON ods.ods_pdd_order_raw (batch_id);

COMMENT ON TABLE ods.ods_pdd_order_raw IS 'ODS拼多多订单原始表，按平台导出订单文件表头原样保存。';
COMMENT ON COLUMN ods.ods_pdd_order_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_pdd_order_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_pdd_order_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_pdd_order_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_pdd_order_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_pdd_order_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_pdd_order_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商品" IS '来源文件字段“商品”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."订单状态" IS '来源文件字段“订单状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商品总价(元)" IS '来源文件字段“商品总价(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."邮费(元)" IS '来源文件字段“邮费(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."店铺优惠折扣(元)" IS '来源文件字段“店铺优惠折扣(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."平台优惠折扣(元)" IS '来源文件字段“平台优惠折扣(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."多多支付立减金额(元)" IS '来源文件字段“多多支付立减金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."用户实付金额(元)" IS '来源文件字段“用户实付金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商家实收金额(元)" IS '来源文件字段“商家实收金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商品数量(件)" IS '来源文件字段“商品数量(件)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."发货时间" IS '来源文件字段“发货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."确认收货时间" IS '来源文件字段“确认收货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商品id" IS '来源文件字段“商品id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商品规格" IS '来源文件字段“商品规格”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."样式ID" IS '来源文件字段“样式ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商家编码-规格维度" IS '来源文件字段“商家编码-规格维度”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商家编码-商品维度" IS '来源文件字段“商家编码-商品维度”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."商家备注" IS '来源文件字段“商家备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."售后状态" IS '来源文件字段“售后状态”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."快递单号" IS '来源文件字段“快递单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."快递公司" IS '来源文件字段“快递公司”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."订单成交时间" IS '来源文件字段“订单成交时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."是否分期" IS '来源文件字段“是否分期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."分期期数" IS '来源文件字段“分期期数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."手续费承担方" IS '来源文件字段“手续费承担方”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_order_raw."分期方式" IS '来源文件字段“分期方式”，保留平台导出的原始值。';
