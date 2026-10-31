TRUNCATE TABLE dws.dws_ks_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_ks_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name), d.shop_code, MAX(d.shop_name),
    t.expense_type_code, MAX(t.expense_type_name), ROUND(SUM(t.expense_amount), 2),
    COUNT(*) FILTER (WHERE t.expense_amount <> 0), MAX(d.source_updated_at), NOW()
FROM dwd.dwd_ks_settlement_expense_event_detail d
CROSS JOIN LATERAL (VALUES
    ('order_refund', '订单退款', d.order_refund_amount),
    ('technical_service_fee', '技术服务费', d.technical_service_fee_amount),
    ('presale_technical_service_fee', '预售增收技术服务费', d.presale_technical_service_fee_amount),
    ('talent_commission', '达人佣金', d.talent_commission_amount),
    ('leader_commission', '团长佣金', d.leader_commission_amount),
    ('earner_commission', '快赚客佣金', d.earner_commission_amount),
    ('service_provider_commission', '服务商佣金', d.service_provider_commission_amount),
    ('other_fee', '其他收费', d.other_fee_amount)
) AS t(expense_type_code, expense_type_name, expense_amount)
GROUP BY d.stat_date, d.platform_code, d.shop_code, t.expense_type_code;

