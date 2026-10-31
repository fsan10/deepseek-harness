CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_settlement_income_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "账期" VARCHAR(64),
    "账单大类" VARCHAR(128),
    "业务大类" VARCHAR(128),
    "业务小类" VARCHAR(128),
    "订单号" VARCHAR(128),
    "子订单号" VARCHAR(128),
    "下单时间" VARCHAR(64),
    "确认收货时间" VARCHAR(64),
    "商品ID" VARCHAR(128),
    "sku" TEXT,
    "商品名称" TEXT,
    "数量" VARCHAR(64),
    "单价（元）" VARCHAR(64),
    "订单实际金额（元）" VARCHAR(64),
    "退款单号" VARCHAR(128),
    "退款金额（元）" VARCHAR(64),
    "收/付渠道" VARCHAR(128),
    "业务流水号" VARCHAR(128),
    "商户订单号" VARCHAR(128),
    "打款时间" VARCHAR(64),
    "打款更新时间" VARCHAR(64),
    "备注" TEXT,

    CONSTRAINT uk_ods_tmall_settlement_income_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_tmall_settlement_income_raw SET source_sheet_name = 'CSV' WHERE source_sheet_name IS NULL OR source_sheet_name = '';
ALTER TABLE ods.ods_tmall_settlement_income_raw ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';
ALTER TABLE ods.ods_tmall_settlement_income_raw ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_tmall_income_batch_id ON ods.ods_tmall_settlement_income_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_income_order_no ON ods.ods_tmall_settlement_income_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_income_sub_order_no ON ods.ods_tmall_settlement_income_raw ("子订单号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_income_product_id ON ods.ods_tmall_settlement_income_raw ("商品ID");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_income_source_file ON ods.ods_tmall_settlement_income_raw (source_file_name);

COMMENT ON TABLE ods.ods_tmall_settlement_income_raw IS 'ODS天猫结算收入原始表';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.source_sheet_name IS '来源工作表；CSV固定写CSV';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."账期" IS '来源文件字段“账期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."账单大类" IS '来源文件字段“账单大类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."业务大类" IS '来源文件字段“业务大类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."业务小类" IS '来源文件字段“业务小类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."子订单号" IS '来源文件字段“子订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."下单时间" IS '来源文件字段“下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."确认收货时间" IS '来源文件字段“确认收货时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."sku" IS '来源文件字段“sku”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."数量" IS '来源文件字段“数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."单价（元）" IS '来源文件字段“单价（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."订单实际金额（元）" IS '来源文件字段“订单实际金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."退款单号" IS '来源文件字段“退款单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."退款金额（元）" IS '来源文件字段“退款金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."收/付渠道" IS '来源文件字段“收/付渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."业务流水号" IS '来源文件字段“业务流水号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."商户订单号" IS '来源文件字段“商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."打款时间" IS '来源文件字段“打款时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."打款更新时间" IS '来源文件字段“打款更新时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_income_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
