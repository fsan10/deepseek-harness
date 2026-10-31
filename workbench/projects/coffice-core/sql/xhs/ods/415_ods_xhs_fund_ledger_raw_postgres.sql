CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_xhs_fund_ledger_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT '资金账单明细',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "动账时间" TEXT,
    "业务单号" TEXT,
    "动账场景" TEXT,
    "动账方向" TEXT,
    "动账金额" TEXT,
    "动账账户" TEXT,
    "动账后余额" TEXT,

    CONSTRAINT uk_ods_xhs_fund_ledger_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_ledger_batch_id
    ON ods.ods_xhs_fund_ledger_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_ledger_biz_no
    ON ods.ods_xhs_fund_ledger_raw ("业务单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_ledger_scene
    ON ods.ods_xhs_fund_ledger_raw ("动账场景");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_fund_ledger_source_file
    ON ods.ods_xhs_fund_ledger_raw (source_file_name);

COMMENT ON TABLE ods.ods_xhs_fund_ledger_raw IS 'ODS小红书资金账单明细原始表，保留平台导出的资金动账流水。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.batch_id IS '导入批次ID，关联 ods.ods_file_ingest_log.batch_id。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.source_sheet_name IS '来源工作表名称；小红书资金账单明细通常为“资金账单明细”。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.source_row_no IS '来源文件中的原始行号。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.row_hash IS '按来源文件、工作表、行号及原始字段计算的SHA256行哈希，用于幂等去重。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账时间" IS '来源文件字段“动账时间”，保留平台导出的原始动账时间值。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."业务单号" IS '来源文件字段“业务单号”，保留平台导出的原始业务关联单号。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账场景" IS '来源文件字段“动账场景”，保留平台导出的原始动账场景，例如结算入账、运费宝或申诉调账。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账方向" IS '来源文件字段“动账方向”，表示该流水的收入或支出方向，保留平台原始枚举值。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账金额" IS '来源文件字段“动账金额”，保留平台导出的原始金额值，单位为元。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账账户" IS '来源文件字段“动账账户”，保留平台导出的原始账户值。';
COMMENT ON COLUMN ods.ods_xhs_fund_ledger_raw."动账后余额" IS '来源文件字段“动账后余额”，表示本笔流水完成后的账户余额，单位为元。';
