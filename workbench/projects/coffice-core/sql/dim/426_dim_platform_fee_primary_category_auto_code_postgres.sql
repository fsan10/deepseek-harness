CREATE SCHEMA IF NOT EXISTS dim;

ALTER TABLE dim.dim_platform_fee_primary_category
    ADD COLUMN IF NOT EXISTS platform_code VARCHAR(32);

ALTER TABLE dim.dim_platform_fee_primary_category
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_primary_category_code;

ALTER TABLE dim.dim_platform_fee_primary_category
    ADD CONSTRAINT ck_dim_platform_fee_primary_category_code
    CHECK (primary_category_code ~ '^[A-Za-z][A-Za-z0-9_]{1,63}$');

ALTER TABLE dim.dim_platform_fee_primary_category
    DROP CONSTRAINT IF EXISTS ck_dim_platform_fee_primary_category_platform_code;

ALTER TABLE dim.dim_platform_fee_primary_category
    ADD CONSTRAINT ck_dim_platform_fee_primary_category_platform_code
    CHECK (platform_code IS NULL OR platform_code ~ '^[a-z][a-z0-9_]{1,31}$');

WITH platform_counts AS (
    SELECT
        primary_category_code,
        MIN(platform_code) AS platform_code,
        COUNT(DISTINCT platform_code) AS platform_count
    FROM dim.dim_platform_fee_mapping
    WHERE NULLIF(BTRIM(platform_code), '') IS NOT NULL
    GROUP BY primary_category_code
)
UPDATE dim.dim_platform_fee_primary_category AS category
SET platform_code = counts.platform_code
FROM platform_counts AS counts
WHERE category.platform_code IS NULL
  AND counts.platform_count = 1;

CREATE INDEX IF NOT EXISTS idx_dim_platform_fee_primary_category_platform_order
    ON dim.dim_platform_fee_primary_category (platform_code, is_active, display_order, primary_category_code);

COMMENT ON TABLE dim.dim_platform_fee_primary_category IS '平台费用一级分类管理表；新建分类由平台编码和序号自动生成编码，费用映射继续保存在dim.dim_platform_fee_mapping。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.platform_code IS '新建一级分类所属的平台编码；历史共享分类可为空，映射涉及的平台仍由费用映射表决定。';
COMMENT ON COLUMN dim.dim_platform_fee_primary_category.primary_category_code IS '一级分类稳定编码；新建分类按所属平台生成大写平台编码_全局递增两位起始序号，例如PDD_01、JD_02；被费用映射引用后不可修改。';
