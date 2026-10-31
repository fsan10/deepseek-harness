CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_pdd_settlement_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "商户订单号" VARCHAR(128),
    "发生时间" VARCHAR(64),
    "收入金额（+元）" VARCHAR(64),
    "支出金额（-元）" VARCHAR(64),
    "账务类型" VARCHAR(128),
    "备注" TEXT,
    "业务描述" TEXT,

    CONSTRAINT uk_ods_pdd_settlement_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_pdd_settlement_raw
SET source_sheet_name = 'CSV'
WHERE source_sheet_name IS NULL OR source_sheet_name = '';

ALTER TABLE ods.ods_pdd_settlement_raw
    ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';

ALTER TABLE ods.ods_pdd_settlement_raw
    ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_pdd_settlement_batch_id ON ods.ods_pdd_settlement_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_pdd_settlement_order_no ON ods.ods_pdd_settlement_raw ("商户订单号");
CREATE INDEX IF NOT EXISTS idx_ods_pdd_settlement_occurred_at ON ods.ods_pdd_settlement_raw ("发生时间");
CREATE INDEX IF NOT EXISTS idx_ods_pdd_settlement_source_file ON ods.ods_pdd_settlement_raw (source_file_name);

COMMENT ON TABLE ods.ods_pdd_settlement_raw IS 'ODS拼多多结算/账务明细原始表';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.source_sheet_name IS '来源工作表；CSV固定写CSV';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_pdd_settlement_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."商户订单号" IS '来源文件字段“商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."发生时间" IS '来源文件字段“发生时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."收入金额（+元）" IS '来源文件字段“收入金额（+元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."支出金额（-元）" IS '来源文件字段“支出金额（-元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."账务类型" IS '来源文件字段“账务类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_pdd_settlement_raw."业务描述" IS '来源文件字段“业务描述”，保留平台导出的原始值。';
