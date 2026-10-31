TRUNCATE TABLE dws.dws_wechat_channels_settlement_net_shop_daily;

INSERT INTO dws.dws_wechat_channels_settlement_net_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount,
    included_event_count, source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    ROUND(SUM(income_amount), 2),
    ROUND(SUM(expense_amount), 2),
    ROUND(SUM(income_amount) - SUM(expense_amount), 2),
    ROUND(SUM(source_settlement_amount), 2),
    ROUND(SUM(income_amount) - SUM(expense_amount) - SUM(source_settlement_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM dwd.dwd_wechat_channels_settlement_net_event_detail
GROUP BY stat_date, platform_code, shop_code;

