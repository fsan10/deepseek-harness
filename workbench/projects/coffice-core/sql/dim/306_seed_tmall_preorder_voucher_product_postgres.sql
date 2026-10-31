DO $$
DECLARE
    l1_id BIGINT;
    l2_id BIGINT;
BEGIN
    SELECT category_id INTO STRICT l1_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 1 AND BTRIM(category_name) = '非商品' AND is_active;

    INSERT INTO dim.dim_influencer_product_category (
        category_name, category_level, parent_category_id,
        category_code, maintenance_source, is_active
    ) VALUES (
        '预定有价券', 2, l1_id,
        'CAT-NONPRODUCT-PREORDER-VOUCHER', 'manual', TRUE
    ) ON CONFLICT DO NOTHING;

    SELECT category_id INTO STRICT l2_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 2 AND parent_category_id = l1_id
      AND BTRIM(category_name) = '预定有价券';

    INSERT INTO dim.dim_influencer_product (
        product_id, category_id, company_product_code, product_name,
        product_type, maintenance_source, is_active
    ) VALUES (
        'PRD-TMALL-PREORDER-VOUCHER', l2_id, 'TMALL-PREORDER-VOUCHER',
        '预定大额有价券', 'non_product', 'manual', TRUE
    ) ON CONFLICT (product_id) DO UPDATE
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
        'PRD-TMALL-PREORDER-VOUCHER', '*', NULL, 'TMALL-PREORDER-VOUCHER',
        'TMALL-PREORDER-VOUCHER', 'TMALL-PREORDER-VOUCHER', NULL, 'exact',
        'box', 'manual', '用户确认规则', 'tmall_order',
        TRUE, 'TMALL-PREORDER-VOUCHER', 'none', 'special'
    )
    ON CONFLICT ((UPPER(BTRIM(alias_code))), quantity_position) DO UPDATE
    SET product_id = EXCLUDED.product_id,
        mapping_kind = 'special',
        is_active = TRUE,
        updated_at = NOW();
END $$;
