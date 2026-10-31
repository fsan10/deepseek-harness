TRUNCATE TABLE ads.ads_influencer_business_monthly;

INSERT INTO ads.ads_influencer_business_monthly (
    stat_month,
    business_owner_id,
    business_owner_name,
    gmv_target,
    actual_gmv_amount,
    completion_rate,
    assigned_influencer_count,
    active_influencer_count,
    influencer_100k_plus_count,
    refund_amount,
    refund_rate,
    source_updated_at,
    refreshed_at
)
WITH source_rows_raw AS (
    SELECT
        stat_month,
        platform_code,
        influencer_id,
        influencer_key,
        gmv_amount,
        refund_amount,
        source_updated_at
    FROM dws.dws_douyin_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_wechat_channels_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_ks_influencer_sales_order_item
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_tmall_influencer_sales_order
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_jd_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_xhs_influencer_sales_shop_daily_zero
    UNION ALL
    SELECT
        stat_month, platform_code, influencer_id, influencer_key, gmv_amount,
        refund_amount, source_updated_at
    FROM dws.dws_pdd_influencer_sales_shop_daily_zero
), source_rows AS (
    SELECT *
    FROM source_rows_raw
    WHERE gmv_amount > 0
      AND influencer_id <> '__no_influencer__'
), months AS (
    SELECT DISTINCT stat_month FROM source_rows
    UNION
    SELECT DISTINCT target_month FROM dim.dim_business_gmv_target_monthly
    UNION
    SELECT DISTINCT effective_month FROM dim.dim_influencer_business_assignment_monthly
), assignment_snapshot AS (
    SELECT
        month.stat_month,
        assignment.platform_code,
        assignment.influencer_id,
        assignment.business_owner_id,
        assignment.is_active
    FROM months month
    CROSS JOIN LATERAL (
        SELECT DISTINCT ON (a.platform_code, a.influencer_id)
            a.platform_code,
            a.influencer_id,
            a.business_owner_id,
            a.is_active
        FROM dim.dim_influencer_business_assignment_monthly a
        WHERE a.effective_month <= month.stat_month
        ORDER BY a.platform_code, a.influencer_id, a.effective_month DESC
    ) assignment
), assigned_counts AS (
    SELECT
        stat_month,
        business_owner_id,
        COUNT(*) AS assigned_influencer_count
    FROM assignment_snapshot
    WHERE is_active AND business_owner_id IS NOT NULL
    GROUP BY stat_month, business_owner_id
), influencer_month AS (
    SELECT
        stat_month,
        platform_code,
        influencer_id,
        influencer_key,
        ROUND(SUM(gmv_amount), 2) AS gmv_amount,
        ROUND(SUM(refund_amount), 2) AS refund_amount,
        MAX(source_updated_at) AS source_updated_at
    FROM source_rows
    GROUP BY stat_month, platform_code, influencer_id, influencer_key
), sales_with_assignment AS (
    SELECT
        sales.*,
        COALESCE(assignment.business_owner_id, 0) AS business_owner_id
    FROM influencer_month sales
    LEFT JOIN LATERAL (
        SELECT CASE WHEN a.is_active THEN a.business_owner_id END AS business_owner_id
        FROM dim.dim_influencer_business_assignment_monthly a
        WHERE a.platform_code = sales.platform_code
          AND a.influencer_id = sales.influencer_id
          AND a.effective_month <= sales.stat_month
        ORDER BY a.effective_month DESC
        LIMIT 1
    ) assignment ON TRUE
), actual_by_business AS (
    SELECT
        stat_month,
        business_owner_id,
        ROUND(SUM(gmv_amount), 2) AS actual_gmv_amount,
        COUNT(*) AS active_influencer_count,
        COUNT(*) FILTER (WHERE gmv_amount >= 100000) AS influencer_100k_plus_count,
        ROUND(SUM(refund_amount), 2) AS refund_amount,
        MAX(source_updated_at) AS source_updated_at
    FROM sales_with_assignment
    GROUP BY stat_month, business_owner_id
), month_business AS (
    SELECT
        month.stat_month,
        owner.business_owner_id,
        owner.business_owner_name
    FROM months month
    CROSS JOIN dim.dim_business_owner owner
    WHERE owner.is_active
    UNION ALL
    SELECT stat_month, 0, '未分配商务'
    FROM months
)
SELECT
    base.stat_month,
    base.business_owner_id,
    base.business_owner_name,
    COALESCE(target.gmv_target, 0),
    COALESCE(actual.actual_gmv_amount, 0),
    COALESCE(ROUND(actual.actual_gmv_amount / NULLIF(target.gmv_target, 0), 6), 0),
    COALESCE(assigned.assigned_influencer_count, 0),
    COALESCE(actual.active_influencer_count, 0),
    COALESCE(actual.influencer_100k_plus_count, 0),
    COALESCE(actual.refund_amount, 0),
    COALESCE(ROUND(actual.refund_amount / NULLIF(actual.actual_gmv_amount, 0), 6), 0),
    actual.source_updated_at,
    NOW()
FROM month_business base
LEFT JOIN dim.dim_business_gmv_target_monthly target
  ON target.target_month = base.stat_month
 AND target.business_owner_id = base.business_owner_id
LEFT JOIN assigned_counts assigned
  ON assigned.stat_month = base.stat_month
 AND assigned.business_owner_id = base.business_owner_id
LEFT JOIN actual_by_business actual
  ON actual.stat_month = base.stat_month
 AND actual.business_owner_id = base.business_owner_id;
