CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_pdd_promotion_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'Sheet0',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "时间" VARCHAR(64),
    "资金类型" VARCHAR(64),
    "流水类型" VARCHAR(64),
    "店铺名称" VARCHAR(255),
    "交易金额" VARCHAR(64),
    "余额" VARCHAR(64),
    "交易摘要" TEXT,
    CONSTRAINT uk_ods_pdd_promotion_expense_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_pdd_promotion_expense_raw IS '拼多多推广费资金流水ODS原始表，一行对应来源文件中的一条店铺资金流水。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.batch_id IS '文件导入批次ID，关联ods.ods_file_ingest_log获取标准店铺。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.source_sheet_name IS '来源Excel工作表名。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.row_hash IS '原始行SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw.ingest_time IS 'ODS入库时间。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."时间" IS '来源资金流水发生时间。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."资金类型" IS '来源资金类型枚举，推广费口径要求为现金。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."流水类型" IS '来源流水方向枚举，推广费口径要求为支出。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."店铺名称" IS '来源文件店铺名称，仅用于与批次标准店铺核对。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."交易金额" IS '来源交易金额文本，单位元。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."余额" IS '交易后账户余额文本，单位元，仅用于审计。';
COMMENT ON COLUMN ods.ods_pdd_promotion_expense_raw."交易摘要" IS '来源推广支出组成说明。';

CREATE INDEX IF NOT EXISTS idx_ods_pdd_promotion_expense_batch
    ON ods.ods_pdd_promotion_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_pdd_promotion_expense_time
    ON ods.ods_pdd_promotion_expense_raw ("时间");
