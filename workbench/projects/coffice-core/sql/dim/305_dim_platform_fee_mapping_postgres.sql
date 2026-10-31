CREATE SCHEMA IF NOT EXISTS dim;

CREATE TABLE IF NOT EXISTS dim.dim_platform_fee_mapping (
    mapping_id BIGSERIAL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL,
    secondary_category_code VARCHAR(96) NOT NULL,
    secondary_category_name VARCHAR(128) NOT NULL,
    source_business_type VARCHAR(128),
    source_description_match_type VARCHAR(16) NOT NULL DEFAULT 'none',
    source_description_match_value VARCHAR(500),
    mapping_priority INTEGER NOT NULL DEFAULT 0,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    include_in_platform_expense BOOLEAN NOT NULL DEFAULT TRUE,
    classification_note VARCHAR(500) NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(100) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(100) NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_dim_platform_fee_mapping_source_type
        CHECK (source_document_type IN ('settlement', 'fund')),
    CONSTRAINT ck_dim_platform_fee_mapping_description_match_type
        CHECK (
            source_description_match_type IN (
                'none', 'exact', 'prefix', 'contains', 'any'
            )
        ),
    CONSTRAINT ck_dim_platform_fee_mapping_nonempty_names
        CHECK (
            BTRIM(platform_code) <> ''
            AND BTRIM(secondary_category_code) <> ''
            AND BTRIM(secondary_category_name) <> ''
            AND BTRIM(primary_category_code) <> ''
            AND BTRIM(primary_category_name) <> ''
        ),
    CONSTRAINT uq_dim_platform_fee_mapping_source_code
        UNIQUE (platform_code, source_document_type, secondary_category_code),
    CONSTRAINT uq_dim_platform_fee_mapping_source_name
        UNIQUE (platform_code, source_document_type, secondary_category_name)
);

ALTER TABLE dim.dim_platform_fee_mapping
    ADD COLUMN IF NOT EXISTS source_business_type VARCHAR(128),
    ADD COLUMN IF NOT EXISTS source_description_match_type VARCHAR(16)
        NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS source_description_match_value VARCHAR(500),
    ADD COLUMN IF NOT EXISTS mapping_priority INTEGER NOT NULL DEFAULT 0;

ALTER TABLE dim.dim_platform_fee_mapping
    DROP CONSTRAINT IF EXISTS
        ck_dim_platform_fee_mapping_description_match_type;

ALTER TABLE dim.dim_platform_fee_mapping
    ADD CONSTRAINT ck_dim_platform_fee_mapping_description_match_type
    CHECK (
        source_description_match_type IN (
            'none', 'exact', 'prefix', 'contains', 'any'
        )
    );

COMMENT ON TABLE dim.dim_platform_fee_mapping IS '平台费用人工映射维表；二级分类固定保留平台原始费用字段或动账场景，一级分类由财务维护，同一平台来源场景只能映射一次。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.mapping_id IS '平台费用映射代理主键。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.platform_code IS '标准平台编码，例如douyin。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.platform_name IS '平台展示名称，例如抖音。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_document_type IS '来源单据类型；settlement为结算明细费用字段，fund为资金明细动账场景。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.secondary_category_code IS '二级费用分类稳定编码，与平台原始字段或动账场景一一对应。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.secondary_category_name IS '二级费用分类名称，严格保留平台原始费用字段名或动账场景名，不进行人工合并。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_business_type IS '资金来源平台原始业务类型；结算字段映射为空，资金描述规则为空时表示不限制原始业务类型。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_description_match_type IS '原始描述匹配方式；none按二级分类名匹配，exact精确匹配，prefix匹配前缀，contains匹配包含文本，any匹配该业务类型全部描述。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.source_description_match_value IS '平台原始描述或原始描述前缀；不改写平台文案。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.mapping_priority IS '同一来源可能命中多个规则时的匹配优先级，数值越大越优先。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.primary_category_code IS '财务人工设置的一级费用分类稳定编码；看板按该字段汇总。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.primary_category_name IS '财务人工设置的一级费用分类名称；多个二级场景可映射到同一个一级分类。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.include_in_platform_expense IS '是否计入平台费用；货款结算、退款勾稽和提现等非费用场景设为false。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.classification_note IS '人工分类依据、排除原因或口径说明。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.display_order IS '一级和二级分类展示排序，数值越小越靠前。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.is_active IS '映射是否有效；不再使用的映射可停用。新场景先以未映射状态保留在原始费用列表，财务确认后再建立有效映射。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.created_by IS '创建映射的用户或系统标识。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.updated_by IS '最后修改映射的用户或系统标识。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.created_at IS '映射创建时间，带时区。';
COMMENT ON COLUMN dim.dim_platform_fee_mapping.updated_at IS '映射最后更新时间，带时区。';

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_mapping_primary
    ON dim.dim_platform_fee_mapping (
        platform_code, primary_category_code, include_in_platform_expense
    )
    WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_mapping_secondary
    ON dim.dim_platform_fee_mapping (
        platform_code, source_document_type, secondary_category_name
    )
    WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_mapping_business_description
    ON dim.dim_platform_fee_mapping (
        platform_code,
        source_document_type,
        source_business_type,
        source_description_match_type,
        mapping_priority DESC
    )
    WHERE is_active;

CREATE OR REPLACE FUNCTION dim.set_platform_fee_mapping_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END
$$;

COMMENT ON FUNCTION dim.set_platform_fee_mapping_updated_at() IS '平台费用映射被人工修改时自动刷新updated_at。';

DROP TRIGGER IF EXISTS trg_dim_platform_fee_mapping_updated_at
    ON dim.dim_platform_fee_mapping;

CREATE TRIGGER trg_dim_platform_fee_mapping_updated_at
BEFORE UPDATE ON dim.dim_platform_fee_mapping
FOR EACH ROW
EXECUTE FUNCTION dim.set_platform_fee_mapping_updated_at();
