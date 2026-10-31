TRUNCATE TABLE dws.dws_douyin_platform_expense_shop_daily_category;

INSERT INTO dws.dws_douyin_platform_expense_shop_daily_category (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    primary_category_code,
    primary_category_name,
    secondary_category_code,
    secondary_category_name,
    source_document_type,
    expense_amount,
    included_detail_count,
    source_detail_count,
    source_updated_at,
    mapping_updated_at,
    updated_at
)
SELECT
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    d.shop_code,
    MAX(d.shop_name),
    m.primary_category_code,
    MAX(m.primary_category_name),
    m.secondary_category_code,
    m.secondary_category_name,
    d.source_document_type,
    ROUND(SUM(d.directional_expense_amount), 2),
    COUNT(*) FILTER (WHERE d.directional_expense_amount <> 0),
    COUNT(*),
    MAX(d.source_updated_at),
    MAX(m.updated_at),
    NOW()
FROM dwd.dwd_douyin_platform_expense_source_detail d
INNER JOIN dim.dim_platform_fee_mapping m
    ON m.platform_code = d.platform_code
          AND m.source_component_code IS NULL
   AND m.source_document_type = d.source_document_type
   AND m.secondary_category_name = d.secondary_category_name
   AND m.include_in_platform_expense
   AND m.source_role IN ('PRIMARY', 'SUPPLEMENT', 'EXPENSE_OFFSET')

GROUP BY
    d.stat_date,
    d.platform_code,
    d.shop_code,
    m.primary_category_code,
    m.secondary_category_code,
    m.secondary_category_name,
    d.source_document_type
HAVING COUNT(*) FILTER (WHERE d.directional_expense_amount <> 0) > 0;
