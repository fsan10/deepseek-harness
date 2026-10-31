TRUNCATE TABLE dws.dws_tmall_settlement_fund_expense_shop_daily_type;

INSERT INTO dws.dws_tmall_settlement_fund_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    expense_type_code,
    MAX(expense_type_name),
    ROUND(SUM(expense_amount), 2),
    COUNT(*) FILTER (WHERE expense_amount <> 0),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_settlement_fund_event_detail
WHERE expense_eligible
GROUP BY stat_date, platform_code, shop_code, expense_type_code;
