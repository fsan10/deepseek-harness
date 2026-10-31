TRUNCATE TABLE dws.dws_tmall_settlement_income_shop_daily_type;

INSERT INTO dws.dws_tmall_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE bill_category
        WHEN '货款收入' THEN 'goods_income'
        ELSE 'tmall_' || MD5(bill_category)
    END,
    bill_category,
    ROUND(SUM(order_actual_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM dwd.dwd_tmall_settlement_income_event_detail
WHERE order_actual_amount <> 0
GROUP BY stat_date, platform_code, shop_code, bill_category;

