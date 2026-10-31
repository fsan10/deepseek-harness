TRUNCATE TABLE dws.dws_douyin_settlement_income_shop_daily_type;

INSERT INTO dws.dws_douyin_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    d.shop_code,
    MAX(d.shop_name),
    t.income_type_code,
    MAX(t.income_type_name),
    ROUND(SUM(t.income_amount), 2),
    COUNT(*) FILTER (WHERE t.income_amount <> 0),
    MAX(d.source_updated_at),
    NOW()
FROM dwd.dwd_douyin_settlement_income_event_detail d
CROSS JOIN LATERAL (VALUES
    ('user_payment', '用户实付', d.user_payment_amount),
    ('platform_subsidy', '平台补贴', d.platform_subsidy_amount),
    ('other_platform_subsidy', '其他平台补贴', d.other_platform_subsidy_amount),
    ('government_platform_advance', '政府补贴平台垫资', d.government_platform_advance_amount),
    ('creator_subsidy', '达人补贴', d.creator_subsidy_amount),
    ('douyin_pay_subsidy', '抖音支付补贴', d.douyin_pay_subsidy_amount),
    ('douyin_monthly_pay_subsidy', '抖音月付营销补贴', d.douyin_monthly_pay_subsidy_amount),
    ('bank_subsidy', '银行补贴', d.bank_subsidy_amount),
    ('trade_in_deduction', '以旧换新抵扣', d.trade_in_deduction_amount),
    ('platform_shipping_subsidy', '平台补贴运费', d.platform_shipping_subsidy_amount)
) AS t(income_type_code, income_type_name, income_amount)
GROUP BY d.stat_date, d.platform_code, d.shop_code, t.income_type_code;

