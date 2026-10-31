TRUNCATE TABLE dws.dws_douyin_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_douyin_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name), d.shop_code, MAX(d.shop_name),
    t.expense_type_code, MAX(t.expense_type_name), ROUND(SUM(t.expense_amount), 2),
    COUNT(*) FILTER (WHERE t.expense_amount <> 0), MAX(d.source_updated_at), NOW()
FROM dwd.dwd_douyin_settlement_expense_event_detail d
CROSS JOIN LATERAL (VALUES
    ('platform_service_fee', '平台服务费', d.platform_service_fee_amount),
    ('creator_commission', '达人佣金', d.creator_commission_amount),
    ('service_provider_commission', '服务商佣金', d.service_provider_commission_amount),
    ('channel_share', '渠道分成', d.channel_share_amount),
    ('merchant_recruitment_service_fee', '招商服务费', d.merchant_recruitment_service_fee_amount),
    ('offsite_promotion_fee', '站外推广费', d.offsite_promotion_fee_amount),
    ('other_share', '其他分成', d.other_share_amount)
) AS t(expense_type_code, expense_type_name, expense_amount)
GROUP BY d.stat_date, d.platform_code, d.shop_code, t.expense_type_code;

