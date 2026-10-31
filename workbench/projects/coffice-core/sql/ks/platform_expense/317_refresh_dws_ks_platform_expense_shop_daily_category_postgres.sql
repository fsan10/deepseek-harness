TRUNCATE TABLE dws.dws_ks_platform_expense_shop_daily_category;

WITH mapped_detail AS (
    SELECT
        d.*,
        mapping.secondary_category_code AS mapping_secondary_category_code,
        mapping.primary_category_code,
        mapping.primary_category_name,
        mapping.include_in_platform_expense,
        mapping.source_role,
        mapping.updated_at AS mapping_updated_at
    FROM dwd.dwd_ks_platform_expense_source_detail d
    CROSS JOIN LATERAL dim.match_platform_operating_scene(d.platform_code,d.source_document_type,d.secondary_category_name,d.source_business_type,d.source_description) mapping
)
INSERT INTO dws.dws_ks_platform_expense_shop_daily_category (
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
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    primary_category_code,
    MAX(primary_category_name),
    CASE
        WHEN source_document_type = 'fund'
            THEN mapping_secondary_category_code
                || '_'
                || LEFT(MD5(secondary_category_name), 12)
        ELSE mapping_secondary_category_code
    END,
    secondary_category_name,
    source_document_type,
    ROUND(SUM(directional_expense_amount), 2),
    COUNT(*) FILTER (WHERE directional_expense_amount <> 0),
    COUNT(*),
    MAX(source_updated_at),
    MAX(mapping_updated_at),
    NOW()
FROM mapped_detail
WHERE include_in_platform_expense
  AND source_role IN ('PRIMARY', 'SUPPLEMENT', 'EXPENSE_OFFSET')
GROUP BY
    stat_date,
    platform_code,
    shop_code,
    primary_category_code,
    CASE
        WHEN source_document_type = 'fund'
            THEN mapping_secondary_category_code
                || '_'
                || LEFT(MD5(secondary_category_name), 12)
        ELSE mapping_secondary_category_code
    END,
    secondary_category_name,
    source_document_type;
