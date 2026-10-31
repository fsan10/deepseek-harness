DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM fund.import_record
        WHERE status = 'success' AND is_submitted
    ) THEN
        RAISE EXCEPTION '没有成功且已提交的银行财务批次，停止刷新银行流水经营指标';
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
        RAISE EXCEPTION '已提交银行批次存在重复账号流水号，停止刷新银行流水经营指标';
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
        RAISE EXCEPTION '已提交银行DWD存在批次、分类关系或调账后金额异常';
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
           OR ABS(
                SUM(split.split_amount)
                - COALESCE(ABS(ods.debit_amount), ABS(ods.credit_amount))
              ) > 0.01
    ) THEN
        RAISE EXCEPTION '已提交银行流水存在DWD缺失、金额方向异常、拆分不平或调账不平';
    END IF;
END $$;

TRUNCATE TABLE dws.dws_bank_statement_account_daily_metric;

INSERT INTO dws.dws_bank_statement_account_daily_metric (
    stat_date,
    platform_code,
    platform_name,
    source_account_name,
    metric_group_code,
    metric_group_name,
    metric_code,
    metric_name,
    metric_amount,
    included_detail_count,
    source_updated_at,
    updated_at
)
WITH submitted_source AS (
    SELECT
        ods.transaction_date AS stat_date,
        COALESCE(NULLIF(BTRIM(ods.account_name), ''), '未提供银行账号名称') AS source_account_name,
        expense.name AS expense_type_name,
        account_entry.code AS account_entry_code,
        account_entry.name AS account_entry_name,
        CASE
            WHEN ods.debit_amount IS NOT NULL AND ods.credit_amount IS NULL
                THEN -SIGN(ods.debit_amount) * (split.original_amount + split.adjusted_diff)
            WHEN ods.credit_amount IS NOT NULL AND ods.debit_amount IS NULL
                THEN SIGN(ods.credit_amount) * (split.original_amount + split.adjusted_diff)
            ELSE 0
        END AS signed_amount,
        GREATEST(split.updated_at, record.submitted_at, ods.created_at) AS source_updated_at
    FROM dwd.dwd_statement_split split
    JOIN fund.import_record record
      ON record.batch_id = split.batch_id
     AND record.status = 'success'
     AND record.is_submitted
    JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
    JOIN dim.dim_expense_type expense ON expense.id = split.expense_type_id
    JOIN dim.dim_account_entry account_entry ON account_entry.id = split.account_entry_id
),
account_day_spine AS (
    SELECT
        stat_date,
        source_account_name,
        MAX(source_updated_at) AS source_updated_at
    FROM submitted_source
    GROUP BY stat_date, source_account_name
),
metric_definitions (
    metric_group_code,
    metric_group_name,
    metric_code,
    metric_name
) AS (
    VALUES
      ('revenue'::varchar, '收入'::varchar, 'main_business_revenue'::varchar, '主营业务收入'::varchar),
      ('revenue'::varchar, '收入'::varchar, 'non_operating_revenue'::varchar, '营业外收入'::varchar),
      ('expense'::varchar, '费用'::varchar, 'selling_expense'::varchar, '销售费用'::varchar),
      ('expense'::varchar, '费用'::varchar, 'administrative_expense'::varchar, '管理费用'::varchar),
      ('expense'::varchar, '费用'::varchar, 'tax_and_surcharge'::varchar, '税金及附加'::varchar),
      ('expense'::varchar, '费用'::varchar, 'personnel_cost'::varchar, '人员成本'::varchar),
      ('expense'::varchar, '费用'::varchar, 'financial_expense'::varchar, '财务费用'::varchar),
      ('expense'::varchar, '费用'::varchar, 'non_operating_expense'::varchar, '营业外支出'::varchar),
      ('cost'::varchar, '成本'::varchar, 'main_business_cost'::varchar, '主营业务成本'::varchar)
),
classified AS (
    SELECT
        source.stat_date,
        source.source_account_name,
        CASE source.expense_type_name
            WHEN '主营业务收入' THEN 'main_business_revenue'
            WHEN '营业外收入' THEN 'non_operating_revenue'
            WHEN '销售费用' THEN 'selling_expense'
            WHEN '管理费用' THEN 'administrative_expense'
            WHEN '税金及附加' THEN 'tax_and_surcharge'
            WHEN '人员成本' THEN 'personnel_cost'
            WHEN '财务费用' THEN 'financial_expense'
            WHEN '营业外支出' THEN 'non_operating_expense'
            WHEN '主营业务成本' THEN 'main_business_cost'
        END AS metric_code,
        ROUND(SUM(
            CASE
                WHEN source.expense_type_name IN ('主营业务收入', '营业外收入')
                    THEN source.signed_amount
                ELSE -source.signed_amount
            END
        ), 2) AS metric_amount,
        COUNT(*) AS included_detail_count,
        MAX(source.source_updated_at) AS source_updated_at
    FROM submitted_source source
    WHERE source.expense_type_name IN (
        '主营业务收入',
        '营业外收入',
        '销售费用',
        '管理费用',
        '税金及附加',
        '人员成本',
        '财务费用',
        '营业外支出',
        '主营业务成本'
    )
      AND NOT (
        source.expense_type_name = '主营业务收入'
        AND (
            source.account_entry_code = 'ACC002'
            OR source.account_entry_name IN ('平台提现', '入账-提现')
        )
      )
    GROUP BY
        source.stat_date,
        source.source_account_name,
        CASE source.expense_type_name
            WHEN '主营业务收入' THEN 'main_business_revenue'
            WHEN '营业外收入' THEN 'non_operating_revenue'
            WHEN '销售费用' THEN 'selling_expense'
            WHEN '管理费用' THEN 'administrative_expense'
            WHEN '税金及附加' THEN 'tax_and_surcharge'
            WHEN '人员成本' THEN 'personnel_cost'
            WHEN '财务费用' THEN 'financial_expense'
            WHEN '营业外支出' THEN 'non_operating_expense'
            WHEN '主营业务成本' THEN 'main_business_cost'
        END
)
SELECT
    spine.stat_date,
    'bank',
    '银行',
    spine.source_account_name,
    definition.metric_group_code,
    definition.metric_group_name,
    definition.metric_code,
    definition.metric_name,
    COALESCE(classified.metric_amount, 0),
    COALESCE(classified.included_detail_count, 0),
    GREATEST(spine.source_updated_at, classified.source_updated_at),
    NOW()
FROM account_day_spine spine
CROSS JOIN metric_definitions definition
LEFT JOIN classified
  ON classified.stat_date = spine.stat_date
 AND classified.source_account_name = spine.source_account_name
 AND classified.metric_code = definition.metric_code;
