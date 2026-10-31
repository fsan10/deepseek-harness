CREATE SCHEMA IF NOT EXISTS dim;

CREATE TABLE IF NOT EXISTS dim.dim_platform_fee_primary_category (
    primary_category_code VARCHAR(64) PRIMARY KEY,
    primary_category_name VARCHAR(100) NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    classification_note TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(100) NOT NULL DEFAULT 'system',
    updated_by VARCHAR(100) NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_dim_platform_fee_primary_category_code
        CHECK (primary_category_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_dim_platform_fee_primary_category_name
        CHECK (BTRIM(primary_category_name) <> ''),
    CONSTRAINT ck_dim_platform_fee_primary_category_order
        CHECK (display_order >= 0)
);

INSERT INTO dim.dim_platform_fee_primary_category (
    primary_category_code,
    primary_category_name,
    display_order,
    classification_note,
    is_active,
    created_by,
    updated_by,
    created_at,
    updated_at
)
SELECT
    primary_category_code,
    MAX(primary_category_name),
    MIN(display_order),
    COALESCE(MAX(NULLIF(classification_note, '')), ''),
    BOOL_OR(is_active),
    'migration_369',
    'migration_369',
    MIN(created_at),
    MAX(updated_at)
FROM dim.dim_platform_fee_mapping
GROUP BY primary_category_code
ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_primary_category_active_order
    ON dim.dim_platform_fee_primary_category (is_active, display_order, primary_category_code);

CREATE OR REPLACE FUNCTION dim.set_platform_fee_primary_category_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_dim_platform_fee_primary_category_updated_at
    ON dim.dim_platform_fee_primary_category;

CREATE TRIGGER trg_dim_platform_fee_primary_category_updated_at
BEFORE UPDATE ON dim.dim_platform_fee_primary_category
FOR EACH ROW
EXECUTE FUNCTION dim.set_platform_fee_primary_category_updated_at();

COMMENT ON TABLE dim.dim_platform_fee_primary_category IS '平台费用一级分类管理表；分类独立于具体映射存在，费用映射继续保存在dim.dim_platform_fee_mapping。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.primary_category_code IS '一级分类稳定英文snake_case编码；被费用映射引用后不可修改。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.primary_category_name IS '一级分类中文展示名称；修改时同步更新引用该编码的费用映射名称。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.display_order IS '一级分类页面及映射下拉框排序，数值越小越靠前。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.classification_note IS '一级分类的财务口径说明或维护备注。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.is_active IS '分类是否可用于新的费用映射；停用不删除或改写已有映射。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.created_by IS '创建分类的用户或系统标识。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.updated_by IS '最后修改分类的用户或系统标识。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.created_at IS '分类创建时间，带时区。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.updated_at IS '分类最后更新时间，带时区。';
COMMENT ON FUNCTION dim.set_platform_fee_primary_category_updated_at() IS '一级分类更新时自动刷新updated_at。';
