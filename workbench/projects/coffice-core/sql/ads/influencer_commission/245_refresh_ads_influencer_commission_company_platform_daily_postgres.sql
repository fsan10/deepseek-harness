DO $$
BEGIN
    IF EXISTS (
        WITH platform_daily AS (
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_douyin_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_ks_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_wechat_channels_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_tmall_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_jd_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_xhs_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, shop_code
            FROM dws.dws_pdd_influencer_commission_shop_daily_zero
        )
        SELECT 1
        FROM platform_daily daily
        JOIN dim.dim_platform_shop_company dim
          ON dim.platform_code = daily.platform_code
         AND dim.shop_code = daily.shop_code
         AND dim.is_active
         AND daily.stat_date >= dim.valid_from
         AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
        GROUP BY daily.stat_date, daily.platform_code, daily.shop_code
        HAVING COUNT(DISTINCT dim.company_code) > 1
    ) THEN
        RAISE EXCEPTION '电商达人佣金店铺在同一统计日期匹配到多个公司';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dws.dws_bank_influencer_commission_account_daily daily
        JOIN dim.dim_platform_shop_company dim
          ON dim.company_name = daily.source_account_name
         AND dim.is_active
         AND daily.stat_date >= dim.valid_from
         AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
        GROUP BY daily.stat_date, daily.source_account_name
        HAVING COUNT(DISTINCT dim.company_code) > 1
    ) THEN
        RAISE EXCEPTION '银行账号名称在同一统计日期匹配到多个公司编码';
    END IF;
END $$;

TRUNCATE TABLE ads.ads_influencer_commission_company_platform_daily;

INSERT INTO ads.ads_influencer_commission_company_platform_daily (
    stat_date, platform_code, platform_name, company_code, company_name,
    influencer_commission_amount, included_detail_count, source_updated_at, updated_at
)
WITH ecommerce_daily AS (
    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_event_count AS included_detail_count,
        source_updated_at
    FROM dws.dws_douyin_influencer_commission_shop_daily

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_event_count,
        source_updated_at
    FROM dws.dws_ks_influencer_commission_shop_daily

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_event_count,
        source_updated_at
    FROM dws.dws_wechat_channels_influencer_commission_shop_daily

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_detail_count,
        source_updated_at
    FROM dws.dws_tmall_influencer_commission_shop_daily_zero

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_detail_count,
        source_updated_at
    FROM dws.dws_jd_influencer_commission_shop_daily_zero

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_detail_count,
        source_updated_at
    FROM dws.dws_xhs_influencer_commission_shop_daily_zero

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        influencer_commission_amount, included_detail_count,
        source_updated_at
    FROM dws.dws_pdd_influencer_commission_shop_daily_zero
),
ecommerce_company_daily AS (
    SELECT
        daily.stat_date,
        daily.platform_code,
        MAX(daily.platform_name) AS platform_name,
        COALESCE(dim.company_code, 'unmapped') AS company_code,
        COALESCE(dim.company_name, '未匹配公司') AS company_name,
        ROUND(SUM(daily.influencer_commission_amount), 2) AS influencer_commission_amount,
        SUM(daily.included_detail_count) AS included_detail_count,
        MAX(daily.source_updated_at) AS source_updated_at
    FROM ecommerce_daily daily
    LEFT JOIN dim.dim_platform_shop_company dim
      ON dim.platform_code = daily.platform_code
     AND dim.shop_code = daily.shop_code
     AND dim.is_active
     AND daily.stat_date >= dim.valid_from
     AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
    GROUP BY
        daily.stat_date,
        daily.platform_code,
        COALESCE(dim.company_code, 'unmapped'),
        COALESCE(dim.company_name, '未匹配公司')
),
bank_company_map AS (
    SELECT
        daily.stat_date,
        daily.source_account_name,
        CASE
            WHEN COUNT(DISTINCT dim.company_code) = 1 THEN MIN(dim.company_code)
        END AS company_code,
        CASE
            WHEN COUNT(DISTINCT dim.company_code) = 1 THEN MIN(dim.company_name)
        END AS company_name
    FROM dws.dws_bank_influencer_commission_account_daily daily
    LEFT JOIN dim.dim_platform_shop_company dim
      ON dim.company_name = daily.source_account_name
     AND dim.is_active
     AND daily.stat_date >= dim.valid_from
     AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
    GROUP BY daily.stat_date, daily.source_account_name
),
bank_company_daily AS (
    SELECT
        daily.stat_date,
        daily.platform_code,
        MAX(daily.platform_name) AS platform_name,
        COALESCE(mapping.company_code, 'unmapped') AS company_code,
        COALESCE(mapping.company_name, '未匹配公司') AS company_name,
        ROUND(SUM(daily.influencer_commission_amount), 2) AS influencer_commission_amount,
        SUM(daily.included_detail_count) AS included_detail_count,
        MAX(daily.source_updated_at) AS source_updated_at
    FROM dws.dws_bank_influencer_commission_account_daily daily
    LEFT JOIN bank_company_map mapping
      ON mapping.stat_date = daily.stat_date
     AND mapping.source_account_name = daily.source_account_name
    GROUP BY
        daily.stat_date,
        daily.platform_code,
        COALESCE(mapping.company_code, 'unmapped'),
        COALESCE(mapping.company_name, '未匹配公司')
),
all_company_daily AS (
    SELECT * FROM ecommerce_company_daily
    UNION ALL
    SELECT * FROM bank_company_daily
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    company_code,
    MAX(company_name),
    ROUND(SUM(influencer_commission_amount), 2),
    SUM(included_detail_count),
    MAX(source_updated_at),
    NOW()
FROM all_company_daily
GROUP BY stat_date, platform_code, company_code;
