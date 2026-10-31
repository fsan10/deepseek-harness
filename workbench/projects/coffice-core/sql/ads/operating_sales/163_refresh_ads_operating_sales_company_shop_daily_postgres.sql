TRUNCATE TABLE ads.ads_operating_sales_company_shop_daily;

INSERT INTO ads.ads_operating_sales_company_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    gmv_amount,
    refund_amount,
    refund_rate,
    transaction_order_count,
    sold_unit_count,
    transaction_unit_price,
    included_sub_order_count,
    source_updated_at,
    updated_at
)
WITH platform_operating_sales_union AS (
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_douyin_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_wechat_channels_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_jd_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_ks_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_xhs_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_pdd_operating_sales_order_item
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        main_order_no,
        sub_order_no,
        gmv_amount,
        refund_amount,
        sold_unit_count,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_tmall_operating_sales_order_item
), company_shop_daily AS (
    SELECT
        d.stat_date,
        d.platform_code,
        MAX(d.platform_name) AS platform_name,
        COALESCE(m.company_code, 'unmapped') AS company_code,
        COALESCE(m.company_name, '未匹配公司') AS company_name,
        d.shop_code,
        COALESCE(m.shop_name, MAX(d.shop_name), '未匹配店铺') AS shop_name,
        ROUND(SUM(d.gmv_amount), 2) AS gmv_amount,
        ROUND(SUM(d.refund_amount), 2) AS refund_amount,
        COUNT(DISTINCT d.main_order_no) AS transaction_order_count,
        ROUND(SUM(d.sold_unit_count), 2) AS sold_unit_count,
        SUM(d.included_sub_order_count) AS included_sub_order_count,
        MAX(d.source_updated_at) AS source_updated_at
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
        m.shop_name
)
SELECT
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    gmv_amount,
    refund_amount,
    COALESCE(ROUND(refund_amount / NULLIF(gmv_amount, 0), 6), 0),
    transaction_order_count,
    sold_unit_count,
    COALESCE(ROUND(gmv_amount / NULLIF(sold_unit_count, 0), 2), 0),
    included_sub_order_count,
    source_updated_at,
    NOW()
FROM company_shop_daily;
