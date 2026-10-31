TRUNCATE TABLE ads.ads_influencer_company_shop_daily;

INSERT INTO ads.ads_influencer_company_shop_daily (
    stat_date, stat_month, platform_code, platform_name,
    company_code, company_name, shop_code, shop_name,
    influencer_id, influencer_name, influencer_key,
    source_influencer_id, company_influencer_id,
    company_influencer_name, influencer_identity_key,
    business_owner_id, business_owner_name, assignment_effective_month,
    gmv_amount, refund_amount, refund_rate, included_sub_order_count,
    source_updated_at, refreshed_at
)
WITH stable_fact AS (
    SELECT
        source.stat_date,
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
        ROUND(SUM(source.gmv_amount), 2) AS gmv_amount,
        ROUND(SUM(source.refund_amount), 2) AS refund_amount,
        SUM(source.included_sub_order_count) AS included_sub_order_count,
        MAX(source.source_updated_at) AS source_updated_at
    FROM dws.v_influencer_identity_resolved source
    LEFT JOIN dim.dim_platform_shop_company company
      ON company.platform_code = source.platform_code
     AND company.shop_code = source.shop_code
     AND company.is_active
     AND source.stat_date >= company.valid_from
     AND (company.valid_to IS NULL OR source.stat_date <= company.valid_to)
    GROUP BY
        source.stat_date, source.stat_month, source.platform_code,
        COALESCE(company.company_code, 'unmapped'), source.shop_code,
        source.influencer_identity_key, source.company_influencer_id
), enriched AS (
    SELECT
        fact.*,
        assignment.business_owner_id,
        assignment.business_owner_name,
        assignment.effective_month AS assignment_effective_month
    FROM stable_fact fact
    LEFT JOIN LATERAL (
        SELECT
            CASE WHEN version.is_active THEN version.business_owner_id END AS business_owner_id,
            CASE WHEN version.is_active THEN owner.business_owner_name END AS business_owner_name,
            version.effective_month
        FROM dim.dim_company_influencer_business_assignment_monthly version
        LEFT JOIN dim.dim_business_owner owner
          ON owner.business_owner_id = version.business_owner_id
        WHERE version.company_influencer_id = fact.company_influencer_id
          AND version.effective_month <= fact.stat_month
        ORDER BY version.effective_month DESC
        LIMIT 1
    ) assignment ON fact.company_influencer_id IS NOT NULL
)
SELECT
    stat_date,
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    source_influencer_id,
    influencer_display_name,
    influencer_identity_key,
    source_influencer_id,
    company_influencer_id,
    COALESCE(company_influencer_name, influencer_display_name),
    influencer_identity_key,
    COALESCE(business_owner_id, 0),
    COALESCE(business_owner_name, '未分配商务'),
    assignment_effective_month,
    gmv_amount,
    refund_amount,
    COALESCE(ROUND(refund_amount / NULLIF(gmv_amount, 0), 6), 0),
    included_sub_order_count,
    source_updated_at,
    NOW()
FROM enriched;

