TRUNCATE TABLE dws.dws_douyin_gsv_shop_daily;

INSERT INTO dws.dws_douyin_gsv_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    gsv_amount,
    included_sub_order_count,
    source_updated_at,
    updated_at
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(SUM(order_pay_amount + discount_total_amount - merchant_actual_discount_amount), 2) AS gsv_amount,
    COUNT(*) AS included_sub_order_count,
    MAX(source_updated_at) AS source_updated_at,
    NOW() AS updated_at
FROM dwd.dwd_douyin_gsv_order_detail
WHERE stat_date IS NOT NULL
  AND order_status IN ('已发货', '已完成')
  AND COALESCE(after_sale_status, '') NOT IN ('待收退货', '待退货', '售后待处理', '退款成功')
GROUP BY
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name;
