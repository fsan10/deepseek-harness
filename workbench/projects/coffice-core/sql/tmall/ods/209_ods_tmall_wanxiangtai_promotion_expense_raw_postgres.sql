CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_wanxiangtai_promotion_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "记账时间" VARCHAR(64),
    "交易日期" VARCHAR(64),
    "收支类型" VARCHAR(64),
    "交易类型" VARCHAR(64),
    "操作金额(元)" VARCHAR(64),
    "操作后余额(元)" VARCHAR(64),
    "备注" TEXT,
    CONSTRAINT uk_ods_tmall_wanxiangtai_promotion_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_tmall_wanxiangtai_promotion_expense_raw IS '天猫万相台推广费资金流水ODS原始表，一行对应一条账户操作流水。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.batch_id IS '文件导入批次ID，关联ods.ods_file_ingest_log获取标准店铺。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.source_sheet_name IS '来源工作表名，CSV固定为CSV。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.row_hash IS '原始行SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw.ingest_time IS 'ODS入库时间。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."记账时间" IS '万相台账户记账时间，推广费统计日期来源。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."交易日期" IS '来源广告消耗交易日期，仅用于审计。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."收支类型" IS '来源收支方向，推广费只纳入支出。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."交易类型" IS '来源交易类型，推广费只纳入扣款。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."操作金额(元)" IS '万相台操作金额文本，推广费金额来源，单位元。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."操作后余额(元)" IS '操作后账户余额文本，单位元，仅用于审计。';
COMMENT ON COLUMN ods.ods_tmall_wanxiangtai_promotion_expense_raw."备注" IS '来源扣款说明。';

CREATE INDEX IF NOT EXISTS idx_ods_tmall_wanxiangtai_promotion_batch
    ON ods.ods_tmall_wanxiangtai_promotion_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_wanxiangtai_promotion_time
    ON ods.ods_tmall_wanxiangtai_promotion_expense_raw ("记账时间");
