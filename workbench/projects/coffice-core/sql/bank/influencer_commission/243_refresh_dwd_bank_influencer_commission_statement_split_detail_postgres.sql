DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM fund.import_record
        WHERE status = 'success' AND is_submitted
    ) THEN
        RAISE EXCEPTION '没有成功且已提交的银行财务批次，停止刷新达人佣金';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dwd.dwd_statement_split split
        JOIN fund.import_record record ON record.batch_id = split.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY split.batch_id
        HAVING ABS(SUM(split.adjusted_diff)) > 0.01
    ) THEN
        RAISE EXCEPTION '银行已提交批次调账净差不为0';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ods.ods_bank_statement ods
        JOIN fund.import_record record ON record.batch_id = ods.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY ods.account_no, ods.transaction_no
        HAVING COUNT(DISTINCT ods.batch_id) > 1
    ) THEN
        RAISE EXCEPTION '银行已提交批次存在重复账号流水号';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dwd.dwd_statement_split split
        JOIN fund.import_record record ON record.batch_id = split.batch_id
        JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
        WHERE record.status = 'success'
          AND record.is_submitted
          AND (
            split.batch_id <> ods.batch_id
            OR split.expense_type_id IS NULL
            OR split.account_entry_id IS NULL
            OR split.original_amount + split.adjusted_diff <= 0
            OR NOT EXISTS (
                SELECT 1
                FROM dim.dim_account_entry_expense_type relation
                WHERE relation.expense_type_id = split.expense_type_id
                  AND relation.account_entry_id = split.account_entry_id
            )
          )
    ) THEN
        RAISE EXCEPTION '银行已提交DWD存在批次、分类关系或调账后金额异常';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ods.ods_bank_statement ods
        JOIN fund.import_record record ON record.batch_id = ods.batch_id
        LEFT JOIN dwd.dwd_statement_split split
          ON split.ods_id = ods.id
         AND split.batch_id = ods.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY ods.id, ods.debit_amount, ods.credit_amount
        HAVING COUNT(split.id) = 0
           OR (ods.debit_amount IS NULL) = (ods.credit_amount IS NULL)
           OR ABS(SUM(split.split_amount) - COALESCE(ABS(ods.debit_amount), ABS(ods.credit_amount))) > 0.01
    ) THEN
        RAISE EXCEPTION '银行已提交流水存在DWD缺失、金额方向异常或拆分不平';
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_bank_influencer_commission_statement_split_detail;

INSERT INTO dwd.dwd_bank_influencer_commission_statement_split_detail (
    source_split_id, source_ods_id, source_batch_id, split_index,
    platform_code, platform_name, stat_date, transaction_time,
    source_account_no, source_account_name, transaction_type, summary,
    transaction_no, debit_amount, credit_amount, split_amount,
    original_amount, adjusted_diff, adjusted_amount, expense_type_code,
    expense_type_name, account_entry_code, account_entry_name,
    directional_expense_amount, is_adjusted, source_updated_at, updated_at
)
SELECT
    split.id,
    split.ods_id,
    split.batch_id,
    split.split_index,
    'bank',
    '银行',
    ods.transaction_date,
    ods.transaction_time,
    NULLIF(BTRIM(ods.account_no), ''),
    COALESCE(NULLIF(BTRIM(ods.account_name), ''), '未提供银行账号名称'),
    NULLIF(BTRIM(ods.transaction_type), ''),
    NULLIF(BTRIM(ods.summary), ''),
    NULLIF(BTRIM(ods.transaction_no), ''),
    ods.debit_amount,
    ods.credit_amount,
    split.split_amount,
    split.original_amount,
    split.adjusted_diff,
    split.original_amount + split.adjusted_diff,
    expense.code,
    expense.name,
    account_entry.code,
    account_entry.name,
    CASE
        WHEN ods.debit_amount IS NOT NULL AND ods.credit_amount IS NULL
            THEN ROUND(SIGN(ods.debit_amount) * (split.original_amount + split.adjusted_diff), 2)
        WHEN ods.credit_amount IS NOT NULL AND ods.debit_amount IS NULL
            THEN ROUND(-SIGN(ods.credit_amount) * (split.original_amount + split.adjusted_diff), 2)
        ELSE 0
    END,
    split.is_adjusted,
    GREATEST(split.updated_at, record.submitted_at, ods.created_at),
    NOW()
FROM dwd.dwd_statement_split split
JOIN fund.import_record record
  ON record.batch_id = split.batch_id
 AND record.status = 'success'
 AND record.is_submitted
JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
JOIN dim.dim_expense_type expense ON expense.id = split.expense_type_id
JOIN dim.dim_account_entry account_entry ON account_entry.id = split.account_entry_id;

