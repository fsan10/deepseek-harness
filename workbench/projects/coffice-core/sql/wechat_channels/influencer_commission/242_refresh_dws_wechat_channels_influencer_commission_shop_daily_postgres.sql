TRUNCATE TABLE dws.dws_wechat_channels_influencer_commission_shop_daily;

INSERT INTO dws.dws_wechat_channels_influencer_commission_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    creator_commission_amount, agency_service_fee_amount,
    influencer_commission_amount, included_event_count, source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    ROUND(COALESCE(SUM(directional_expense_amount) FILTER (WHERE movement_type = '达人佣金'), 0), 2),
    ROUND(COALESCE(SUM(directional_expense_amount) FILTER (WHERE movement_type = '带货机构服务费'), 0), 2),
    ROUND(SUM(directional_expense_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_wechat_channels_influencer_commission_event_detail
WHERE movement_type IN ('达人佣金', '带货机构服务费')
  AND directional_expense_amount <> 0
GROUP BY stat_date, platform_code, shop_code;
