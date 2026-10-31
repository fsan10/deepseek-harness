TRUNCATE TABLE dws.dws_tmall_settlement_fund_net_shop_daily;

INSERT INTO dws.dws_tmall_settlement_fund_net_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount,
    included_event_count, source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    ROUND(COALESCE(SUM(income_amount) FILTER (WHERE income_eligible), 0), 2),
    ROUND(COALESCE(SUM(expense_amount) FILTER (WHERE expense_eligible), 0), 2),
    ROUND(
        COALESCE(SUM(income_amount) FILTER (WHERE income_eligible), 0)
        - COALESCE(SUM(expense_amount) FILTER (WHERE expense_eligible), 0),
        2
    ),
    ROUND(
        COALESCE(SUM(signed_amount) FILTER (WHERE income_eligible OR expense_eligible), 0),
        2
    ),
    ROUND(
        COALESCE(SUM(income_amount) FILTER (WHERE income_eligible), 0)
        - COALESCE(SUM(expense_amount) FILTER (WHERE expense_eligible), 0)
        - COALESCE(SUM(signed_amount) FILTER (WHERE income_eligible OR expense_eligible), 0),
        2
    ),
    COUNT(*) FILTER (WHERE income_eligible OR expense_eligible),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_settlement_fund_event_detail
GROUP BY stat_date, platform_code, shop_code;
