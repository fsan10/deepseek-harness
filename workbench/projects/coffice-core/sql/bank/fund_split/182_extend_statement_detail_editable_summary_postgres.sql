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

COMMENT ON VIEW dwd.v_statement_split_detail IS 'DWD银行流水拆分展示视图；保留ODS账号和原摘要，使用DWD备注作为可编辑摘要覆盖值。';
COMMENT ON COLUMN dwd.v_statement_split_detail.account_name IS '银行账号名称，原样来源于ODS账号名称，不允许在本系统修改。';
COMMENT ON COLUMN dwd.v_statement_split_detail.source_summary IS '银行原始摘要，原样来源于ODS摘要，仅用于追溯。';
COMMENT ON COLUMN dwd.v_statement_split_detail.summary IS '当前展示摘要；优先使用DWD remark覆盖值，否则使用ODS原始摘要。';
