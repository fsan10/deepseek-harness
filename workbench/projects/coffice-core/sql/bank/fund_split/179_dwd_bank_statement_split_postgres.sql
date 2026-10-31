CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_statement_split (
    id BIGSERIAL PRIMARY KEY,
    ods_id BIGINT NOT NULL REFERENCES ods.ods_bank_statement(id) ON DELETE CASCADE,
    batch_id VARCHAR(32) NOT NULL,
    split_index INTEGER NOT NULL DEFAULT 1,
    split_amount NUMERIC(18,2) NOT NULL,
    expense_type_id BIGINT REFERENCES dim.dim_expense_type(id) ON DELETE RESTRICT,
    account_entry_id BIGINT REFERENCES dim.dim_account_entry(id) ON DELETE RESTRICT,
    remark VARCHAR(500) NOT NULL DEFAULT '',
    is_adjusted BOOLEAN NOT NULL DEFAULT FALSE,
    original_amount NUMERIC(18,2) NOT NULL,
    adjusted_diff NUMERIC(18,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_dwd_statement_split UNIQUE (batch_id, ods_id, split_index),
    CONSTRAINT ck_dwd_statement_split_index CHECK (split_index >= 1),
    CONSTRAINT ck_dwd_statement_split_amount CHECK (split_amount > 0),
    CONSTRAINT ck_dwd_statement_split_original_amount CHECK (original_amount > 0)
);

CREATE INDEX IF NOT EXISTS idx_dwd_statement_split_batch ON dwd.dwd_statement_split (batch_id, ods_id, split_index);
CREATE INDEX IF NOT EXISTS idx_dwd_statement_split_classification ON dwd.dwd_statement_split (expense_type_id, account_entry_id);

CREATE OR REPLACE VIEW dwd.v_statement_split_detail AS
SELECT
    split.id AS split_id,
    split.ods_id,
    split.batch_id,
    split.split_index,
    ods.transaction_date,
    ods.transaction_time,
    ods.transaction_type,
    COALESCE(NULLIF(split.remark, ''), ods.summary) AS summary,
    ods.debit_amount,
    ods.credit_amount,
    ods.balance,
    ods.transaction_no,
    split.split_amount,
    split.original_amount,
    split.adjusted_diff,
    split.original_amount + split.adjusted_diff AS adjusted_amount,
    split.is_adjusted,
    split.expense_type_id,
    expense.name AS expense_type_name,
    split.account_entry_id,
    account.name AS account_entry_name,
    split.remark,
    split.updated_at,
    ods.account_name,
    ods.summary AS source_summary
FROM dwd.dwd_statement_split split
JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
LEFT JOIN dim.dim_expense_type expense ON expense.id = split.expense_type_id
LEFT JOIN dim.dim_account_entry account ON account.id = split.account_entry_id;

COMMENT ON TABLE dwd.dwd_statement_split IS 'DWD层-银行流水拆分、分类与调账明细；每行可追溯到唯一ODS流水。';
COMMENT ON COLUMN dwd.dwd_statement_split.id IS '拆分明细代理主键。';
COMMENT ON COLUMN dwd.dwd_statement_split.ods_id IS '来源ODS流水ID。';
COMMENT ON COLUMN dwd.dwd_statement_split.batch_id IS '导入批次号，冗余自ODS便于批次查询。';
COMMENT ON COLUMN dwd.dwd_statement_split.split_index IS '同一ODS流水内拆分序号，从1开始。';
COMMENT ON COLUMN dwd.dwd_statement_split.split_amount IS '拆分基准金额，单位人民币元；同ODS子行合计必须等于源流水绝对金额。';
COMMENT ON COLUMN dwd.dwd_statement_split.expense_type_id IS '财务费用类型ID；NULL表示待分类。';
COMMENT ON COLUMN dwd.dwd_statement_split.account_entry_id IS '财务入账科目ID；NULL表示待入账。';
COMMENT ON COLUMN dwd.dwd_statement_split.remark IS '财务备注，最长500字。';
COMMENT ON COLUMN dwd.dwd_statement_split.is_adjusted IS '是否发生手工调账。';
COMMENT ON COLUMN dwd.dwd_statement_split.original_amount IS '本拆分行调账前金额，单位人民币元，调账后保持不变。';
COMMENT ON COLUMN dwd.dwd_statement_split.adjusted_diff IS '调账差额，单位人民币元；调账后金额=original_amount+adjusted_diff。';
COMMENT ON COLUMN dwd.dwd_statement_split.created_at IS '拆分明细创建时间，带时区。';
COMMENT ON COLUMN dwd.dwd_statement_split.updated_at IS '拆分明细最后更新时间，带时区。';
COMMENT ON VIEW dwd.v_statement_split_detail IS 'DWD银行流水拆分展示视图，关联ODS与分类维度并计算调账后金额。';
COMMENT ON COLUMN dwd.v_statement_split_detail.account_name IS '银行账号名称，原样来源于ODS账号名称，不允许在本系统修改。';
COMMENT ON COLUMN dwd.v_statement_split_detail.source_summary IS '银行原始摘要，原样来源于ODS摘要，仅用于追溯。';
COMMENT ON COLUMN dwd.v_statement_split_detail.summary IS '当前展示摘要；优先使用DWD remark覆盖值，否则使用ODS原始摘要。';
