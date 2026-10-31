TRUNCATE TABLE ads.ads_gsv_promotion_expense_company_shop_monthly;

INSERT INTO ads.ads_gsv_promotion_expense_company_shop_monthly (
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    gsv_amount,
    actual_promotion_expense_amount,
    roi,
    gsv_source_updated_at,
    promotion_source_updated_at,
    source_updated_at,
    updated_at
)
WITH gsv_monthly AS (
    SELECT
        DATE_TRUNC('month', stat_date)::date AS stat_month,
        platform_code,
        MAX(platform_name) AS platform_name,
        company_code,
        MAX(company_name) AS company_name,
        shop_code,
        MAX(shop_name) AS shop_name,
        ROUND(SUM(gsv_amount), 2) AS gsv_amount,
        MAX(source_updated_at) AS gsv_source_updated_at
    FROM ads.ads_gsv_company_daily
    GROUP BY
        DATE_TRUNC('month', stat_date)::date,
        platform_code,
        company_code,
        shop_code
), promotion_monthly AS (
    SELECT
        DATE_TRUNC('month', stat_date)::date AS stat_month,
        platform_code,
        company_code,
        shop_code,
        ROUND(SUM(promotion_expense_amount), 2) AS actual_promotion_expense_amount,
        MAX(source_updated_at) AS promotion_source_updated_at
    FROM ads.ads_promotion_expense_company_shop_daily
    GROUP BY
        DATE_TRUNC('month', stat_date)::date,
        platform_code,
        company_code,
        shop_code
), monthly_joined AS (
    SELECT
        g.stat_month,
        g.platform_code,
        g.platform_name,
        g.company_code,
        g.company_name,
        g.shop_code,
        g.shop_name,
        g.gsv_amount,
        COALESCE(p.actual_promotion_expense_amount, 0)::numeric AS actual_promotion_expense_amount,
        g.gsv_source_updated_at,
        p.promotion_source_updated_at
    FROM gsv_monthly g
    LEFT JOIN promotion_monthly p
      ON p.stat_month = g.stat_month
     AND p.platform_code = g.platform_code
     AND p.company_code = g.company_code
     AND p.shop_code = g.shop_code
)
SELECT
    stat_month,
    platform_code,
    platform_name,
    company_code,
    company_name,
    shop_code,
    shop_name,
    gsv_amount,
    actual_promotion_expense_amount,
    CASE
        WHEN actual_promotion_expense_amount = 0 THEN NULL
        ELSE ROUND(gsv_amount / actual_promotion_expense_amount, 6)
    END AS roi,
    gsv_source_updated_at,
    promotion_source_updated_at,
    GREATEST(gsv_source_updated_at, promotion_source_updated_at) AS source_updated_at,
    NOW()
FROM monthly_joined;
