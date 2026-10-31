CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_bank_statement (
    id BIGSERIAL PRIMARY KEY,
    batch_id VARCHAR(32) NOT NULL,
    original_row_order INTEGER NOT NULL,
    account_no VARCHAR(64),
    account_name VARCHAR(256),
    currency VARCHAR(32),
    transaction_date DATE NOT NULL,
    transaction_time TIME,
    value_date DATE,
    transaction_type VARCHAR(200),
    debit_amount NUMERIC(18,2),
    credit_amount NUMERIC(18,2),
    balance NUMERIC(18,2),
    summary TEXT,
    transaction_no VARCHAR(128),
    raw_data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ods_bank_statement_batch_row UNIQUE (batch_id, original_row_order),
    CONSTRAINT ck_ods_bank_statement_has_amount CHECK (debit_amount IS NOT NULL OR credit_amount IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_ods_bank_statement_batch_date
    ON ods.ods_bank_statement (batch_id, transaction_date, original_row_order);
CREATE INDEX IF NOT EXISTS idx_ods_bank_statement_transaction_no
    ON ods.ods_bank_statement (transaction_no) WHERE transaction_no IS NOT NULL;

COMMENT ON TABLE ods.ods_bank_statement IS 'ODS层-银行直接下载的资金流水原始数据；导入后不可修改，完整源字段保存在raw_data。';
COMMENT ON COLUMN ods.ods_bank_statement.id IS 'ODS流水代理主键。';
COMMENT ON COLUMN ods.ods_bank_statement.batch_id IS '导入批次号，来源fund.import_record.batch_id。';
COMMENT ON COLUMN ods.ods_bank_statement.original_row_order IS '原始Excel数据行顺序，从1开始，不含表头。';
COMMENT ON COLUMN ods.ods_bank_statement.account_no IS '银行账号，来源原数据字段“账号”，按文本保存。';
COMMENT ON COLUMN ods.ods_bank_statement.account_name IS '银行账号名称，来源原数据字段“账号名称”。';
COMMENT ON COLUMN ods.ods_bank_statement.currency IS '币种，来源原数据字段“币种”。';
COMMENT ON COLUMN ods.ods_bank_statement.transaction_date IS '交易日期，来源原数据字段“交易日”。';
COMMENT ON COLUMN ods.ods_bank_statement.transaction_time IS '交易时间，来源原数据字段“交易时间”；源为空时保留NULL。';
COMMENT ON COLUMN ods.ods_bank_statement.value_date IS '起息日期，来源原数据字段“起息日”。';
COMMENT ON COLUMN ods.ods_bank_statement.transaction_type IS '银行交易类型，来源原数据字段“交易类型”。';
COMMENT ON COLUMN ods.ods_bank_statement.debit_amount IS '借方发生额，单位人民币元，来源“借方金额”；允许负数以原样保留银行冲正。';
COMMENT ON COLUMN ods.ods_bank_statement.credit_amount IS '贷方发生额，单位人民币元，来源“贷方金额”；允许负数以原样保留银行冲正。';
COMMENT ON COLUMN ods.ods_bank_statement.balance IS '交易后余额，单位人民币元，来源“余额”。';
COMMENT ON COLUMN ods.ods_bank_statement.summary IS '银行流水摘要，来源原数据字段“摘要”。';
COMMENT ON COLUMN ods.ods_bank_statement.transaction_no IS '银行流水号，来源原数据字段“流水号”，为空时保留NULL。';
COMMENT ON COLUMN ods.ods_bank_statement.raw_data IS '完整原始行JSON，键名逐字保留银行Excel全部源字段名和值。';
COMMENT ON COLUMN ods.ods_bank_statement.created_at IS 'ODS写入时间，带时区。';

