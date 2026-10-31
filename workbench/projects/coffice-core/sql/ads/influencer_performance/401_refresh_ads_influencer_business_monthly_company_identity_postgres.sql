TRUNCATE TABLE ads.ads_influencer_business_monthly;

INSERT INTO ads.ads_influencer_business_monthly (
    stat_month, business_owner_id, business_owner_name, gmv_target,
    actual_gmv_amount, completion_rate, assigned_influencer_count,
    active_influencer_count, influencer_100k_plus_count,
    refund_amount, refund_rate, source_updated_at, refreshed_at
)
WITH eligible_source AS (
    SELECT *
    FROM dws.v_influencer_identity_resolved
    WHERE gmv_amount > 0
      AND source_influencer_id <> '__no_influencer__'
), months AS (
    SELECT DISTINCT stat_month FROM eligible_source
    UNION
    SELECT DISTINCT target_month FROM dim.dim_business_gmv_target_monthly
    UNION
    SELECT DISTINCT effective_month
    FROM dim.dim_company_influencer_business_assignment_monthly
), assignment_snapshot AS (
    SELECT
        month.stat_month,
        influencer.company_influencer_id,
        assignment.business_owner_id
    FROM months month
    CROSS JOIN dim.dim_company_influencer influencer
    LEFT JOIN LATERAL (
        SELECT
            CASE WHEN version.is_active THEN version.business_owner_id END AS business_owner_id
        FROM dim.dim_company_influencer_business_assignment_monthly version
        WHERE version.company_influencer_id = influencer.company_influencer_id
          AND version.effective_month <= month.stat_month
        ORDER BY version.effective_month DESC
        LIMIT 1
    ) assignment ON TRUE
    WHERE influencer.is_active
), assigned_counts AS (
    SELECT
        stat_month,
        business_owner_id,
        COUNT(DISTINCT company_influencer_id) AS assigned_influencer_count
    FROM assignment_snapshot
    WHERE business_owner_id IS NOT NULL
    GROUP BY stat_month, business_owner_id
), influencer_month AS (
    SELECT
        stat_month,
        influencer_identity_key,
        company_influencer_id,
        ROUND(SUM(gmv_amount), 2) AS gmv_amount,
        ROUND(SUM(refund_amount), 2) AS refund_amount,
        MAX(source_updated_at) AS source_updated_at
    FROM eligible_source
    GROUP BY stat_month, influencer_identity_key, company_influencer_id
), sales_with_assignment AS (
    SELECT
        sales.*,
        COALESCE(assignment.business_owner_id, 0) AS business_owner_id
    FROM influencer_month sales
    LEFT JOIN assignment_snapshot assignment
      ON assignment.stat_month = sales.stat_month
     AND assignment.company_influencer_id = sales.company_influencer_id
), actual_by_business AS (
    SELECT
        stat_month,
        business_owner_id,
        ROUND(SUM(gmv_amount), 2) AS actual_gmv_amount,
        COUNT(DISTINCT influencer_identity_key) AS active_influencer_count,
        COUNT(DISTINCT influencer_identity_key) FILTER (WHERE gmv_amount >= 100000)
            AS influencer_100k_plus_count,
        ROUND(SUM(refund_amount), 2) AS refund_amount,
        MAX(source_updated_at) AS source_updated_at
    FROM sales_with_assignment
    GROUP BY stat_month, business_owner_id
), month_business AS (
    SELECT month.stat_month, owner.business_owner_id, owner.business_owner_name
    FROM months month
    CROSS JOIN dim.dim_business_owner owner
    WHERE owner.is_active
    UNION ALL
    SELECT stat_month, 0, '未分配商务' FROM months
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
