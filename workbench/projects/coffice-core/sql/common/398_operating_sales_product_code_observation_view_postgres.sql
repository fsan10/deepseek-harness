CREATE SCHEMA IF NOT EXISTS common;

CREATE OR REPLACE VIEW common.v_operating_sales_product_code_observation AS
WITH source_rows AS (
    -- Only observation dimensions are needed here. Carrying complete order rows
    -- through the reused CTEs spills large intermediate results to disk.
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_douyin_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_wechat_channels_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_jd_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_ks_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_xhs_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_pdd_operating_sales_product_allocation
    UNION ALL
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           is_gift, component_quantity, paid_quantity, gift_quantity,
           allocated_gmv_amount, stat_date
    FROM dws.dws_tmall_operating_sales_product_allocation
), source_observations AS (
    -- Collapse repeated order components before resolving rules and collecting
    -- DISTINCT dimensions. Keep raw counts and unrounded sums for exact totals.
    SELECT product_mapping_id, code_expression, quantity_position,
           merchant_code_component, platform_code, platform_name, shop_code,
           COUNT(*) AS component_row_count,
           COUNT(*) FILTER (WHERE is_gift) AS gift_component_row_count,
           SUM(component_quantity) AS component_quantity,
           SUM(paid_quantity) AS paid_quantity,
           SUM(gift_quantity) AS gift_quantity,
           SUM(allocated_gmv_amount) AS allocated_gmv_amount,
           MIN(stat_date) AS first_seen_date,
           MAX(stat_date) AS last_seen_date
    FROM source_rows
    GROUP BY product_mapping_id, code_expression, quantity_position,
             merchant_code_component, platform_code, platform_name, shop_code
), mapped_source_rows AS (
    SELECT
        source.*,
        source.product_mapping_id AS resolved_mapping_id
    FROM source_observations source
    WHERE source.product_mapping_id IS NOT NULL
), unresolved_source_rows AS (
    SELECT
        source.*,
        configured.mapping_id AS resolved_mapping_id
    FROM source_observations source
    LEFT JOIN LATERAL (
        SELECT rule.mapping_id
        FROM dim.dim_company_product_code_mapping rule
        WHERE UPPER(BTRIM(rule.alias_code)) = source.code_expression
          AND (
              rule.quantity_position = source.quantity_position
              OR (
                  source.quantity_position = 'none'
                  AND rule.quantity_position IN ('none', 'suffix', 'prefix')
              )
          )
        ORDER BY
            CASE WHEN rule.quantity_position = source.quantity_position THEN 0 ELSE 1 END,
            CASE rule.mapping_kind WHEN 'company_code' THEN 0 WHEN 'special' THEN 1 ELSE 2 END,
            rule.mapping_id
        LIMIT 1
    ) configured ON TRUE
    WHERE source.product_mapping_id IS NULL
), resolved_rows AS (
    SELECT * FROM mapped_source_rows
    UNION ALL
    SELECT * FROM unresolved_source_rows
), mapping_observations AS (
    SELECT
        resolved_mapping_id AS mapping_id,
        ARRAY_AGG(DISTINCT merchant_code_component ORDER BY merchant_code_component)
            AS observed_source_codes,
        ARRAY_AGG(DISTINCT platform_code ORDER BY platform_code)
            AS observed_platform_codes,
        ARRAY_AGG(DISTINCT platform_name ORDER BY platform_name)
            AS observed_platform_names,
        COUNT(DISTINCT shop_code) AS shop_count,
        SUM(component_row_count)::BIGINT AS component_row_count,
        SUM(gift_component_row_count)::BIGINT AS gift_component_row_count,
        ROUND(SUM(component_quantity), 2) AS parsed_quantity,
        ROUND(SUM(paid_quantity), 2) AS paid_quantity,
        ROUND(SUM(gift_quantity), 2) AS gift_quantity,
        ROUND(SUM(allocated_gmv_amount), 2) AS gmv_amount,
        MIN(first_seen_date) AS first_seen_date,
        MAX(last_seen_date) AS last_seen_date
    FROM resolved_rows
    WHERE resolved_mapping_id IS NOT NULL
    GROUP BY resolved_mapping_id
), unmapped_observations AS (
    SELECT
        code_expression,
        quantity_position,
        ARRAY_AGG(DISTINCT merchant_code_component ORDER BY merchant_code_component)
            AS observed_source_codes,
        ARRAY_AGG(DISTINCT platform_code ORDER BY platform_code)
            AS observed_platform_codes,
        ARRAY_AGG(DISTINCT platform_name ORDER BY platform_name)
            AS observed_platform_names,
        COUNT(DISTINCT shop_code) AS shop_count,
        SUM(component_row_count)::BIGINT AS component_row_count,
        SUM(gift_component_row_count)::BIGINT AS gift_component_row_count,
        ROUND(SUM(component_quantity), 2) AS parsed_quantity,
        ROUND(SUM(paid_quantity), 2) AS paid_quantity,
        ROUND(SUM(gift_quantity), 2) AS gift_quantity,
        ROUND(SUM(allocated_gmv_amount), 2) AS gmv_amount,
        MIN(first_seen_date) AS first_seen_date,
        MAX(last_seen_date) AS last_seen_date
    FROM resolved_rows
    WHERE resolved_mapping_id IS NULL
    GROUP BY code_expression, quantity_position
), configured_rules AS (
    SELECT
        mapping.mapping_id,
        mapping.alias_code AS source_product_code,
        mapping.code_pattern,
        mapping.quantity_position,
        mapping.mapping_kind,
        mapping.product_id AS current_product_id,
        product.company_product_code,
        product.product_type,
        parent.category_name AS large_product_category,
        child.category_name AS product_category_l2,
        product.product_name,
        mapping.is_active AS mapping_is_active,
        product.is_active AS product_is_active,
        observation.observed_source_codes,
        observation.observed_platform_codes,
        observation.observed_platform_names,
        COALESCE(observation.shop_count, 0) AS shop_count,
        COALESCE(observation.component_row_count, 0) AS component_row_count,
        COALESCE(observation.gift_component_row_count, 0) AS gift_component_row_count,
        COALESCE(observation.parsed_quantity, 0) AS parsed_quantity,
        COALESCE(observation.paid_quantity, 0) AS paid_quantity,
        COALESCE(observation.gift_quantity, 0) AS gift_quantity,
        COALESCE(observation.gmv_amount, 0) AS gmv_amount,
        observation.first_seen_date,
        observation.last_seen_date,
        CASE
            WHEN mapping.is_active AND product.is_active THEN 'mapped'
            ELSE 'inactive'
        END AS mapping_status
    FROM dim.dim_company_product_code_mapping mapping
    JOIN dim.dim_influencer_product product
      ON product.product_id = mapping.product_id
    JOIN dim.dim_influencer_product_category child
      ON child.category_id = product.category_id
    JOIN dim.dim_influencer_product_category parent
      ON parent.category_id = child.parent_category_id
    LEFT JOIN mapping_observations observation
      ON observation.mapping_id = mapping.mapping_id
)
SELECT
    mapping_id,
    source_product_code,
    code_pattern,
    quantity_position,
    mapping_kind,
    current_product_id,
    company_product_code,
    product_type,
    large_product_category,
    product_category_l2,
    product_name,
    mapping_is_active,
    product_is_active,
    observed_source_codes,
    observed_platform_codes,
    observed_platform_names,
    shop_count,
    component_row_count,
    gift_component_row_count,
    parsed_quantity,
    paid_quantity,
    gift_quantity,
    gmv_amount,
    first_seen_date,
    last_seen_date,
    mapping_status
FROM configured_rules
UNION ALL
SELECT
    NULL::BIGINT,
    code_expression,
    CASE
        WHEN quantity_position = 'suffix' THEN code_expression || '-X'
        WHEN quantity_position = 'prefix' THEN 'X' || code_expression
        ELSE code_expression
    END,
    quantity_position,
    NULL::VARCHAR(32),
    NULL::VARCHAR(128),
    NULL::VARCHAR(128),
    NULL::VARCHAR(32),
    NULL::VARCHAR(128),
    NULL::VARCHAR(128),
    NULL::VARCHAR(255),
    NULL::BOOLEAN,
    NULL::BOOLEAN,
    observed_source_codes,
    observed_platform_codes,
    observed_platform_names,
    shop_count,
    component_row_count,
    gift_component_row_count,
    parsed_quantity,
    paid_quantity,
    gift_quantity,
    gmv_amount,
    first_seen_date,
    last_seen_date,
    'unmapped'::TEXT
FROM unmapped_observations;

COMMENT ON VIEW common.v_operating_sales_product_code_observation IS
    '统一商品编码映射工作台视图；一行一个公司级编码表达规则或未映射编码族，平台与店铺仅作为观察维度。';
COMMENT ON COLUMN common.v_operating_sales_product_code_observation.source_product_code IS
    '去除数量后的公司编码或别名表达；同一商品不同数量只出现一次。';
COMMENT ON COLUMN common.v_operating_sales_product_code_observation.observed_source_codes IS
    '七平台实际观察到的完整原始组件编码集合。';
COMMENT ON COLUMN common.v_operating_sales_product_code_observation.observed_platform_codes IS
    '实际观察到该表达的平台编码集合，仅用于来源追溯。';
COMMENT ON COLUMN common.v_operating_sales_product_code_observation.mapping_status IS
    '规则状态：mapped已映射、unmapped未映射、inactive规则或商品已停用；不再产生partial。';
