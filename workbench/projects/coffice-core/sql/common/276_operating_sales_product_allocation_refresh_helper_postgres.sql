CREATE SCHEMA IF NOT EXISTS dws;

DROP PROCEDURE IF EXISTS dws.refresh_operating_sales_product_allocation(
    REGCLASS, REGCLASS, BOOLEAN
);
DROP PROCEDURE IF EXISTS dws.refresh_operating_sales_product_allocation(
    REGCLASS, REGCLASS, BOOLEAN, VARCHAR, BOOLEAN
);

CREATE OR REPLACE PROCEDURE dws.refresh_operating_sales_product_allocation (
    p_source_table REGCLASS,
    p_target_table REGCLASS,
    p_normalize_historical_codes BOOLEAN DEFAULT FALSE,
    p_brush_rule VARCHAR DEFAULT 'any_line_ge',
    p_exclude_auxiliary_lines BOOLEAN DEFAULT FALSE
)
LANGUAGE plpgsql
AS $$
BEGIN
    EXECUTE FORMAT('TRUNCATE TABLE %s', p_target_table);

    EXECUTE FORMAT(
        $statement$
        INSERT INTO %1$s (
            stat_date, platform_code, platform_name, shop_code, shop_name,
            main_order_no, sub_order_no, merchant_code, source_product_name,
            product_spec, source_component_count, paid_component_count,
            component_index, raw_merchant_code_component, normalization_rule_id,
            merchant_code_component, code_expression,
            quantity_position, product_mapping_id, company_product_id,
            company_product_code, product_type, large_product_category,
            product_category_l2, product_name, code_role, mapping_pattern,
            component_quantity, paid_quantity, gift_quantity, is_gift,
            allocation_weight, source_line_gmv_amount, allocated_gmv_amount,
            is_mapped, source_id, source_batch_id, source_updated_at, updated_at
        )
        WITH eligible_lines AS (
            SELECT
                d.*,
                COALESCE(
                    NULLIF(BTRIM(REPLACE(d.merchant_code, '＋', '+'), E' \t\r\n'), ''),
                    'UNMAPPED'
                ) AS normalized_merchant_code,
                COALESCE(d.product_spec, '') AS normalized_product_spec,
                COALESCE(d.product_name, '') AS normalized_product_name
            FROM %2$s d
            WHERE (
                    d.gmv_amount > 0
                    OR COALESCE(d.product_name, '') LIKE '%%赠品勿拍%%'
                  )
              AND NOT (
                  (
                      $2 = 'main_order_sum_gt'
                      AND (
                          SELECT COALESCE(SUM(brush.order_pay_amount), 0)
                          FROM %2$s brush
                          WHERE brush.platform_code = d.platform_code
                            AND brush.shop_code = d.shop_code
                            AND brush.main_order_no = d.main_order_no
                      ) > 2000
                  )
                  OR (
                      $2 = 'any_line_ge'
                      AND EXISTS (
                          SELECT 1
                          FROM %2$s brush
                          WHERE brush.platform_code = d.platform_code
                            AND brush.shop_code = d.shop_code
                            AND brush.main_order_no = d.main_order_no
                            AND brush.order_pay_amount >= 2000
                      )
                  )
              )
              AND NOT (
                  $3 AND COALESCE(d.product_name, '') = 'MOCK推荐官'
              )
        ), initial_components AS (
            SELECT
                e.*,
                BTRIM(UPPER(component.component_text), E' \t\r\n') AS raw_component,
                component.component_index::SMALLINT AS raw_component_index
            FROM eligible_lines e
            CROSS JOIN LATERAL REGEXP_SPLIT_TO_TABLE(
                e.normalized_merchant_code,
                E'\\+'
            ) WITH ORDINALITY AS component(component_text, component_index)
            WHERE NULLIF(BTRIM(component.component_text, E' \t\r\n'), '') IS NOT NULL
        ), normalized_components AS (
            SELECT
                initial.*,
                initial.raw_component AS raw_merchant_code_component,
                normalization.normalization_rule_id,
                BTRIM(UPPER(normalized.component_text), E' \t\r\n') AS normalized_component,
                ROW_NUMBER() OVER (
                    PARTITION BY initial.platform_code, initial.shop_code, initial.sub_order_no
                    ORDER BY initial.raw_component_index, normalized.normalized_component_index
                )::SMALLINT AS component_index
            FROM initial_components initial
            LEFT JOIN LATERAL (
                SELECT
                    rule.normalization_rule_id,
                    rule.normalized_code_expression
                FROM dim.dim_company_product_code_normalization_rule rule
                WHERE rule.is_active
                  AND UPPER(BTRIM(rule.source_code_component)) = initial.raw_component
                ORDER BY rule.normalization_rule_id
                LIMIT 1
            ) normalization ON TRUE
            CROSS JOIN LATERAL REGEXP_SPLIT_TO_TABLE(
                COALESCE(normalization.normalized_code_expression, initial.raw_component),
                E'\\+'
            ) WITH ORDINALITY AS normalized(component_text, normalized_component_index)
            WHERE NULLIF(BTRIM(normalized.component_text, E' \t\r\n'), '') IS NOT NULL
        ), parsed_components AS (
            SELECT
                r.*,
                parsed.code_expression,
                parsed.quantity_position,
                parsed.parsed_quantity AS component_quantity,
                COUNT(*) OVER (
                    PARTITION BY r.platform_code, r.shop_code, r.sub_order_no
                )::SMALLINT AS source_component_count,
                POSITION(
                    '赠' IN r.normalized_product_spec || ' ' || r.normalized_product_name
                ) AS gift_position
            FROM normalized_components r
            CROSS JOIN LATERAL common.parse_company_product_component(r.normalized_component) parsed
        ), component_rules AS (
            SELECT
                p.*,
                CASE
                    WHEN p.gift_position > 0 THEN RTRIM(
                        REPLACE(LEFT(
                            p.normalized_product_spec || ' ' || p.normalized_product_name,
                            p.gift_position - 1
                        ), '＋', '+'),
                        E' +（(【[\t\r\n:：,，、*xX'
                    )
                    ELSE ''
                END AS paid_spec_prefix
            FROM parsed_components p
        ), classified_components AS (
            SELECT
                p.*,
                CASE
                    WHEN p.gmv_amount <= 0
                      OR COALESCE(p.normalized_product_name, '') LIKE '%%赠品勿拍%%'
                        THEN 0
                    WHEN p.gift_position > 0 THEN LEAST(
                        p.source_component_count,
                        GREATEST(
                            1,
                            1 + LENGTH(p.paid_spec_prefix)
                            - LENGTH(REPLACE(p.paid_spec_prefix, '+', ''))
                        )
                    )::SMALLINT
                    ELSE p.source_component_count
                END AS paid_component_limit
            FROM component_rules p
        ), spec_quantities AS (
            SELECT
                c.*,
                paid_spec.spec_paid_quantity
            FROM classified_components c
            LEFT JOIN LATERAL (
                SELECT (parts)[1]::NUMERIC(18,2) AS spec_paid_quantity
                FROM REGEXP_MATCHES(
                    c.paid_spec_prefix,
                    '([0-9]+)[[:space:]]*(盒|袋|条|杯|份|个|张)',
                    'g'
                ) WITH ORDINALITY AS matches(parts, ordinal_no)
                ORDER BY ordinal_no DESC
                LIMIT 1
            ) paid_spec ON c.source_component_count = 1 AND c.gift_position > 0
        ), quantified_components AS (
            SELECT
                s.*,
                CASE
                    WHEN s.component_index > s.paid_component_limit THEN 0::NUMERIC(18,2)
                    WHEN s.source_component_count = 1
                     AND s.gift_position > 0
                     AND s.spec_paid_quantity > 0
                     AND s.spec_paid_quantity <= s.component_quantity
                        THEN s.spec_paid_quantity
                    ELSE s.component_quantity
                END AS paid_quantity
            FROM spec_quantities s
        ), mapped_components AS (
            SELECT
                q.*,
                (q.component_quantity - q.paid_quantity)::NUMERIC(18,2) AS gift_quantity,
                q.paid_quantity = 0 AS is_gift,
                COUNT(*) FILTER (WHERE q.paid_quantity > 0) OVER (
                    PARTITION BY q.platform_code, q.shop_code, q.sub_order_no
                )::SMALLINT AS paid_component_count,
                mapping.mapping_id AS product_mapping_id,
                mapping.product_id AS company_product_id,
                mapping.company_product_code,
                mapping.product_type,
                COALESCE(mapping.large_product_category, '未配置') AS large_product_category,
                COALESCE(mapping.product_category_l2, '未配置') AS product_category_l2,
                COALESCE(mapping.product_name, '未配置') AS mapped_product_name,
                COALESCE(mapping.code_role, 'unmapped') AS code_role,
                mapping.code_pattern AS mapping_pattern,
                mapping.mapping_id IS NOT NULL AS is_mapped
            FROM quantified_components q
            LEFT JOIN LATERAL (
                SELECT
                    rule.mapping_id,
                    rule.product_id,
                    rule.code_pattern,
                    rule.code_role,
                    product.company_product_code,
                    product.product_type,
                    product.product_name,
                    parent.category_name AS large_product_category,
                    child.category_name AS product_category_l2
                FROM dim.dim_company_product_code_mapping rule
                JOIN dim.dim_influencer_product product
                  ON product.product_id = rule.product_id
                 AND product.is_active
                JOIN dim.dim_influencer_product_category child
                  ON child.category_id = product.category_id
                 AND child.category_level = 2
                 AND child.is_active
                JOIN dim.dim_influencer_product_category parent
                  ON parent.category_id = child.parent_category_id
                 AND parent.category_level = 1
                 AND parent.is_active
                WHERE rule.is_active
                  AND UPPER(BTRIM(rule.alias_code)) = q.code_expression
                  AND (
                      rule.quantity_position = q.quantity_position
                      OR (
                          q.quantity_position = 'none'
                          AND rule.quantity_position IN ('none', 'suffix', 'prefix')
                      )
                  )
                ORDER BY
                    CASE WHEN rule.quantity_position = q.quantity_position THEN 0 ELSE 1 END,
                    CASE rule.mapping_kind WHEN 'company_code' THEN 0 WHEN 'special' THEN 1 ELSE 2 END,
                    rule.mapping_id
                LIMIT 1
            ) mapping ON TRUE
        ), weighted_components AS (
            SELECT
                m.*,
                SUM(m.paid_quantity) OVER (
                    PARTITION BY m.platform_code, m.shop_code, m.sub_order_no
                ) AS total_paid_quantity
            FROM mapped_components m
        ), rounded_components AS (
            SELECT
                w.*,
                CASE WHEN w.paid_quantity > 0 THEN ROUND(
                    w.paid_quantity / NULLIF(w.total_paid_quantity, 0), 10
                ) ELSE 0::NUMERIC END AS allocation_weight,
                CASE WHEN w.paid_quantity > 0 THEN ROUND(
                    w.gmv_amount * w.paid_quantity
                    / NULLIF(w.total_paid_quantity, 0), 2
                ) ELSE 0::NUMERIC END AS rounded_gmv_amount
            FROM weighted_components w
        ), reconciled_components AS (
            SELECT
                r.*,
                SUM(r.rounded_gmv_amount) OVER (
                    PARTITION BY r.platform_code, r.shop_code, r.sub_order_no
                ) AS rounded_gmv_total,
                MAX(r.component_index) FILTER (WHERE r.paid_quantity > 0) OVER (
                    PARTITION BY r.platform_code, r.shop_code, r.sub_order_no
                ) AS last_paid_component_index
            FROM rounded_components r
        )
        SELECT
            r.stat_date, r.platform_code, r.platform_name, r.shop_code, r.shop_name,
            r.main_order_no, r.sub_order_no, r.normalized_merchant_code,
            NULLIF(r.normalized_product_name, ''), NULLIF(r.normalized_product_spec, ''),
            r.source_component_count, r.paid_component_count, r.component_index,
            r.raw_merchant_code_component, r.normalization_rule_id,
            r.normalized_component, r.code_expression, r.quantity_position,
            r.product_mapping_id, r.company_product_id, r.company_product_code,
            r.product_type, r.large_product_category, r.product_category_l2,
            r.mapped_product_name, r.code_role, r.mapping_pattern,
            ROUND(r.component_quantity, 2), ROUND(r.paid_quantity, 2),
            ROUND(r.gift_quantity, 2), r.is_gift, r.allocation_weight,
            r.gmv_amount,
            CASE
                WHEN r.paid_quantity = 0 THEN 0::NUMERIC(18,2)
                WHEN r.component_index = r.last_paid_component_index THEN ROUND(
                    r.rounded_gmv_amount + r.gmv_amount - r.rounded_gmv_total, 2
                )
                ELSE r.rounded_gmv_amount
            END,
            r.is_mapped, r.source_id, r.source_batch_id, r.source_updated_at, NOW()
        FROM reconciled_components r
        $statement$,
        p_target_table,
        p_source_table
    )
    USING
        p_normalize_historical_codes,
        p_brush_rule,
        p_exclude_auxiliary_lines;
END;
$$;

COMMENT ON PROCEDURE dws.refresh_operating_sales_product_allocation(REGCLASS, REGCLASS, BOOLEAN, VARCHAR, BOOLEAN) IS
    '七平台商品组件统一刷新：先应用公司级异常组件修正规则并拆分，再解析数量与别名；保留赠品并以实际付费数量分摊GMV。';
