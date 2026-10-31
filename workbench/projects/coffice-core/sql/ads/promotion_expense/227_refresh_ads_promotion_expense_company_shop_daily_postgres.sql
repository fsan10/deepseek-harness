TRUNCATE TABLE ads.ads_promotion_expense_company_shop_daily;

INSERT INTO ads.ads_promotion_expense_company_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    promotion_expense_amount,
    included_detail_count,
    source_updated_at,
    updated_at
)
WITH real_platform_daily AS (
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_douyin_promotion_expense_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_pdd_promotion_expense_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_jd_promotion_expense_shop_daily

    UNION ALL

    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM dws.dws_tmall_promotion_expense_shop_daily
),
date_spine AS (
    SELECT DISTINCT stat_date
    FROM real_platform_daily
),
zero_platform_daily AS (
    SELECT
        d.stat_date,
        m.platform_code,
        m.platform_name,
        m.shop_code,
        m.shop_name,
        0::NUMERIC(18,2) AS promotion_expense_amount,
        0::BIGINT AS included_detail_count,
        NULL::TIMESTAMPTZ AS source_updated_at
    FROM date_spine d
    JOIN dim.dim_platform_shop_company m
      ON m.platform_code IN ('ks', 'wechat_channels', 'xhs')
     AND m.is_active
     AND d.stat_date >= m.valid_from
     AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
),
platform_daily AS (
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM real_platform_daily
    UNION ALL
    SELECT
        stat_date,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM zero_platform_daily
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    COALESCE(m.company_code, 'unmapped'),
    COALESCE(m.company_name, '未匹配公司'),
    d.shop_code,
    MAX(d.shop_name),
    ROUND(SUM(d.promotion_expense_amount), 2),
    SUM(d.included_detail_count),
    MAX(d.source_updated_at),
    NOW()
FROM platform_daily d
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
    d.shop_code;
