TRUNCATE TABLE dws.dws_jd_settlement_income_shop_daily_type;

INSERT INTO dws.dws_jd_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE fee_item_name
        WHEN '货款' THEN 'goods_payment'
        WHEN '代收配送费' THEN 'delivery_fee_collected'
        WHEN '佣金' THEN 'commission'
        WHEN '交易服务费' THEN 'transaction_service_fee'
        WHEN '运费保险服务费' THEN 'shipping_insurance_service_fee'
        WHEN '商品保险服务费' THEN 'product_insurance_service_fee'
        WHEN '综合违约金' THEN 'comprehensive_penalty'
        WHEN '随单送的京豆' THEN 'order_jingdou'
        ELSE 'jd_' || MD5(fee_item_name)
    END,
    fee_item_name,
    ROUND(SUM(income_amount), 2),
    COUNT(*) FILTER (WHERE income_amount <> 0),
    MAX(source_updated_at), NOW()
FROM dwd.dwd_jd_settlement_income_document_detail
WHERE income_amount <> 0
GROUP BY stat_date, platform_code, shop_code, fee_item_name;

