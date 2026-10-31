TRUNCATE TABLE ads.ads_settlement_net_company_shop_monthly;

INSERT INTO ads.ads_settlement_net_company_shop_monthly (
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    income_amount,
    expense_amount,
    display_expense_amount,
    settlement_net_amount,
    source_settlement_amount,
    validation_difference_amount,
    included_event_count,
    source_updated_at,
    updated_at
)
SELECT
    DATE_TRUNC('month', stat_date)::date AS stat_month,
    platform_code,
    MAX(platform_name) AS platform_name,
    company_code,
    MAX(company_name) AS company_name,
    shop_code,
    MAX(shop_name) AS shop_name,
    ROUND(SUM(income_amount), 2) AS income_amount,
    ROUND(SUM(expense_amount), 2) AS expense_amount,
    ROUND(SUM(display_expense_amount), 2) AS display_expense_amount,
    ROUND(SUM(income_amount) - SUM(expense_amount), 2) AS settlement_net_amount,
    ROUND(SUM(source_settlement_amount), 2) AS source_settlement_amount,
    ROUND(
        SUM(income_amount) - SUM(expense_amount) - SUM(source_settlement_amount),
        2
    ) AS validation_difference_amount,
    SUM(included_event_count) AS included_event_count,
    MAX(source_updated_at) AS source_updated_at,
    NOW() AS updated_at
FROM ads.ads_settlement_net_company_shop_daily
GROUP BY
    DATE_TRUNC('month', stat_date)::date,
    platform_code,
    company_code,
    shop_code;
