TRUNCATE TABLE ads.ads_platform_main_business_income_company_shop_daily_category;

INSERT INTO ads.ads_platform_main_business_income_company_shop_daily_category (
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    primary_category_code,
    primary_category_name,
    secondary_category_code,
    secondary_category_name,
    source_document_type,
    income_amount,
    included_detail_count,
    source_updated_at,
    updated_at
)
WITH platform_dws AS (
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_douyin_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_ks_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_jd_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_tmall_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_pdd_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_wechat_channels_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        income_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_xhs_operating_flow_shop_daily_scene
    WHERE operating_treatment='income'
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    COALESCE(m.company_code, 'unmapped'),
    COALESCE(m.company_name, '未匹配公司'),
    d.shop_code,
    MAX(d.shop_name),
    d.primary_category_code,
    MAX(d.primary_category_name),
    d.secondary_category_code,
    MAX(d.secondary_category_name),
    d.source_document_type,
    ROUND(SUM(d.income_amount), 2),
    SUM(d.included_detail_count),
    MAX(d.source_updated_at),
    NOW()
FROM platform_dws d
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
    d.primary_category_code,
    d.secondary_category_code,
    d.source_document_type;
