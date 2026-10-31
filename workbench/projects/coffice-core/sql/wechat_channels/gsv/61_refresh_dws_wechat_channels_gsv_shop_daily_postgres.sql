TRUNCATE TABLE dws.dws_wechat_channels_gsv_shop_daily;

INSERT INTO dws.dws_wechat_channels_gsv_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    actual_received_amount, activity_merchant_subsidy_amount, gsv_amount,
    included_order_count, source_line_count, source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, platform_name, shop_code, shop_name,
    ROUND(SUM(actual_received_amount), 2),
    ROUND(SUM(activity_merchant_subsidy_amount), 2),
    ROUND(SUM(actual_received_amount), 2),
    COUNT(*), SUM(source_line_count), MAX(source_updated_at), NOW()
FROM dwd.dwd_wechat_channels_gsv_order_detail
WHERE stat_date IS NOT NULL
  AND COALESCE(BTRIM(order_status), '') = '已完成'
  AND NOT (after_sale_statuses && ARRAY['退货退款完成', '退款完成']::TEXT[])
GROUP BY stat_date, platform_code, platform_name, shop_code, shop_name;
