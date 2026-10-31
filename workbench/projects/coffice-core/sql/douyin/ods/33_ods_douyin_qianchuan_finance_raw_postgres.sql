CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_douyin_qianchuan_finance_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'data',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "日期" VARCHAR(64),
    "余额总消耗(元)" VARCHAR(64),
    "非赠款消耗(元)" VARCHAR(64),
    "赠款消耗(元)" VARCHAR(64),
    "消返红包消耗(元)" VARCHAR(64),
    "立减红包消耗(元)" VARCHAR(64),
    "共享钱包消耗(元)" VARCHAR(64),
    "共享赠款消耗(元)" VARCHAR(64),
    "总存入(元)" VARCHAR(64),
    "总转入(元)" VARCHAR(64),
    "总转出(元)" VARCHAR(64),
    "总余额(元)" VARCHAR(64),
    "赠款余额(元)" VARCHAR(64),
    "非赠款余额(元)" VARCHAR(64),

    CONSTRAINT uk_ods_douyin_qianchuan_finance_row_hash UNIQUE (row_hash)
);

COMMENT ON TABLE ods.ods_douyin_qianchuan_finance_raw IS '抖音千川财务流水ODS原始表，按文件表头保留每日消耗、存入、转入转出和余额字段。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.batch_id IS '文件导入批次ID，可关联ods_file_ingest_log。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.source_sheet_name IS '来源Excel工作表名。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.source_row_no IS '数据在来源文件中的原始行号。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.row_hash IS '原始行内容SHA256摘要，用于幂等去重。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."日期" IS '千川财务流水业务日期。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."余额总消耗(元)" IS '千川余额总消耗，单位元，仅作来源审计。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."非赠款消耗(元)" IS '千川非赠款消耗，抖音推广费金额来源，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."赠款消耗(元)" IS '千川赠款消耗，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."消返红包消耗(元)" IS '千川消返红包消耗，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."立减红包消耗(元)" IS '千川立减红包消耗，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."共享钱包消耗(元)" IS '千川共享钱包消耗，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."共享赠款消耗(元)" IS '千川共享赠款消耗，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."总存入(元)" IS '千川账户总存入，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."总转入(元)" IS '千川账户总转入，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."总转出(元)" IS '千川账户总转出，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."总余额(元)" IS '千川账户总余额，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."赠款余额(元)" IS '千川账户赠款余额，单位元。';
COMMENT ON COLUMN ods.ods_douyin_qianchuan_finance_raw."非赠款余额(元)" IS '千川账户非赠款余额，单位元。';

CREATE INDEX IF NOT EXISTS idx_ods_douyin_qianchuan_finance_date
    ON ods.ods_douyin_qianchuan_finance_raw ("日期");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_qianchuan_finance_batch
    ON ods.ods_douyin_qianchuan_finance_raw (batch_id);
