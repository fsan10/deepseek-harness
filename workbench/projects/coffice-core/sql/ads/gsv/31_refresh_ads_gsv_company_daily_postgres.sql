TRUNCATE TABLE ads.ads_gsv_company_daily;

INSERT INTO ads.ads_gsv_company_daily (
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    gsv_amount,
    source_updated_at,
    updated_at
)
WITH platform_gsv_union AS (
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_douyin_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_tmall_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_jd_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_pdd_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_ks_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_wechat_channels_gsv_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        gsv_amount,
        source_updated_at
    FROM dws.dws_xhs_gsv_shop_daily
),
company_shop_daily AS (
    SELECT
        d.stat_date,
        d.platform_code,
        MAX(d.platform_name) AS platform_name,
        COALESCE(m.company_code, 'unmapped') AS company_code,
        COALESCE(m.company_name, '未匹配公司') AS company_name,
        d.shop_code,
        COALESCE(m.shop_name, MAX(d.shop_name), '未匹配店铺') AS shop_name,
        ROUND(SUM(d.gsv_amount), 2) AS gsv_amount,
        MAX(d.source_updated_at) AS source_updated_at
    FROM platform_gsv_union d
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
    gsv_amount,
    source_updated_at,
    NOW()
FROM company_shop_daily;
