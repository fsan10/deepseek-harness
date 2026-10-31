CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_jd_tong_promotion_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'sheet1',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    "流水单号" VARCHAR(128),
    "投放账户名称" VARCHAR(255),
    "投放账户ID" VARCHAR(128),
    "投放日期" VARCHAR(64),
    "交易类型" VARCHAR(128),
    "支出" VARCHAR(64),
    "秒送门店ID" VARCHAR(128),
    "结算时间" VARCHAR(64),
    "结余" VARCHAR(64),
    "开票方式" VARCHAR(128),
    CONSTRAINT uk_ods_jd_tong_promotion_expense_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_jd_tong_promotion_expense_raw IS '京东通推广费流水ODS原始表，一行对应一条京东通投放账户结算流水。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.batch_id IS '文件导入批次ID，关联ods.ods_file_ingest_log获取标准店铺。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.source_sheet_name IS '来源Excel工作表名。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.row_hash IS '原始行SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw.ingest_time IS 'ODS入库时间。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."流水单号" IS '京东通流水唯一编号。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."投放账户名称" IS '来源投放账户名称。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."投放账户ID" IS '来源投放账户ID，非空时必须与批次标准店铺编码一致。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."投放日期" IS '来源广告投放日期，仅用于审计。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."交易类型" IS '来源交易类型，京东通推广费只纳入全站营销扣费。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."支出" IS '京东通支出金额文本，单位元。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."秒送门店ID" IS '来源秒送门店ID，仅用于审计。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."结算时间" IS '推广费统计时间来源。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."结余" IS '交易后账户结余文本，单位元。';
COMMENT ON COLUMN ods.ods_jd_tong_promotion_expense_raw."开票方式" IS '来源推广费开票方式。';

CREATE INDEX IF NOT EXISTS idx_ods_jd_tong_promotion_expense_batch
    ON ods.ods_jd_tong_promotion_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_jd_tong_promotion_expense_settlement_time
    ON ods.ods_jd_tong_promotion_expense_raw ("结算时间");
