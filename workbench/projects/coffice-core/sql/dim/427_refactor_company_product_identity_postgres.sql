CREATE SCHEMA IF NOT EXISTS common;
CREATE SCHEMA IF NOT EXISTS dim;

ALTER TABLE dim.dim_influencer_product
    ADD COLUMN IF NOT EXISTS company_product_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS product_type VARCHAR(32) NOT NULL DEFAULT 'merchandise';

ALTER TABLE dim.dim_company_product_code_mapping
    ADD COLUMN IF NOT EXISTS alias_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS quantity_position VARCHAR(16),
    ADD COLUMN IF NOT EXISTS mapping_kind VARCHAR(32) NOT NULL DEFAULT 'alias',
    ADD COLUMN IF NOT EXISTS legacy_platform_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS legacy_shop_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

UPDATE dim.dim_influencer_product
SET product_type = CASE
        WHEN product_id IN (
            'PRD-TMALL-SHOPPING-FUND-A1',
            'PRD-TMALL-SHOPPING-FUND-B2',
            'PRD-TMALL-SHOPPING-FUND-C3',
            'PRD-TMALL-PREORDER-VOUCHER'
        ) THEN 'non_product'
        WHEN product_id = 'PRD-RED-ENVELOPE' THEN 'promotion'
        ELSE COALESCE(NULLIF(product_type, ''), 'merchandise')
    END;

WITH normalized AS (
    SELECT
        mapping_id,
        product_id,
        CASE
            WHEN product_id IN (
                'PRD-TMALL-SHOPPING-FUND-A1',
                'PRD-TMALL-SHOPPING-FUND-B2',
                'PRD-TMALL-SHOPPING-FUND-C3',
                'PRD-TMALL-PREORDER-VOUCHER'
            ) THEN UPPER(BTRIM(source_product_code))
            WHEN match_rule = 'suffix_quantity' THEN UPPER(REGEXP_REPLACE(
                COALESCE(NULLIF(BTRIM(source_product_code), ''), code_pattern),
                '-X$', '', 'i'
            ))
            WHEN UPPER(BTRIM(source_product_code)) ~ '^.+-[1-9][0-9]*$' THEN
                REGEXP_REPLACE(UPPER(BTRIM(source_product_code)), '-[1-9][0-9]*$', '')
            ELSE UPPER(BTRIM(source_product_code))
        END AS alias_code,
        CASE
            WHEN product_id IN (
                'PRD-TMALL-SHOPPING-FUND-A1',
                'PRD-TMALL-SHOPPING-FUND-B2',
                'PRD-TMALL-SHOPPING-FUND-C3',
                'PRD-TMALL-PREORDER-VOUCHER'
            ) THEN 'none'
            ELSE 'suffix'
        END AS quantity_position
    FROM dim.dim_company_product_code_mapping
), ranked_product_codes AS (
    SELECT
        n.product_id,
        n.alias_code,
        ROW_NUMBER() OVER (
            PARTITION BY n.product_id
            ORDER BY
                CASE WHEN m.platform_code = '*' THEN 0 ELSE 1 END,
                CASE WHEN m.mapping_source = 'file' THEN 0 ELSE 1 END,
                m.mapping_id
        ) AS preference_rank
    FROM normalized n
    JOIN dim.dim_company_product_code_mapping m USING (mapping_id)
)
UPDATE dim.dim_influencer_product p
SET company_product_code = chosen.alias_code,
    updated_at = NOW()
FROM ranked_product_codes chosen
WHERE chosen.product_id = p.product_id
  AND chosen.preference_rank = 1
  AND NULLIF(BTRIM(p.company_product_code), '') IS NULL;

UPDATE dim.dim_influencer_product
SET company_product_code = UPPER(product_id),
    updated_at = NOW()
WHERE NULLIF(BTRIM(company_product_code), '') IS NULL;

DO $guard$
BEGIN
    IF EXISTS (
        WITH normalized AS (
            SELECT
                m.product_id,
                CASE
                    WHEN NULLIF(BTRIM(m.alias_code), '') IS NOT NULL THEN UPPER(BTRIM(m.alias_code))
                    WHEN p.product_type = 'non_product' THEN UPPER(BTRIM(m.source_product_code))
                    WHEN m.match_rule = 'suffix_quantity' THEN UPPER(REGEXP_REPLACE(
                        COALESCE(NULLIF(BTRIM(m.source_product_code), ''), m.code_pattern),
                        '-X$', '', 'i'
                    ))
                    WHEN UPPER(BTRIM(m.source_product_code)) ~ '^.+-[1-9][0-9]*$' THEN
                        REGEXP_REPLACE(UPPER(BTRIM(m.source_product_code)), '-[1-9][0-9]*$', '')
                    ELSE UPPER(BTRIM(m.source_product_code))
                END AS alias_code,
                COALESCE(m.quantity_position, CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END)
                    AS quantity_position
            FROM dim.dim_company_product_code_mapping m
            JOIN dim.dim_influencer_product p ON p.product_id = m.product_id
        )
        SELECT 1
        FROM normalized
        GROUP BY alias_code, quantity_position
        HAVING COUNT(DISTINCT product_id) > 1
    ) THEN
        RAISE EXCEPTION '公司级商品编码表达存在跨商品冲突，不能自动迁移';
    END IF;
END
$guard$;

WITH normalized AS (
    SELECT
        m.mapping_id,
        m.product_id,
        CASE
            WHEN NULLIF(BTRIM(m.alias_code), '') IS NOT NULL THEN UPPER(BTRIM(m.alias_code))
            WHEN p.product_type = 'non_product' THEN UPPER(BTRIM(m.source_product_code))
            WHEN m.match_rule = 'suffix_quantity' THEN UPPER(REGEXP_REPLACE(
                COALESCE(NULLIF(BTRIM(m.source_product_code), ''), m.code_pattern),
                '-X$', '', 'i'
            ))
            WHEN UPPER(BTRIM(m.source_product_code)) ~ '^.+-[1-9][0-9]*$' THEN
                REGEXP_REPLACE(UPPER(BTRIM(m.source_product_code)), '-[1-9][0-9]*$', '')
            ELSE UPPER(BTRIM(m.source_product_code))
        END AS alias_code,
        COALESCE(m.quantity_position, CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END)
            AS quantity_position,
        m.platform_code,
        m.shop_code,
        ROW_NUMBER() OVER (
            PARTITION BY
                CASE
                    WHEN NULLIF(BTRIM(m.alias_code), '') IS NOT NULL THEN UPPER(BTRIM(m.alias_code))
                    WHEN p.product_type = 'non_product' THEN UPPER(BTRIM(m.source_product_code))
                    WHEN m.match_rule = 'suffix_quantity' THEN UPPER(REGEXP_REPLACE(
                        COALESCE(NULLIF(BTRIM(m.source_product_code), ''), m.code_pattern),
                        '-X$', '', 'i'
                    ))
                    WHEN UPPER(BTRIM(m.source_product_code)) ~ '^.+-[1-9][0-9]*$' THEN
                        REGEXP_REPLACE(UPPER(BTRIM(m.source_product_code)), '-[1-9][0-9]*$', '')
                    ELSE UPPER(BTRIM(m.source_product_code))
                END,
                COALESCE(m.quantity_position, CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END)
            ORDER BY
                CASE WHEN m.platform_code = '*' THEN 0 ELSE 1 END,
                m.mapping_id
        ) AS alias_rank
    FROM dim.dim_company_product_code_mapping m
    JOIN dim.dim_influencer_product p ON p.product_id = m.product_id
), audit AS (
    SELECT
        alias_code,
        quantity_position,
        ARRAY_AGG(DISTINCT platform_code ORDER BY platform_code) AS platform_codes,
        ARRAY_REMOVE(ARRAY_AGG(DISTINCT shop_code ORDER BY shop_code), NULL) AS shop_codes
    FROM normalized
    GROUP BY alias_code, quantity_position
), keepers AS (
    SELECT * FROM normalized WHERE alias_rank = 1
)
UPDATE dim.dim_company_product_code_mapping m
SET alias_code = k.alias_code,
    quantity_position = k.quantity_position,
    platform_code = '*',
    shop_code = NULL,
    source_product_code = k.alias_code,
    code_pattern = CASE
        WHEN k.quantity_position = 'suffix' THEN k.alias_code || '-X'
        WHEN k.quantity_position = 'prefix' THEN 'X' || k.alias_code
        ELSE k.alias_code
    END,
    code_prefix = CASE WHEN k.quantity_position = 'suffix' THEN k.alias_code || '-' ELSE NULL END,
    match_rule = CASE
        WHEN k.quantity_position = 'suffix' THEN 'suffix_quantity'
        WHEN k.quantity_position = 'prefix' THEN 'prefix_quantity'
        ELSE 'exact'
    END,
    mapping_kind = CASE
        WHEN m.mapping_kind = 'special' THEN 'special'
        WHEN k.alias_code = UPPER(BTRIM(p.company_product_code)) THEN 'company_code'
        ELSE 'alias'
    END,
    legacy_platform_codes = a.platform_codes,
    legacy_shop_codes = a.shop_codes,
    updated_at = NOW()
FROM keepers k
JOIN audit a USING (alias_code, quantity_position)
JOIN dim.dim_influencer_product p ON p.product_id = k.product_id
WHERE m.mapping_id = k.mapping_id;

WITH normalized AS (
    SELECT
        m.mapping_id,
        ROW_NUMBER() OVER (
            PARTITION BY
                CASE
                    WHEN NULLIF(BTRIM(m.alias_code), '') IS NOT NULL THEN UPPER(BTRIM(m.alias_code))
                    WHEN p.product_type = 'non_product' THEN UPPER(BTRIM(m.source_product_code))
                    WHEN m.match_rule = 'suffix_quantity' THEN UPPER(REGEXP_REPLACE(
                        COALESCE(NULLIF(BTRIM(m.source_product_code), ''), m.code_pattern),
                        '-X$', '', 'i'
                    ))
                    WHEN UPPER(BTRIM(m.source_product_code)) ~ '^.+-[1-9][0-9]*$' THEN
                        REGEXP_REPLACE(UPPER(BTRIM(m.source_product_code)), '-[1-9][0-9]*$', '')
                    ELSE UPPER(BTRIM(m.source_product_code))
                END,
                COALESCE(m.quantity_position, CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END)
            ORDER BY
                CASE WHEN m.alias_code IS NOT NULL THEN 0 ELSE 1 END,
                CASE WHEN m.platform_code = '*' THEN 0 ELSE 1 END,
                m.mapping_id
        ) AS alias_rank
    FROM dim.dim_company_product_code_mapping m
    JOIN dim.dim_influencer_product p ON p.product_id = m.product_id
)
DELETE FROM dim.dim_company_product_code_mapping m
USING normalized n
WHERE m.mapping_id = n.mapping_id
  AND n.alias_rank > 1;

INSERT INTO dim.dim_company_product_code_mapping (
    product_id, platform_code, shop_code, source_product_code,
    code_pattern, code_prefix, match_rule, code_role,
    mapping_source, is_active, alias_code, quantity_position, mapping_kind
)
SELECT
    p.product_id,
    '*',
    NULL,
    UPPER(BTRIM(p.company_product_code)),
    CASE WHEN p.product_type = 'non_product'
        THEN UPPER(BTRIM(p.company_product_code))
        ELSE UPPER(BTRIM(p.company_product_code)) || '-X' END,
    CASE WHEN p.product_type = 'non_product'
        THEN NULL ELSE UPPER(BTRIM(p.company_product_code)) || '-' END,
    CASE WHEN p.product_type = 'non_product' THEN 'exact' ELSE 'suffix_quantity' END,
    'box',
    p.maintenance_source,
    p.is_active,
    UPPER(BTRIM(p.company_product_code)),
    CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END,
    'company_code'
FROM dim.dim_influencer_product p
WHERE NOT EXISTS (
    SELECT 1
    FROM dim.dim_company_product_code_mapping m
    WHERE UPPER(BTRIM(m.alias_code)) = UPPER(BTRIM(p.company_product_code))
      AND m.quantity_position = CASE WHEN p.product_type = 'non_product' THEN 'none' ELSE 'suffix' END
);

DROP INDEX IF EXISTS dim.uq_company_product_mapping_platform_code;
DROP INDEX IF EXISTS dim.uq_company_product_mapping_shop_code;
DROP INDEX IF EXISTS dim.idx_company_product_mapping_lookup;
ALTER TABLE dim.dim_company_product_code_mapping
    DROP CONSTRAINT IF EXISTS ck_company_product_match_rule,
    DROP CONSTRAINT IF EXISTS ck_company_product_code_prefix;

ALTER TABLE dim.dim_influencer_product
    ALTER COLUMN company_product_code SET NOT NULL;
ALTER TABLE dim.dim_company_product_code_mapping
    ALTER COLUMN alias_code SET NOT NULL,
    ALTER COLUMN quantity_position SET NOT NULL;

DO $constraints$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_influencer_product_type') THEN
        ALTER TABLE dim.dim_influencer_product
            ADD CONSTRAINT ck_influencer_product_type
            CHECK (product_type IN ('merchandise', 'non_product', 'promotion'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_company_product_match_rule') THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT ck_company_product_match_rule
            CHECK (match_rule IN ('exact', 'suffix_quantity', 'prefix_quantity'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_company_product_quantity_position') THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT ck_company_product_quantity_position
            CHECK (quantity_position IN ('none', 'suffix', 'prefix'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_company_product_mapping_kind') THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT ck_company_product_mapping_kind
            CHECK (mapping_kind IN ('company_code', 'alias', 'special'));
    END IF;
END
$constraints$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_influencer_product_company_code
    ON dim.dim_influencer_product (UPPER(BTRIM(company_product_code)));
CREATE UNIQUE INDEX IF NOT EXISTS uq_company_product_alias_rule
    ON dim.dim_company_product_code_mapping (UPPER(BTRIM(alias_code)), quantity_position);
CREATE INDEX IF NOT EXISTS idx_company_product_alias_lookup
    ON dim.dim_company_product_code_mapping (
        quantity_position, UPPER(BTRIM(alias_code)), is_active
    );

CREATE OR REPLACE FUNCTION common.parse_company_product_component(p_component TEXT)
RETURNS TABLE (
    raw_component TEXT,
    code_expression TEXT,
    quantity_position VARCHAR(16),
    parsed_quantity NUMERIC(18,2)
)
LANGUAGE SQL
IMMUTABLE
AS $function$
    WITH normalized AS (
        SELECT UPPER(BTRIM(COALESCE(p_component, ''), E' \t\r\n')) AS code
    )
    SELECT
        code,
        CASE
            WHEN code ~ '^[1-9][0-9]*[A-Z][A-Z0-9-]*$'
                THEN SUBSTRING(code FROM '^[1-9][0-9]*([A-Z][A-Z0-9-]*)$')
            WHEN code ~ '^.+-[1-9][0-9]*$'
                THEN REGEXP_REPLACE(code, '-[1-9][0-9]*$', '')
            ELSE code
        END,
        CASE
            WHEN code ~ '^[1-9][0-9]*[A-Z][A-Z0-9-]*$' THEN 'prefix'::VARCHAR(16)
            WHEN code ~ '^.+-[1-9][0-9]*$' THEN 'suffix'::VARCHAR(16)
            ELSE 'none'::VARCHAR(16)
        END,
        CASE
            WHEN code ~ '^[1-9][0-9]*[A-Z][A-Z0-9-]*$'
                THEN SUBSTRING(code FROM '^([1-9][0-9]*)')::NUMERIC(18,2)
            WHEN code ~ '^.+-[1-9][0-9]*$'
                THEN SUBSTRING(code FROM '-([1-9][0-9]*)$')::NUMERIC(18,2)
            ELSE 1::NUMERIC(18,2)
        END
    FROM normalized;
$function$;

COMMENT ON TABLE dim.dim_influencer_product IS
    '公司统一商品主数据；商品ID是稳定系统主键，公司商品编码是独立的全公司业务编码。';
COMMENT ON COLUMN dim.dim_influencer_product.company_product_code IS
    '公司统一业务商品编码；不含销售数量，跨平台和店铺保持一致。';
COMMENT ON COLUMN dim.dim_influencer_product.product_type IS
    '商品类型：merchandise普通商品、non_product非商品辅助项、promotion营销特殊项。';
COMMENT ON TABLE dim.dim_company_product_code_mapping IS
    '公司级商品编码表达规则；别名或缩写全局映射到公司商品，平台与店铺不参与商品身份。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.alias_code IS
    '去除数量后的原始编码表达，例如M-MGNT或MG。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.quantity_position IS
    '数量在原始表达中的位置：suffix后缀、prefix前缀、none无数量。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.mapping_kind IS
    '规则类型：company_code公司编码本身、alias别名或缩写、special特殊精确编码。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.platform_code IS
    '兼容历史字段，统一为星号；平台仅由订单事实记录，不参与映射匹配。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.shop_code IS
    '兼容历史字段，统一为空；店铺仅由订单事实记录，不参与映射匹配。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.legacy_platform_codes IS
    '迁移前该规则曾使用的平台作用域集合，仅用于审计。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.legacy_shop_codes IS
    '迁移前该规则曾使用的店铺作用域集合，仅用于审计。';
COMMENT ON FUNCTION common.parse_company_product_component(TEXT) IS
    '把单个原始编码组件拆为去数量编码表达、数量位置和数量；不做商品归属判断。';
