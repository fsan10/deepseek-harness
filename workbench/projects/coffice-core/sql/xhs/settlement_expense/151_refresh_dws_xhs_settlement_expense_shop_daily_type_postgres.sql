TRUNCATE TABLE dws.dws_xhs_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_xhs_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE business_item
        WHEN '运费宝' THEN 'shipping_protection'
        ELSE 'xhs_' || MD5(business_item)
    END,
    business_item, ROUND(SUM(expense_amount), 2), COUNT(*),
    MAX(source_updated_at), NOW()
FROM dwd.dwd_xhs_settlement_expense_event_detail
GROUP BY stat_date, platform_code, shop_code, business_item;

