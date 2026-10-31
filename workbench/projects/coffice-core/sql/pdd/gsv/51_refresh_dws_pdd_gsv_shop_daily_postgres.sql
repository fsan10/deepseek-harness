TRUNCATE TABLE dws.dws_pdd_gsv_shop_daily;

INSERT INTO dws.dws_pdd_gsv_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    merchant_received_amount,
    store_discount_amount,
    gsv_amount,
    included_order_count,
    source_updated_at,
    updated_at
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(SUM(merchant_received_amount), 2),
    ROUND(SUM(store_discount_amount), 2),
    ROUND(SUM(merchant_received_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_pdd_gsv_order_detail
WHERE stat_date IS NOT NULL
  AND BTRIM(order_status) IN ('已发货，待收货', '已收货')
  AND BTRIM(after_sale_status) IN (
      '无售后',
      '售后取消',
      '无售后或售后取消'
  )
GROUP BY
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name;
