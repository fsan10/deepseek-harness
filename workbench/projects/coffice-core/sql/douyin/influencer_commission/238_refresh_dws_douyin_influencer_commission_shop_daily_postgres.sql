TRUNCATE TABLE dws.dws_douyin_influencer_commission_shop_daily;

INSERT INTO dws.dws_douyin_influencer_commission_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    creator_commission_amount, recruitment_service_fee_amount,
    influencer_commission_amount, included_event_count, source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    ROUND(SUM(creator_commission_amount), 2),
    ROUND(SUM(recruitment_service_fee_amount), 2),
    ROUND(SUM(creator_commission_amount + recruitment_service_fee_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_douyin_influencer_commission_event_detail
WHERE creator_commission_amount + recruitment_service_fee_amount <> 0
GROUP BY stat_date, platform_code, shop_code;

