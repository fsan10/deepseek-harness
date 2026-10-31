CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_ks_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "账务流水号" TEXT,
    "关联业务单号" TEXT,
    "入账时间" TEXT,
    "账务方向" TEXT,
    "发生额（元）" TEXT,
    "期末余额（元）" TEXT,
    "业务类型" TEXT,
    "描述" TEXT,
    "备注" TEXT,

    CONSTRAINT uk_ods_ks_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_ks_fund_flow_no ON ods.ods_ks_fund_raw ("账务流水号");
CREATE INDEX IF NOT EXISTS idx_ods_ks_fund_biz_no ON ods.ods_ks_fund_raw ("关联业务单号");
CREATE INDEX IF NOT EXISTS idx_ods_ks_fund_source_file ON ods.ods_ks_fund_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_ks_fund_batch_id ON ods.ods_ks_fund_raw (batch_id);

COMMENT ON TABLE ods.ods_ks_fund_raw IS 'ODS快手资金单原始表，按平台导出资金文件表头原样保存。';
COMMENT ON COLUMN ods.ods_ks_fund_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_ks_fund_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_ks_fund_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_ks_fund_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_ks_fund_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_ks_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_ks_fund_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."账务流水号" IS '来源文件字段“账务流水号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."关联业务单号" IS '来源文件字段“关联业务单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."入账时间" IS '来源文件字段“入账时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."账务方向" IS '来源文件字段“账务方向”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."发生额（元）" IS '来源文件字段“发生额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."期末余额（元）" IS '来源文件字段“期末余额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."业务类型" IS '来源文件字段“业务类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."描述" IS '来源文件字段“描述”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_fund_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
