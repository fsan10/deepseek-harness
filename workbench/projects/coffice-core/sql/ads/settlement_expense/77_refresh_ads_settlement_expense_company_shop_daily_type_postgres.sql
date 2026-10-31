TRUNCATE TABLE ads.ads_settlement_expense_company_shop_daily_type;

INSERT INTO ads.ads_settlement_expense_company_shop_daily_type (
    stat_date, platform_code, platform_name, company_code, company_name,
    shop_code, shop_name, expense_type_code, expense_type_name, expense_amount,
    included_event_count, source_updated_at, updated_at
)
WITH platform_expense_union AS (
    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_douyin_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_jd_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_ks_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_pdd_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_wechat_channels_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_tmall_settlement_expense_shop_daily_type

    UNION ALL

    SELECT
        stat_date, platform_code, platform_name, shop_code, shop_name,
        expense_type_code, expense_type_name, expense_amount,
        included_event_count, source_updated_at
    FROM dws.dws_xhs_settlement_expense_shop_daily_type
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name),
    COALESCE(m.company_code, 'unmapped'), COALESCE(m.company_name, '未匹配公司'),
    d.shop_code, MAX(d.shop_name), d.expense_type_code, MAX(d.expense_type_name),
    ROUND(SUM(d.expense_amount), 2), SUM(d.included_event_count),
    MAX(d.source_updated_at), NOW()
FROM platform_expense_union d
LEFT JOIN dim.dim_platform_shop_company m
    ON m.platform_code = d.platform_code
   AND m.shop_code = d.shop_code
   AND m.is_active
   AND d.stat_date >= m.valid_from
   AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
GROUP BY
    d.stat_date, d.platform_code,
    COALESCE(m.company_code, 'unmapped'), COALESCE(m.company_name, '未匹配公司'),
    d.shop_code, d.expense_type_code;
