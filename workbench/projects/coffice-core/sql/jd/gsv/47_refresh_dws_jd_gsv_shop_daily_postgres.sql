TRUNCATE TABLE dws.dws_jd_gsv_shop_daily;

INSERT INTO dws.dws_jd_gsv_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    gsv_amount,
    included_order_count,
    source_line_count,
    source_updated_at,
    updated_at
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(SUM(payable_amount), 2) AS gsv_amount,
    COUNT(*) AS included_order_count,
    SUM(source_line_count) AS source_line_count,
    MAX(source_updated_at) AS source_updated_at,
    NOW() AS updated_at
FROM dwd.dwd_jd_gsv_order_detail
WHERE stat_date IS NOT NULL
  AND COALESCE(order_status, '') NOT LIKE '(删除)%'
GROUP BY
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name;
