TRUNCATE TABLE dws.dws_ks_influencer_commission_shop_daily;

INSERT INTO dws.dws_ks_influencer_commission_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    talent_commission_amount, leader_commission_amount, other_fee_amount,
    influencer_commission_amount, included_event_count,
    included_refund_event_count, source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    ROUND(SUM(talent_commission_amount), 2),
    ROUND(SUM(leader_commission_amount), 2),
    ROUND(SUM(other_fee_amount), 2),
    ROUND(SUM(talent_commission_amount + leader_commission_amount + other_fee_amount), 2),
    COUNT(*),
    COUNT(*) FILTER (WHERE order_refund_amount > 0),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_ks_influencer_commission_event_detail
WHERE talent_commission_amount + leader_commission_amount + other_fee_amount <> 0
GROUP BY stat_date, platform_code, shop_code;

