DO $$
DECLARE
    l1_id BIGINT;
    l2_id BIGINT;
BEGIN
    SELECT category_id INTO l1_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 1 AND LOWER(BTRIM(category_name)) = '其他'
    ORDER BY category_id LIMIT 1;
    IF l1_id IS NULL THEN
        INSERT INTO dim.dim_influencer_product_category (
            category_name, category_level, category_code, maintenance_source, is_active
        ) VALUES ('其他', 1, 'CAT-OTHER', 'manual', TRUE)
        RETURNING category_id INTO l1_id;
    END IF;

    SELECT category_id INTO l2_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 2 AND parent_category_id = l1_id
      AND LOWER(BTRIM(category_name)) = '其他'
    ORDER BY category_id LIMIT 1;
    IF l2_id IS NULL THEN
        INSERT INTO dim.dim_influencer_product_category (
            category_name, category_level, parent_category_id,
            category_code, maintenance_source, is_active
        ) VALUES ('其他', 2, l1_id, 'CAT-OTHER-OTHER', 'manual', TRUE)
        RETURNING category_id INTO l2_id;
    END IF;

    INSERT INTO dim.dim_influencer_product (
        product_id, category_id, company_product_code, product_name,
        product_type, maintenance_source, is_active
    ) VALUES (
        'PRD-RED-ENVELOPE', l2_id, 'M-MHB', '红包',
        'promotion', 'manual', TRUE
    )
    ON CONFLICT (product_id) DO UPDATE
    SET category_id = EXCLUDED.category_id,
        company_product_code = EXCLUDED.company_product_code,
        product_name = EXCLUDED.product_name,
        product_type = EXCLUDED.product_type,
        is_active = TRUE,
        updated_at = NOW();

    INSERT INTO dim.dim_company_product_code_mapping (
        product_id, platform_code, shop_code, source_product_code,
        code_pattern, source_code_pattern, code_prefix, match_rule,
        code_role, mapping_source, source_file_name, source_sheet_name,
        is_active, alias_code, quantity_position, mapping_kind
    ) VALUES (
        'PRD-RED-ENVELOPE', '*', NULL, 'M-MHB',
        'M-MHB-X', 'M-MHB-X', 'M-MHB-', 'suffix_quantity',
        'box', 'manual', '用户确认规则', 'red_envelope',
        TRUE, 'M-MHB', 'suffix', 'company_code'
    )
    ON CONFLICT ((UPPER(BTRIM(alias_code))), quantity_position) DO UPDATE
    SET product_id = EXCLUDED.product_id,
        mapping_kind = 'company_code',
        is_active = TRUE,
        updated_at = NOW();
END $$;
