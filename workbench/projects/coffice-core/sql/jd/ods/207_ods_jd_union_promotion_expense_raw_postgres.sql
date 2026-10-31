CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_jd_union_promotion_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'Sheet1',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "流水单号" VARCHAR(128),
    "结算金额" VARCHAR(64),
    "费用时间" VARCHAR(64),
    "状态" VARCHAR(64),
    "结算时间" VARCHAR(64),
    "结算类型" VARCHAR(128),
    CONSTRAINT uk_ods_jd_union_promotion_expense_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_jd_union_promotion_expense_raw IS '京东联盟推广费结算ODS原始表，一行对应一条联盟结算流水。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.batch_id IS '文件导入批次ID，关联ods.ods_file_ingest_log获取标准店铺。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.source_sheet_name IS '来源Excel工作表名。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.row_hash IS '原始行SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw.ingest_time IS 'ODS入库时间。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."流水单号" IS '联盟流水编号，当前格式包含京东店铺账号ID。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."结算金额" IS '京东联盟结算金额文本，推广费金额来源，单位元。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."费用时间" IS '来源费用归属日期，仅用于审计。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."状态" IS '来源支付状态，当前口径不筛选。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."结算时间" IS '推广费统计日期来源。';
COMMENT ON COLUMN ods.ods_jd_union_promotion_expense_raw."结算类型" IS '来源现金结算类型。';

CREATE INDEX IF NOT EXISTS idx_ods_jd_union_promotion_expense_batch
    ON ods.ods_jd_union_promotion_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_jd_union_promotion_expense_settlement_time
    ON ods.ods_jd_union_promotion_expense_raw ("结算时间");
