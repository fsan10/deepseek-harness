DO $$
DECLARE
    source_table TEXT;
BEGIN
    FOREACH source_table IN ARRAY ARRAY[
        'ads.ads_platform_main_business_income_company_shop_daily_category',
        'ads.ads_platform_expense_company_shop_daily_category',
        'ads.ads_promotion_expense_company_shop_daily',
        'ads.ads_bank_statement_company_daily_metric'
    ] LOOP
        IF TO_REGCLASS(source_table) IS NULL THEN
            RAISE EXCEPTION '缺少平台银行汇总来源表：%', source_table;
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM ads.ads_bank_statement_company_daily_metric
        WHERE metric_group_code NOT IN ('revenue', 'expense', 'cost')
    ) THEN
        RAISE EXCEPTION '银行流水ADS存在未知metric_group_code，停止刷新汇总ADS';
    END IF;

    IF EXISTS (
        SELECT 1 FROM ads.ads_platform_main_business_income_company_shop_daily_category WHERE company_code = 'unmapped'
        UNION ALL
        SELECT 1 FROM ads.ads_platform_expense_company_shop_daily_category WHERE company_code = 'unmapped'
        UNION ALL
        SELECT 1 FROM ads.ads_promotion_expense_company_shop_daily WHERE company_code = 'unmapped'
        UNION ALL
        SELECT 1 FROM ads.ads_bank_statement_company_daily_metric WHERE company_code = 'unmapped'
    ) THEN
        RAISE EXCEPTION '四张来源ADS存在未匹配公司，停止刷新平台银行汇总ADS';
    END IF;
END $$;

TRUNCATE TABLE ads.ads_platform_bank_total_revenue_company_daily_type;

INSERT INTO ads.ads_platform_bank_total_revenue_company_daily_type (
    stat_date,
    source_type_code,
    source_type_name,
    platform_code,
    platform_name,
    company_code,
    company_name,
    financial_direction_code,
    financial_direction_name,
    metric_group_code,
    metric_group_name,
    primary_category_code,
    primary_category_name,
    secondary_category_code,
    secondary_category_name,
    source_document_type,
    source_table_code,
    metric_amount,
    included_detail_count,
    source_updated_at,
    updated_at
)
WITH source_union AS (
    SELECT
        stat_date,
        'platform'::varchar AS source_type_code,
        '平台'::varchar AS source_type_name,
        platform_code,
        platform_name,
        company_code,
        company_name,
        'income'::varchar AS financial_direction_code,
        '收入'::varchar AS financial_direction_name,
        'platform_main_business_income'::varchar AS metric_group_code,
        '平台主营收入'::varchar AS metric_group_name,
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        'ads_platform_main_business_income_company_shop_daily_category'::varchar AS source_table_code,
        income_amount AS metric_amount,
        included_detail_count,
        source_updated_at
    FROM ads.ads_platform_main_business_income_company_shop_daily_category

    UNION ALL

    SELECT
        stat_date,
        'platform',
        '平台',
        platform_code,
        platform_name,
        company_code,
        company_name,
        'expense',
        '支出',
        'platform_expense',
        '平台费用',
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        source_document_type,
        'ads_platform_expense_company_shop_daily_category',
        expense_amount,
        included_detail_count,
        source_updated_at
    FROM ads.ads_platform_expense_company_shop_daily_category

    UNION ALL

    SELECT
        stat_date,
        'platform',
        '平台',
        platform_code,
        platform_name,
        company_code,
        company_name,
        'expense',
        '支出',
        'independent_promotion_expense',
        '独立推广费',
        'independent_promotion_expense',
        '独立推广费',
        'all',
        '全部',
        'promotion_account',
        'ads_promotion_expense_company_shop_daily',
        promotion_expense_amount,
        included_detail_count,
        source_updated_at
    FROM ads.ads_promotion_expense_company_shop_daily

    UNION ALL

    SELECT
        stat_date,
        'bank',
        '银行',
        'bank',
        '银行',
        company_code,
        company_name,
        CASE WHEN metric_group_code = 'revenue' THEN 'income' ELSE 'expense' END,
        CASE WHEN metric_group_code = 'revenue' THEN '收入' ELSE '支出' END,
        CASE metric_group_code
            WHEN 'revenue' THEN 'bank_income'
            WHEN 'expense' THEN 'bank_expense'
            WHEN 'cost' THEN 'bank_cost'
        END,
        CASE metric_group_code
            WHEN 'revenue' THEN '银行收入'
            WHEN 'expense' THEN '银行费用'
            WHEN 'cost' THEN '银行主营业务成本'
        END,
        metric_code,
        metric_name,
        'all',
        '全部',
        'bank_statement',
        'ads_bank_statement_company_daily_metric',
        metric_amount,
        included_detail_count,
        source_updated_at
    FROM ads.ads_bank_statement_company_daily_metric
)
SELECT
    stat_date,
    source_type_code,
    MAX(source_type_name),
    platform_code,
    MAX(platform_name),
    company_code,
    MAX(company_name),
    financial_direction_code,
    MAX(financial_direction_name),
    metric_group_code,
    MAX(metric_group_name),
    primary_category_code,
    MAX(primary_category_name),
    secondary_category_code,
    MAX(secondary_category_name),
    source_document_type,
    MAX(source_table_code),
    ROUND(SUM(metric_amount), 2),
    SUM(included_detail_count),
    MAX(source_updated_at),
    NOW()
FROM source_union
GROUP BY
    stat_date,
    source_type_code,
    platform_code,
    company_code,
    financial_direction_code,
    metric_group_code,
    primary_category_code,
    secondary_category_code,
    source_document_type;
