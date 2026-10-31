TRUNCATE TABLE ads.ads_operating_sales_traffic_company_shop_daily;

INSERT INTO ads.ads_operating_sales_traffic_company_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    traffic_content_type,
    traffic_channel,
    gmv_amount,
    included_sub_order_count,
    source_updated_at,
    updated_at
)
WITH platform_operating_sales_union AS (
    SELECT * FROM dws.dws_douyin_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_wechat_channels_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_jd_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_ks_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_xhs_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_pdd_operating_sales_order_item
    UNION ALL
    SELECT * FROM dws.dws_tmall_operating_sales_order_item
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    COALESCE(m.company_code, 'unmapped'),
    COALESCE(m.company_name, '未匹配公司'),
    d.shop_code,
    COALESCE(m.shop_name, MAX(d.shop_name), '未匹配店铺'),
    COALESCE(NULLIF(BTRIM(d.traffic_content_type), ''), '未提供'),
    COALESCE(NULLIF(BTRIM(d.traffic_channel), ''), '未提供'),
    ROUND(SUM(d.gmv_amount), 2),
    SUM(d.included_sub_order_count),
    MAX(d.source_updated_at),
    NOW()
FROM platform_operating_sales_union d
LEFT JOIN dim.dim_platform_shop_company m
  ON m.platform_code = d.platform_code
 AND m.shop_code = d.shop_code
 AND m.is_active
 AND d.stat_date >= m.valid_from
 AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
GROUP BY
    d.stat_date,
    d.platform_code,
    COALESCE(m.company_code, 'unmapped'),
    COALESCE(m.company_name, '未匹配公司'),
    d.shop_code,
    m.shop_name,
    COALESCE(NULLIF(BTRIM(d.traffic_content_type), ''), '未提供'),
    COALESCE(NULLIF(BTRIM(d.traffic_channel), ''), '未提供');
