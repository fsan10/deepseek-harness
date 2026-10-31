DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM dim.dim_expense_type expense
        JOIN dim.dim_account_entry_expense_type relation
          ON relation.expense_type_id = expense.id
        JOIN dim.dim_account_entry account_entry
          ON account_entry.id = relation.account_entry_id
        WHERE expense.code = 'EXP006'
          AND expense.name = '销售费用'
          AND account_entry.code = 'ACC006'
          AND account_entry.name = '入账-达人佣金费用'
          AND expense.is_active
          AND account_entry.is_active
    ) THEN
        RAISE EXCEPTION '缺少有效分类关系：销售费用 -> 入账-达人佣金费用';
    END IF;
END $$;

TRUNCATE TABLE dws.dws_bank_influencer_commission_account_daily;

INSERT INTO dws.dws_bank_influencer_commission_account_daily (
    stat_date, platform_code, platform_name, source_account_name,
    influencer_commission_amount, included_detail_count, source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    source_account_name,
    ROUND(SUM(directional_expense_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_bank_influencer_commission_statement_split_detail
WHERE expense_type_code = 'EXP006'
  AND expense_type_name = '销售费用'
  AND account_entry_code = 'ACC006'
  AND account_entry_name = '入账-达人佣金费用'
  AND directional_expense_amount <> 0
GROUP BY stat_date, platform_code, source_account_name;

