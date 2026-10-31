CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "日期" TEXT,
    "明细笔数" TEXT,
    "收入金额（元）" TEXT,
    "收入笔数" TEXT,
    "支出金额（元）" TEXT,
    "支出笔数" TEXT,
    "期末余额（元）" TEXT,

    CONSTRAINT uk_ods_tmall_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_tmall_fund_date ON ods.ods_tmall_fund_raw ("日期");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_fund_source_file ON ods.ods_tmall_fund_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_fund_batch_id ON ods.ods_tmall_fund_raw (batch_id);

COMMENT ON TABLE ods.ods_tmall_fund_raw IS 'ODS天猫资金单原始表，当前源文件为日级资金汇总。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_tmall_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."日期" IS '来源文件字段“日期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."明细笔数" IS '来源文件字段“明细笔数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."收入金额（元）" IS '来源文件字段“收入金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."收入笔数" IS '来源文件字段“收入笔数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."支出金额（元）" IS '来源文件字段“支出金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."支出笔数" IS '来源文件字段“支出笔数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_fund_raw."期末余额（元）" IS '来源文件字段“期末余额（元）”，保留平台导出的原始值。';
