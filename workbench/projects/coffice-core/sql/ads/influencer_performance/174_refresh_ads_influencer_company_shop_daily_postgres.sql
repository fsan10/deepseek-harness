TRUNCATE TABLE ads.ads_influencer_company_shop_daily;

INSERT INTO ads.ads_influencer_company_shop_daily (
    stat_date,
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
    assignment_effective_month,
    gmv_amount,
    refund_amount,
    refund_rate,
    included_sub_order_count,
    source_updated_at,
    refreshed_at
)
WITH source_rows AS (
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
        refund_amount,
        included_sub_order_count,
        source_updated_at
    FROM dws.dws_douyin_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_wechat_channels_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_ks_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_tmall_influencer_sales_order
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_jd_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_xhs_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
        influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
        included_sub_order_count, source_updated_at
    FROM dws.dws_pdd_influencer_sales_shop_daily_zero
), enriched AS (
    SELECT
        s.*,
        COALESCE(company.company_code, 'unmapped') AS company_code,
        COALESCE(company.company_name, '未匹配公司') AS company_name,
        COALESCE(assignment.business_owner_id, 0) AS business_owner_id,
        COALESCE(assignment.business_owner_name, '未分配商务') AS business_owner_name,
        assignment.effective_month AS assignment_effective_month
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
            CASE WHEN a.is_active THEN b.business_owner_name END AS business_owner_name,
            a.effective_month
        FROM dim.dim_influencer_business_assignment_monthly a
        LEFT JOIN dim.dim_business_owner b
          ON b.business_owner_id = a.business_owner_id
        WHERE a.platform_code = s.platform_code
          AND a.influencer_id = s.influencer_id
          AND a.effective_month <= s.stat_month
        ORDER BY a.effective_month DESC
        LIMIT 1
    ) assignment ON TRUE
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
    influencer_id,
    MAX(influencer_name),
    influencer_key,
    business_owner_id,
    business_owner_name,
    assignment_effective_month,
    ROUND(SUM(gmv_amount), 2),
    ROUND(SUM(refund_amount), 2),
    COALESCE(ROUND(SUM(refund_amount) / NULLIF(SUM(gmv_amount), 0), 6), 0),
    SUM(included_sub_order_count),
    MAX(source_updated_at),
    NOW()
FROM enriched
GROUP BY
    stat_date,
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    influencer_id,
    influencer_key,
    business_owner_id,
    business_owner_name,
    assignment_effective_month;
