TRUNCATE TABLE dws.dws_pdd_promotion_expense_shop_daily;

INSERT INTO dws.dws_pdd_promotion_expense_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    cash_outflow_amount,
    promotion_expense_amount,
    included_detail_count,
    excluded_detail_count,
    source_updated_at,
    updated_at
)
SELECT
    expense_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(COALESCE(SUM(transaction_amount) FILTER (
        WHERE fund_type = '现金' AND flow_type = '支出'
    ), 0), 2),
    ROUND(COALESCE(SUM(transaction_amount) FILTER (
        WHERE fund_type = '现金' AND flow_type = '支出'
    ), 0), 2),
    COUNT(*) FILTER (WHERE fund_type = '现金' AND flow_type = '支出'),
    COUNT(*) FILTER (WHERE fund_type IS DISTINCT FROM '现金' OR flow_type IS DISTINCT FROM '支出'),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_pdd_promotion_expense_detail
WHERE expense_date IS NOT NULL
  AND transaction_amount IS NOT NULL
GROUP BY expense_date, platform_code, platform_name, shop_code, shop_name;
