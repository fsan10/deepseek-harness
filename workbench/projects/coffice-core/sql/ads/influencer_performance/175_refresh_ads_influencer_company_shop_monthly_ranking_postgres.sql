TRUNCATE TABLE ads.ads_influencer_company_shop_monthly_ranking;

INSERT INTO ads.ads_influencer_company_shop_monthly_ranking (
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    influencer_id,
    influencer_name,
    influencer_key,
    business_owner_id,
    business_owner_name,
    current_month_gmv,
    previous_month_gmv,
    mom_growth_rate,
    platform_month_gmv,
    previous_platform_month_gmv,
    platform_mom_growth_rate,
    platform_month_rank,
    is_platform_month_100k_plus,
    included_sub_order_count,
    source_updated_at,
    refreshed_at
)
WITH source_rows_raw AS (
    SELECT
        stat_date,
        stat_month,
        platform_code,
        platform_name,
        shop_code,
        shop_name,
        influencer_id,
        influencer_name,
        influencer_key,
        gmv_amount,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_douyin_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_wechat_channels_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_ks_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_tmall_influencer_sales_order
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_jd_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_xhs_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_pdd_influencer_sales_shop_daily_zero
), source_rows AS (
    SELECT *
    FROM source_rows_raw
    WHERE gmv_amount > 0
      AND influencer_id <> '__no_influencer__'
), shop_month AS (
    SELECT
        s.stat_month,
        s.platform_code,
        s.platform_name,
        COALESCE(company.company_code, 'unmapped') AS company_code,
        COALESCE(company.company_name, '未匹配公司') AS company_name,
        s.shop_code,
        s.shop_name,
        s.influencer_id,
        MAX(s.influencer_name) AS influencer_name,
        s.influencer_key,
        COALESCE(assignment.business_owner_id, 0) AS business_owner_id,
        COALESCE(assignment.business_owner_name, '未分配商务') AS business_owner_name,
        ROUND(SUM(s.gmv_amount), 2) AS current_month_gmv,
        SUM(s.included_sub_order_count) AS included_sub_order_count,
        MAX(s.source_updated_at) AS source_updated_at
    FROM source_rows s
    LEFT JOIN dim.dim_platform_shop_company company
      ON company.platform_code = s.platform_code
     AND company.shop_code = s.shop_code
     AND company.is_active
     AND s.stat_date >= company.valid_from
     AND (company.valid_to IS NULL OR s.stat_date <= company.valid_to)
    LEFT JOIN LATERAL (
        SELECT
            CASE WHEN a.is_active THEN a.business_owner_id END AS business_owner_id,
            CASE WHEN a.is_active THEN b.business_owner_name END AS business_owner_name
        FROM dim.dim_influencer_business_assignment_monthly a
        LEFT JOIN dim.dim_business_owner b
          ON b.business_owner_id = a.business_owner_id
        WHERE a.platform_code = s.platform_code
          AND a.influencer_id = s.influencer_id
          AND a.effective_month <= s.stat_month
        ORDER BY a.effective_month DESC
        LIMIT 1
    ) assignment ON TRUE
    GROUP BY
        s.stat_month,
        s.platform_code,
        s.platform_name,
        COALESCE(company.company_code, 'unmapped'),
        COALESCE(company.company_name, '未匹配公司'),
        s.shop_code,
        s.shop_name,
        s.influencer_id,
        s.influencer_key,
        COALESCE(assignment.business_owner_id, 0),
        COALESCE(assignment.business_owner_name, '未分配商务')
), shop_with_previous AS (
    SELECT
        current.*,
        COALESCE(previous.current_month_gmv, 0) AS previous_month_gmv
    FROM shop_month current
    LEFT JOIN shop_month previous
      ON previous.stat_month = (current.stat_month - INTERVAL '1 month')::date
     AND previous.platform_code = current.platform_code
     AND previous.company_code = current.company_code
     AND previous.shop_code = current.shop_code
     AND previous.influencer_id = current.influencer_id
), platform_month AS (
    SELECT
        stat_month,
        platform_code,
        MAX(platform_name) AS platform_name,
        influencer_id,
        MAX(influencer_name) AS influencer_name,
        MAX(influencer_key) AS influencer_key,
        ROUND(SUM(current_month_gmv), 2) AS platform_month_gmv
    FROM shop_month
    GROUP BY stat_month, platform_code, influencer_id
), platform_with_previous AS (
    SELECT
        current.*,
        COALESCE(previous.platform_month_gmv, 0) AS previous_platform_month_gmv,
        DENSE_RANK() OVER (
            PARTITION BY current.stat_month, current.platform_code
            ORDER BY current.platform_month_gmv DESC, current.influencer_id
        ) AS platform_month_rank
    FROM platform_month current
    LEFT JOIN platform_month previous
      ON previous.stat_month = (current.stat_month - INTERVAL '1 month')::date
     AND previous.platform_code = current.platform_code
     AND previous.influencer_id = current.influencer_id
)
SELECT
    shop.stat_month,
    shop.platform_code,
    shop.platform_name,
    shop.company_code,
    shop.company_name,
    shop.shop_code,
    shop.shop_name,
    shop.influencer_id,
    shop.influencer_name,
    shop.influencer_key,
    shop.business_owner_id,
    shop.business_owner_name,
    shop.current_month_gmv,
    shop.previous_month_gmv,
    CASE
        WHEN shop.previous_month_gmv = 0 THEN NULL
        ELSE ROUND((shop.current_month_gmv - shop.previous_month_gmv) / shop.previous_month_gmv, 6)
    END,
    platform.platform_month_gmv,
    platform.previous_platform_month_gmv,
    CASE
        WHEN platform.previous_platform_month_gmv = 0 THEN NULL
        ELSE ROUND(
            (platform.platform_month_gmv - platform.previous_platform_month_gmv)
            / platform.previous_platform_month_gmv,
            6
        )
    END,
    platform.platform_month_rank,
    platform.platform_month_gmv >= 100000,
    shop.included_sub_order_count,
    shop.source_updated_at,
    NOW()
FROM shop_with_previous shop
JOIN platform_with_previous platform
  ON platform.stat_month = shop.stat_month
 AND platform.platform_code = shop.platform_code
 AND platform.influencer_id = shop.influencer_id;
