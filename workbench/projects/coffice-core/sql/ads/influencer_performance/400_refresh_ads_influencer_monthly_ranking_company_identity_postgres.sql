TRUNCATE TABLE ads.ads_influencer_company_shop_monthly_ranking;

INSERT INTO ads.ads_influencer_company_shop_monthly_ranking (
    stat_month, platform_code, platform_name, company_code, company_name,
    shop_code, shop_name, influencer_id, influencer_name, influencer_key,
    source_influencer_id, company_influencer_id, company_influencer_name,
    influencer_identity_key, business_owner_id, business_owner_name,
    current_month_gmv, previous_month_gmv, mom_growth_rate,
    platform_month_gmv, previous_platform_month_gmv,
    platform_mom_growth_rate, platform_month_rank,
    is_platform_month_100k_plus, included_sub_order_count,
    source_updated_at, refreshed_at
)
WITH eligible_source AS (
    SELECT *
    FROM dws.v_influencer_identity_resolved
    WHERE gmv_amount > 0
      AND source_influencer_id <> '__no_influencer__'
), shop_fact AS (
    SELECT
        source.stat_month,
        source.platform_code,
        MAX(source.platform_name) AS platform_name,
        COALESCE(company.company_code, 'unmapped') AS company_code,
        MAX(COALESCE(company.company_name, '未匹配公司')) AS company_name,
        source.shop_code,
        MAX(COALESCE(company.shop_name, source.shop_name, '未匹配店铺')) AS shop_name,
        source.influencer_identity_key,
        source.company_influencer_id,
        MIN(source.source_influencer_id) AS source_influencer_id,
        MAX(source.influencer_display_name) AS influencer_display_name,
        MAX(source.company_influencer_name) AS company_influencer_name,
        ROUND(SUM(source.gmv_amount), 2) AS current_month_gmv,
        SUM(source.included_sub_order_count) AS included_sub_order_count,
        MAX(source.source_updated_at) AS source_updated_at
    FROM eligible_source source
    LEFT JOIN dim.dim_platform_shop_company company
      ON company.platform_code = source.platform_code
     AND company.shop_code = source.shop_code
     AND company.is_active
     AND source.stat_date >= company.valid_from
     AND (company.valid_to IS NULL OR source.stat_date <= company.valid_to)
    GROUP BY
        source.stat_month, source.platform_code,
        COALESCE(company.company_code, 'unmapped'), source.shop_code,
        source.influencer_identity_key, source.company_influencer_id
), shop_enriched AS (
    SELECT
        fact.*,
        COALESCE(assignment.business_owner_id, 0) AS business_owner_id,
        COALESCE(assignment.business_owner_name, '未分配商务') AS business_owner_name
    FROM shop_fact fact
    LEFT JOIN LATERAL (
        SELECT
            CASE WHEN version.is_active THEN version.business_owner_id END AS business_owner_id,
            CASE WHEN version.is_active THEN owner.business_owner_name END AS business_owner_name
        FROM dim.dim_company_influencer_business_assignment_monthly version
        LEFT JOIN dim.dim_business_owner owner
          ON owner.business_owner_id = version.business_owner_id
        WHERE version.company_influencer_id = fact.company_influencer_id
          AND version.effective_month <= fact.stat_month
        ORDER BY version.effective_month DESC
        LIMIT 1
    ) assignment ON fact.company_influencer_id IS NOT NULL
), shop_with_previous AS (
    SELECT
        current.*,
        COALESCE(previous.current_month_gmv, 0) AS previous_month_gmv
    FROM shop_enriched current
    LEFT JOIN shop_enriched previous
      ON previous.stat_month = (current.stat_month - INTERVAL '1 month')::date
     AND previous.platform_code = current.platform_code
     AND previous.company_code = current.company_code
     AND previous.shop_code = current.shop_code
     AND previous.influencer_identity_key = current.influencer_identity_key
), platform_fact AS (
    SELECT
        stat_month,
        platform_code,
        influencer_identity_key,
        ROUND(SUM(current_month_gmv), 2) AS platform_month_gmv
    FROM shop_enriched
    GROUP BY stat_month, platform_code, influencer_identity_key
), platform_with_previous AS (
    SELECT
        current.*,
        COALESCE(previous.platform_month_gmv, 0) AS previous_platform_month_gmv,
        DENSE_RANK() OVER (
            PARTITION BY current.stat_month, current.platform_code
            ORDER BY current.platform_month_gmv DESC, current.influencer_identity_key
        ) AS platform_month_rank
    FROM platform_fact current
    LEFT JOIN platform_fact previous
      ON previous.stat_month = (current.stat_month - INTERVAL '1 month')::date
     AND previous.platform_code = current.platform_code
     AND previous.influencer_identity_key = current.influencer_identity_key
)
SELECT
    shop.stat_month,
    shop.platform_code,
    shop.platform_name,
    shop.company_code,
    shop.company_name,
    shop.shop_code,
    shop.shop_name,
    shop.source_influencer_id,
    shop.influencer_display_name,
    shop.influencer_identity_key,
    shop.source_influencer_id,
    shop.company_influencer_id,
    COALESCE(shop.company_influencer_name, shop.influencer_display_name),
    shop.influencer_identity_key,
    shop.business_owner_id,
    shop.business_owner_name,
    shop.current_month_gmv,
    shop.previous_month_gmv,
    CASE WHEN shop.previous_month_gmv = 0 THEN NULL
         ELSE ROUND(
             (shop.current_month_gmv - shop.previous_month_gmv)
             / shop.previous_month_gmv,
             6
         ) END,
    platform.platform_month_gmv,
    platform.previous_platform_month_gmv,
    CASE WHEN platform.previous_platform_month_gmv = 0 THEN NULL
         ELSE ROUND(
             (platform.platform_month_gmv - platform.previous_platform_month_gmv)
             / platform.previous_platform_month_gmv,
             6
         ) END,
    platform.platform_month_rank,
    platform.platform_month_gmv >= 100000,
    shop.included_sub_order_count,
    shop.source_updated_at,
    NOW()
FROM shop_with_previous shop
JOIN platform_with_previous platform
  ON platform.stat_month = shop.stat_month
 AND platform.platform_code = shop.platform_code
 AND platform.influencer_identity_key = shop.influencer_identity_key;

