TRUNCATE TABLE dws.dws_ks_gsv_shop_daily;

INSERT INTO dws.dws_ks_gsv_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    gsv_amount,
    included_item_count,
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
    ROUND(SUM(paid_amount), 2),
    COUNT(*),
    COUNT(DISTINCT order_no),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_ks_gsv_order_item_detail
WHERE stat_date IS NOT NULL
  AND COALESCE(BTRIM(order_status), '') <> '交易关闭'
  AND COALESCE(BTRIM(after_sale_status), '') <> '退款成功'
GROUP BY
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name;
