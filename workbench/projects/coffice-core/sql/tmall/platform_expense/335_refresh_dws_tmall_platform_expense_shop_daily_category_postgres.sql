TRUNCATE TABLE dws.dws_tmall_platform_expense_shop_daily_category;

DO $$
DECLARE
    missing_count INTEGER;
    missing_scenes TEXT;
BEGIN
    WITH missing AS (
        SELECT DISTINCT d.source_business_type, d.secondary_category_name
        FROM dwd.dwd_tmall_platform_expense_source_detail d
        WHERE NOT EXISTS (
            SELECT 1
            FROM dim.dim_platform_fee_mapping m
            WHERE m.platform_code = d.platform_code
          AND m.source_component_code IS NULL
              AND m.source_document_type = 'fund'

              AND (
                    (
                        m.source_description_match_type = 'none'
                        AND (m.secondary_category_name = d.secondary_category_name OR (m.source_component_code IS NULL AND m.normalized_scene_name = d.secondary_category_name))
                    )
                    OR (
                        m.source_description_match_type <> 'none'
                        AND (
                            m.source_business_type IS NULL
                            OR m.source_business_type = d.source_business_type
                        )
                        AND (
                            m.source_description_match_type = 'any'
                            OR (
                                m.source_description_match_type = 'exact'
                                AND COALESCE(d.source_description, '')
                                    = COALESCE(m.source_description_match_value, '')
                            )
                            OR (
                                m.source_description_match_type = 'prefix'
                                AND COALESCE(d.source_description, '')
                                    LIKE COALESCE(m.source_description_match_value, '') || '%'
                            )
                            OR (
                                m.source_description_match_type = 'contains'
                                AND POSITION(
                                    COALESCE(m.source_description_match_value, '')
                                    IN COALESCE(d.source_description, '')
                                ) > 0
                            )
                        )
                    )
              )
        )
    )
    SELECT COUNT(*), STRING_AGG(
        secondary_category_name,
        E'\n' ORDER BY source_business_type, secondary_category_name
    )
    INTO missing_count, missing_scenes
    FROM missing;

    IF missing_count > 0 THEN
        RAISE WARNING '天猫平台费用存在 % 个未映射原始场景，已保留在原始费用中，暂不进入平台费用分类：% ',
            missing_count, E'\n' || missing_scenes;
    END IF;
END
$$;

WITH mapped_detail AS (
    SELECT
        d.*,
        mapping.secondary_category_code AS mapping_secondary_category_code,
        mapping.primary_category_code,
        mapping.primary_category_name,
        mapping.include_in_platform_expense,
        mapping.source_role,
        mapping.source_description_match_type,
        mapping.updated_at AS mapping_updated_at
    FROM dwd.dwd_tmall_platform_expense_source_detail d
    CROSS JOIN LATERAL dim.match_platform_operating_scene(d.platform_code,'fund',d.secondary_category_name,d.source_business_type,d.source_description) mapping
)
INSERT INTO dws.dws_tmall_platform_expense_shop_daily_category (
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
    d.primary_category_code,
    MAX(d.primary_category_name),
    CASE
        WHEN d.source_description_match_type = 'none'
            THEN d.mapping_secondary_category_code
        ELSE d.mapping_secondary_category_code
            || '_' || LEFT(MD5(d.secondary_category_name), 12)
    END,
    d.secondary_category_name,
    'fund',
    ROUND(SUM(d.directional_expense_amount), 2),
    COUNT(*) FILTER (WHERE d.directional_expense_amount <> 0),
    COUNT(*),
    MAX(d.source_updated_at),
    MAX(d.mapping_updated_at),
    NOW()
FROM mapped_detail d
WHERE d.include_in_platform_expense
  AND d.source_role IN ('PRIMARY', 'SUPPLEMENT', 'EXPENSE_OFFSET')
GROUP BY
    d.stat_date,
    d.platform_code,
    d.shop_code,
    d.primary_category_code,
    CASE
        WHEN d.source_description_match_type = 'none'
            THEN d.mapping_secondary_category_code
        ELSE d.mapping_secondary_category_code
            || '_' || LEFT(MD5(d.secondary_category_name), 12)
    END,
    d.secondary_category_name;
