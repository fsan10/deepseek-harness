DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM dws.dws_bank_main_business_cost_account_daily dws
        JOIN dim.dim_platform_shop_company dim
          ON dim.company_name = dws.source_account_name
        GROUP BY dws.source_account_name
        HAVING COUNT(DISTINCT dim.company_code) > 1
    ) THEN
        RAISE EXCEPTION '银行账号名称匹配到多个公司编码，停止刷新主营业务成本ADS';
    END IF;
END $$;

TRUNCATE TABLE ads.ads_main_business_cost_company_daily;

INSERT INTO ads.ads_main_business_cost_company_daily (
    stat_date, platform_code, platform_name, company_code, company_name,
    main_business_cost_amount, included_detail_count, source_updated_at, updated_at
)
WITH company_map AS (
    SELECT company_name, MIN(company_code) AS company_code
    FROM dim.dim_platform_shop_company
    GROUP BY company_name
    HAVING COUNT(DISTINCT company_code) = 1
)
SELECT
    dws.stat_date,
    dws.platform_code,
    MAX(dws.platform_name),
    COALESCE(company_map.company_code, 'unmapped'),
    COALESCE(company_map.company_name, '未匹配公司'),
    ROUND(SUM(dws.main_business_cost_amount), 2),
    SUM(dws.included_detail_count),
    MAX(dws.source_updated_at),
    NOW()
FROM dws.dws_bank_main_business_cost_account_daily dws
LEFT JOIN company_map ON company_map.company_name = dws.source_account_name
GROUP BY
    dws.stat_date,
    dws.platform_code,
    COALESCE(company_map.company_code, 'unmapped'),
    COALESCE(company_map.company_name, '未匹配公司');

