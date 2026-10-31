TRUNCATE TABLE dws.dws_tmall_gsv_shop_daily;

INSERT INTO dws.dws_tmall_gsv_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    gsv_amount, included_order_count, included_sub_order_count,
    source_updated_at, updated_at
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(SUM(buyer_paid_amount), 2),
    COUNT(DISTINCT main_order_no),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_gsv_order_detail
WHERE stat_date IS NOT NULL
  AND COALESCE(order_status, '') <> '交易关闭'
  AND COALESCE(refund_status, '') <> '退款成功'
  AND COALESCE(product_title, '') NOT LIKE '%购物金%'
GROUP BY stat_date, platform_code, platform_name, shop_code, shop_name;
