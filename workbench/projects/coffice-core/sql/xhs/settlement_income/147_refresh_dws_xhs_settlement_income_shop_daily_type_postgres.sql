TRUNCATE TABLE dws.dws_xhs_settlement_income_shop_daily_type;

INSERT INTO dws.dws_xhs_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE transaction_type
        WHEN '结算入账' THEN 'settlement_credit'
        WHEN '退款' THEN 'refund'
        WHEN '申诉调账' THEN 'appeal_adjustment_income'
        ELSE 'xhs_' || MD5(transaction_type)
    END,
    transaction_type, ROUND(SUM(income_amount), 2), COUNT(*),
    MAX(source_updated_at), NOW()
FROM dwd.dwd_xhs_settlement_income_event_detail
GROUP BY stat_date, platform_code, shop_code, transaction_type;
