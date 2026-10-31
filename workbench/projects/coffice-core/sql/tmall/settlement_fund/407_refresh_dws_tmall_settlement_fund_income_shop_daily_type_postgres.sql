TRUNCATE TABLE dws.dws_tmall_settlement_fund_income_shop_daily_type;

INSERT INTO dws.dws_tmall_settlement_fund_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    'fund_goods_income',
    '货款收入',
    ROUND(SUM(income_amount), 2),
    COUNT(*) FILTER (WHERE income_amount <> 0),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_settlement_fund_event_detail
WHERE income_eligible
GROUP BY stat_date, platform_code, shop_code;
