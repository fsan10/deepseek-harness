DO $$
DECLARE
    l1_id BIGINT;
    l2_id BIGINT;
BEGIN
    INSERT INTO dim.dim_influencer_product_category (
        category_name, category_level, parent_category_id,
        category_code, maintenance_source, is_active
    ) VALUES ('非商品', 1, NULL, 'CAT-NONPRODUCT', 'manual', TRUE)
    ON CONFLICT DO NOTHING;

    SELECT category_id INTO STRICT l1_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 1 AND BTRIM(category_name) = '非商品';

    INSERT INTO dim.dim_influencer_product_category (
        category_name, category_level, parent_category_id,
        category_code, maintenance_source, is_active
    ) VALUES ('购物金', 2, l1_id, 'CAT-NONPRODUCT-SHOPPING-FUND', 'manual', TRUE)
    ON CONFLICT DO NOTHING;

    SELECT category_id INTO STRICT l2_id
    FROM dim.dim_influencer_product_category
    WHERE category_level = 2 AND parent_category_id = l1_id
      AND BTRIM(category_name) = '购物金';

    INSERT INTO dim.dim_influencer_product (
        product_id, category_id, company_product_code, product_name,
        product_type, maintenance_source, is_active
    ) VALUES
        ('PRD-TMALL-SHOPPING-FUND-A1', l2_id, 'A1', '购物金', 'non_product', 'manual', TRUE),
        ('PRD-TMALL-SHOPPING-FUND-C3', l2_id, 'C3', '购物金', 'non_product', 'manual', TRUE),
        ('PRD-TMALL-SHOPPING-FUND-B2', l2_id, 'B2', '购物金', 'non_product', 'manual', TRUE)
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
    ) VALUES
        ('PRD-TMALL-SHOPPING-FUND-A1', '*', NULL, 'A1', 'A1', 'A1', NULL, 'exact', 'box', 'manual', '用户确认规则', 'shopping_fund', TRUE, 'A1', 'none', 'special'),
        ('PRD-TMALL-SHOPPING-FUND-C3', '*', NULL, 'C3', 'C3', 'C3', NULL, 'exact', 'box', 'manual', '用户确认规则', 'shopping_fund', TRUE, 'C3', 'none', 'special'),
        ('PRD-TMALL-SHOPPING-FUND-B2', '*', NULL, 'B2', 'B2', 'B2', NULL, 'exact', 'box', 'manual', '用户确认规则', 'shopping_fund', TRUE, 'B2', 'none', 'special')
    ON CONFLICT ((UPPER(BTRIM(alias_code))), quantity_position) DO UPDATE
    SET product_id = EXCLUDED.product_id,
        mapping_kind = 'special',
        is_active = TRUE,
        updated_at = NOW();
END $$;

COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_role IS
    '历史包装角色，仅用于兼容审计；购物金等特殊精确编码的业务区别由product_type表达。';
