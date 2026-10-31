DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM dws.dws_bank_total_expense_account_daily_type dws
        JOIN dim.dim_platform_shop_company dim
          ON dim.company_name = dws.source_account_name
        GROUP BY dws.source_account_name
        HAVING COUNT(DISTINCT dim.company_code) > 1
    ) THEN
        RAISE EXCEPTION '银行账号名称匹配到多个公司编码，停止刷新总费用ADS';
    END IF;
END $$;

TRUNCATE TABLE ads.ads_total_expense_company_daily_type;

INSERT INTO ads.ads_total_expense_company_daily_type (
    stat_date, platform_code, platform_name, company_code, company_name,
    expense_type_code, expense_type_name, expense_amount,
    included_detail_count, source_updated_at, updated_at
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
    dws.expense_type_code,
    MAX(dws.expense_type_name),
    ROUND(SUM(dws.expense_amount), 2),
    SUM(dws.included_detail_count),
    MAX(dws.source_updated_at),
    NOW()
FROM dws.dws_bank_total_expense_account_daily_type dws
LEFT JOIN company_map ON company_map.company_name = dws.source_account_name
GROUP BY
    dws.stat_date,
    dws.platform_code,
    COALESCE(company_map.company_code, 'unmapped'),
    COALESCE(company_map.company_name, '未匹配公司'),
    dws.expense_type_code;

