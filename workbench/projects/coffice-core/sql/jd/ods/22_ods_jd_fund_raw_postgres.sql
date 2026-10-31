CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_jd_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "商户订单号" TEXT,
    "交易订单号" TEXT,
    "支出类型" TEXT,
    "交易金额" TEXT,
    "交易类型" TEXT,
    "入账时间" TEXT,
    "资金动账备注" TEXT,

    CONSTRAINT uk_ods_jd_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_jd_fund_merchant_order_no ON ods.ods_jd_fund_raw ("商户订单号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_fund_trade_order_no ON ods.ods_jd_fund_raw ("交易订单号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_fund_source_file ON ods.ods_jd_fund_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_jd_fund_batch_id ON ods.ods_jd_fund_raw (batch_id);

COMMENT ON TABLE ods.ods_jd_fund_raw IS 'ODS京东资金单原始表，按平台导出资金文件表头原样保存。';
COMMENT ON COLUMN ods.ods_jd_fund_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_jd_fund_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_jd_fund_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_jd_fund_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_jd_fund_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_jd_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_jd_fund_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."商户订单号" IS '来源文件字段“商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."交易订单号" IS '来源文件字段“交易订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."支出类型" IS '来源文件字段“支出类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."交易金额" IS '来源文件字段“交易金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."交易类型" IS '来源文件字段“交易类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."入账时间" IS '来源文件字段“入账时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_fund_raw."资金动账备注" IS '来源文件字段“资金动账备注”，保留平台导出的原始值。';
