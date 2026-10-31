DO $$
BEGIN
    IF TO_REGCLASS('ads.ads_settlement_net_company_shop_daily') IS NULL THEN
        RAISE EXCEPTION '缺少平台收入来源ads.ads_settlement_net_company_shop_daily';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dws.dws_bank_total_revenue_account_daily_type dws
        JOIN dim.dim_platform_shop_company dim
          ON dim.company_name = dws.source_account_name
        GROUP BY dws.source_account_name
        HAVING COUNT(DISTINCT dim.company_code) > 1
    ) THEN
        RAISE EXCEPTION '银行账号名称匹配到多个公司编码，停止刷新总营收ADS';
    END IF;
END $$;

TRUNCATE TABLE ads.ads_total_revenue_company_daily_type;

INSERT INTO ads.ads_total_revenue_company_daily_type (
    stat_date, platform_code, platform_name, company_code, company_name,
    revenue_type_code, revenue_type_name, revenue_amount,
    included_detail_count, source_updated_at, updated_at
)
WITH company_map AS (
    SELECT company_name, MIN(company_code) AS company_code
    FROM dim.dim_platform_shop_company
    GROUP BY company_name
    HAVING COUNT(DISTINCT company_code) = 1
),
bank_revenue AS (
    SELECT
        dws.stat_date,
        dws.platform_code,
        dws.platform_name,
        COALESCE(company_map.company_code, 'unmapped') AS company_code,
        COALESCE(company_map.company_name, '未匹配公司') AS company_name,
        dws.revenue_type_code,
        dws.revenue_type_name,
        dws.revenue_amount,
        dws.included_detail_count,
        dws.source_updated_at
    FROM dws.dws_bank_total_revenue_account_daily_type dws
    LEFT JOIN company_map ON company_map.company_name = dws.source_account_name
),
platform_revenue AS (
    SELECT
        stat_date,
        'all_platforms'::varchar AS platform_code,
        '全平台结算'::varchar AS platform_name,
        company_code,
        company_name,
        'platform_revenue'::varchar AS revenue_type_code,
        '平台收入'::varchar AS revenue_type_name,
        ROUND(SUM(settlement_net_amount), 2) AS revenue_amount,
        SUM(included_event_count) AS included_detail_count,
        MAX(source_updated_at) AS source_updated_at
    FROM ads.ads_settlement_net_company_shop_daily
    GROUP BY stat_date, company_code, company_name
),
revenue_union AS (
    SELECT * FROM bank_revenue
    UNION ALL
    SELECT * FROM platform_revenue
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    company_code,
    MAX(company_name),
    revenue_type_code,
    MAX(revenue_type_name),
    ROUND(SUM(revenue_amount), 2),
    SUM(included_detail_count),
    MAX(source_updated_at),
    NOW()
FROM revenue_union
GROUP BY stat_date, platform_code, company_code, revenue_type_code;

