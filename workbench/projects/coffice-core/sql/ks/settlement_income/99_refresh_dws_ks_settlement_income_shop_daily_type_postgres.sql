TRUNCATE TABLE dws.dws_ks_settlement_income_shop_daily_type;

INSERT INTO dws.dws_ks_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name), d.shop_code, MAX(d.shop_name),
    t.income_type_code, MAX(t.income_type_name), ROUND(SUM(t.income_amount), 2),
    COUNT(*) FILTER (WHERE t.income_amount <> 0), MAX(d.source_updated_at), NOW()
FROM dwd.dwd_ks_settlement_income_event_detail d
CROSS JOIN LATERAL (VALUES
    ('order_paid', '订单实付', d.order_paid_amount),
    ('government_subsidy', '政府补贴', d.government_subsidy_amount),
    ('payment_marketing_subsidy', '支付营销补贴', d.payment_marketing_subsidy_amount),
    ('platform_subsidy', '平台补贴', d.platform_subsidy_amount),
    ('merchant_subsidy', '商家补贴', d.merchant_subsidy_amount),
    ('talent_subsidy', '达人补贴', d.talent_subsidy_amount)
) AS t(income_type_code, income_type_name, income_amount)
GROUP BY d.stat_date, d.platform_code, d.shop_code, t.income_type_code;

