CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_xhs_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "创建时间" TEXT,
    "交易类型描述" TEXT,
    "收入（元）" TEXT,
    "支出（元）" TEXT,
    "账户余额（元）" TEXT,
    "业务单号" TEXT,
    "备注" TEXT,

    CONSTRAINT uk_ods_xhs_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_biz_no ON ods.ods_xhs_fund_raw ("业务单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_source_file ON ods.ods_xhs_fund_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_batch_id ON ods.ods_xhs_fund_raw (batch_id);

COMMENT ON TABLE ods.ods_xhs_fund_raw IS 'ODS小红书资金单原始表，按平台导出资金文件表头原样保存。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_xhs_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."创建时间" IS '来源文件字段“创建时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."交易类型描述" IS '来源文件字段“交易类型描述”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."收入（元）" IS '来源文件字段“收入（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."支出（元）" IS '来源文件字段“支出（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."账户余额（元）" IS '来源文件字段“账户余额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."业务单号" IS '来源文件字段“业务单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_fund_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
