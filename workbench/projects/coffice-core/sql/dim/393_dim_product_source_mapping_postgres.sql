CREATE SCHEMA IF NOT EXISTS dim;

ALTER TABLE dim.dim_company_product_code_mapping
    ADD COLUMN IF NOT EXISTS platform_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS shop_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS source_product_code VARCHAR(512);

DO $column_widths$
DECLARE
    column_name_to_widen TEXT;
BEGIN
    FOR column_name_to_widen IN
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'dim'
          AND table_name = 'dim_company_product_code_mapping'
          AND column_name IN ('code_pattern', 'source_code_pattern', 'code_prefix')
          AND (data_type <> 'character varying' OR character_maximum_length IS DISTINCT FROM 512)
    LOOP
        EXECUTE FORMAT(
            'ALTER TABLE dim.dim_company_product_code_mapping ALTER COLUMN %I TYPE VARCHAR(512)',
            column_name_to_widen
        );
    END LOOP;
END
$column_widths$;

ALTER TABLE dim.dim_company_product_code_mapping
    DROP CONSTRAINT IF EXISTS uq_company_product_code_pattern;

DROP INDEX IF EXISTS dim.uq_company_product_code_pattern;
DROP INDEX IF EXISTS dim.uq_company_product_mapping_product_id;

UPDATE dim.dim_company_product_code_mapping
SET platform_code = COALESCE(NULLIF(BTRIM(platform_code), ''), '*'),
    source_product_code = COALESCE(
        NULLIF(BTRIM(source_product_code), ''),
        NULLIF(BTRIM(code_pattern), '')
    ),
    updated_at = NOW()
WHERE platform_code IS NULL
   OR NULLIF(BTRIM(platform_code), '') IS NULL
   OR source_product_code IS NULL
   OR NULLIF(BTRIM(source_product_code), '') IS NULL;

ALTER TABLE dim.dim_company_product_code_mapping
    ALTER COLUMN platform_code SET DEFAULT '*',
    ALTER COLUMN platform_code SET NOT NULL,
    ALTER COLUMN source_product_code SET NOT NULL;

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_company_product_mapping_platform_not_blank'
          AND conrelid = 'dim.dim_company_product_code_mapping'::regclass
    ) THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT ck_company_product_mapping_platform_not_blank
            CHECK (BTRIM(platform_code) <> '');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_company_product_mapping_source_code_not_blank'
          AND conrelid = 'dim.dim_company_product_code_mapping'::regclass
    ) THEN
        ALTER TABLE dim.dim_company_product_code_mapping
            ADD CONSTRAINT ck_company_product_mapping_source_code_not_blank
            CHECK (BTRIM(source_product_code) <> '');
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_company_product_mapping_lookup
    ON dim.dim_company_product_code_mapping (
        platform_code,
        shop_code,
        is_active,
        UPPER(BTRIM(source_product_code))
    );

CREATE INDEX IF NOT EXISTS idx_company_product_code_mapping_product
    ON dim.dim_company_product_code_mapping (product_id, is_active);

COMMENT ON TABLE dim.dim_company_product_code_mapping IS
    '公司商品编码映射兼容表；最终公司级编码表达语义由427号SQL补齐。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.mapping_id IS
    '平台商品编码映射代理主键。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.product_id IS
    '公司统一商品ID，关联dim.dim_influencer_product；同一商品允许被多条平台原始编码引用。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.platform_code IS
    '历史兼容字段；427号SQL起不再参与商品身份或映射优先级。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.shop_code IS
    '历史兼容字段；427号SQL起统一为空且不参与商品身份。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_product_code IS
    '平台导出的原始商品编码文本；仅清理首尾空白，不限制字符格式。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_pattern IS
    '兼容旧链路的匹配文本；新人工映射与source_product_code一致，历史规则可保留数量后缀模式。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.source_code_pattern IS
    '历史Excel来源编码审计键；不作为新人工映射的身份唯一键。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_prefix IS
    '历史数量后缀规则前缀；新人工精确映射为空。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.match_rule IS
    '匹配规则：exact为平台原始编码精确匹配，suffix_quantity仅兼容历史数量后缀规则。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.code_role IS
    '历史包装角色box或sachet；新人工映射默认box，不参与商品身份唯一性。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.is_active IS
    '映射是否启用；停用后订单编码作为未配置编码继续进入GMV。';

COMMENT ON TABLE dim.dim_influencer_product IS
    '公司统一商品主数据；product_id稳定，一个公司商品可关联多个平台原始商品编码。';
COMMENT ON COLUMN dim.dim_influencer_product.product_id IS
    '公司统一商品稳定ID；修改名称或分类、增加或移除平台编码时保持不变。';
