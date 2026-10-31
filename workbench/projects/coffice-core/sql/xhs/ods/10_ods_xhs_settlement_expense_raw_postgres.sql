CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_xhs_settlement_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" VARCHAR(128),
    "业务款项" VARCHAR(128),
    "业务单号" VARCHAR(128),
    "结算时间" VARCHAR(64),
    "结算账户" VARCHAR(128),
    "动账金额" VARCHAR(64),
    "佣金金额" VARCHAR(64),
    "备注" TEXT,

    CONSTRAINT uk_ods_xhs_settlement_expense_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_xhs_settlement_expense_raw SET source_sheet_name = 'CSV' WHERE source_sheet_name IS NULL OR source_sheet_name = '';
ALTER TABLE ods.ods_xhs_settlement_expense_raw ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';
ALTER TABLE ods.ods_xhs_settlement_expense_raw ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_xhs_expense_batch_id ON ods.ods_xhs_settlement_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_xhs_expense_order_no ON ods.ods_xhs_settlement_expense_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_expense_biz_no ON ods.ods_xhs_settlement_expense_raw ("业务单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_expense_source_file ON ods.ods_xhs_settlement_expense_raw (source_file_name);

COMMENT ON TABLE ods.ods_xhs_settlement_expense_raw IS 'ODS小红书其他服务款/结算支出原始表';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.source_sheet_name IS '来源工作表';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."业务款项" IS '来源文件字段“业务款项”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."业务单号" IS '来源文件字段“业务单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."结算时间" IS '来源文件字段“结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."结算账户" IS '来源文件字段“结算账户”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."动账金额" IS '来源文件字段“动账金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."佣金金额" IS '来源文件字段“佣金金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
