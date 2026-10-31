DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM fund.import_record
        WHERE status = 'success' AND is_submitted
    ) THEN
        RAISE EXCEPTION '没有成功且已提交的银行财务批次，停止刷新总营收';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dwd.dwd_statement_split split
        JOIN fund.import_record record ON record.batch_id = split.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY split.batch_id
        HAVING ABS(SUM(split.adjusted_diff)) > 0.01
    ) THEN
        RAISE EXCEPTION '已提交银行批次调账净差不为0';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ods.ods_bank_statement ods
        JOIN fund.import_record record ON record.batch_id = ods.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY ods.account_no, ods.transaction_no
        HAVING COUNT(DISTINCT ods.batch_id) > 1
    ) THEN
        RAISE EXCEPTION '已提交银行批次存在重复账号流水号，停止刷新总营收';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dwd.dwd_statement_split split
        JOIN fund.import_record record ON record.batch_id = split.batch_id
        JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
        WHERE record.status = 'success' AND record.is_submitted
          AND (
            split.batch_id <> ods.batch_id
            OR split.expense_type_id IS NULL
            OR split.account_entry_id IS NULL
            OR split.original_amount + split.adjusted_diff <= 0
            OR NOT EXISTS (
                SELECT 1 FROM dim.dim_account_entry_expense_type relation
                WHERE relation.expense_type_id = split.expense_type_id
                  AND relation.account_entry_id = split.account_entry_id
            )
          )
    ) THEN
        RAISE EXCEPTION '已提交银行DWD存在批次、分类关系或调账后金额异常';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM ods.ods_bank_statement ods
        JOIN fund.import_record record ON record.batch_id = ods.batch_id
        LEFT JOIN dwd.dwd_statement_split split
          ON split.ods_id = ods.id AND split.batch_id = ods.batch_id
        WHERE record.status = 'success' AND record.is_submitted
        GROUP BY ods.id, ods.debit_amount, ods.credit_amount
        HAVING COUNT(split.id) = 0
           OR (ods.debit_amount IS NULL) = (ods.credit_amount IS NULL)
           OR ABS(SUM(split.split_amount) - COALESCE(ABS(ods.debit_amount), ABS(ods.credit_amount))) > 0.01
    ) THEN
        RAISE EXCEPTION '已提交银行流水存在DWD缺失、金额方向异常、拆分不平或调账不平';
    END IF;
END $$;

TRUNCATE TABLE dws.dws_bank_total_revenue_account_daily_type;

INSERT INTO dws.dws_bank_total_revenue_account_daily_type (
    stat_date, platform_code, platform_name, source_account_name,
    revenue_type_code, revenue_type_name, revenue_amount,
    included_detail_count, source_updated_at, updated_at
)
WITH submitted_source AS (
    SELECT
        ods.transaction_date AS stat_date,
        COALESCE(NULLIF(BTRIM(ods.account_name), ''), '未提供银行账号名称') AS source_account_name,
        ods.debit_amount,
        ods.credit_amount,
        split.expense_type_id,
        split.account_entry_id,
        split.original_amount + split.adjusted_diff AS adjusted_amount,
        GREATEST(split.updated_at, record.submitted_at, ods.created_at) AS source_updated_at
    FROM dwd.dwd_statement_split split
    JOIN fund.import_record record
      ON record.batch_id = split.batch_id
     AND record.status = 'success'
     AND record.is_submitted
    JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
),
account_day_spine AS (
    SELECT stat_date, source_account_name, MAX(source_updated_at) AS source_updated_at
    FROM submitted_source
    GROUP BY stat_date, source_account_name
),
revenue_types(revenue_type_code, revenue_type_name) AS (
    VALUES
      ('main_business_revenue'::varchar, '主营业务收入'::varchar),
      ('non_operating_revenue'::varchar, '营业外收入'::varchar)
),
classified AS (
    SELECT
        source.stat_date,
        source.source_account_name,
        CASE expense.name
            WHEN '主营业务收入' THEN 'main_business_revenue'
            WHEN '营业外收入' THEN 'non_operating_revenue'
        END AS revenue_type_code,
        ROUND(SUM(
            CASE
                WHEN source.debit_amount IS NOT NULL AND source.credit_amount IS NULL
                    THEN -SIGN(source.debit_amount) * source.adjusted_amount
                WHEN source.credit_amount IS NOT NULL AND source.debit_amount IS NULL
                    THEN SIGN(source.credit_amount) * source.adjusted_amount
                ELSE 0
            END
        ), 2) AS revenue_amount,
        COUNT(*) AS detail_count,
        MAX(source.source_updated_at) AS source_updated_at
    FROM submitted_source source
    JOIN dim.dim_expense_type expense ON expense.id = source.expense_type_id
    JOIN dim.dim_account_entry account_entry ON account_entry.id = source.account_entry_id
    WHERE expense.name IN ('主营业务收入', '营业外收入')
      AND NOT (
        expense.name = '主营业务收入'
        AND (account_entry.code = 'ACC002' OR account_entry.name IN ('平台提现', '入账-提现'))
      )
    GROUP BY
        source.stat_date,
        source.source_account_name,
        CASE expense.name
            WHEN '主营业务收入' THEN 'main_business_revenue'
            WHEN '营业外收入' THEN 'non_operating_revenue'
        END
)
SELECT
    spine.stat_date,
    'bank',
    '银行',
    spine.source_account_name,
    revenue_types.revenue_type_code,
    revenue_types.revenue_type_name,
    COALESCE(classified.revenue_amount, 0),
    COALESCE(classified.detail_count, 0),
    GREATEST(spine.source_updated_at, classified.source_updated_at),
    NOW()
FROM account_day_spine spine
CROSS JOIN revenue_types
LEFT JOIN classified
  ON classified.stat_date = spine.stat_date
 AND classified.source_account_name = spine.source_account_name
 AND classified.revenue_type_code = revenue_types.revenue_type_code;
