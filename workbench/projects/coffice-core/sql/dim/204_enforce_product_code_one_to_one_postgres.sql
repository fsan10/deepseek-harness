CREATE SCHEMA IF NOT EXISTS dim;

DROP INDEX IF EXISTS dim.uq_influencer_product_category_name_pair;

-- 兼容保留原迁移编号。商品与平台原始编码自393号迁移起为一对多，
-- 因此这里只移除历史一对一约束，不再按编码复制商品主档。
DROP INDEX IF EXISTS dim.uq_company_product_mapping_product_id;

CREATE INDEX IF NOT EXISTS idx_influencer_product_name
    ON dim.dim_influencer_product (LOWER(BTRIM(product_name)), is_active);

COMMENT ON TABLE dim.dim_influencer_product IS
    '公司统一商品主数据；一个商品可关联多个平台或店铺原始商品编码。';
COMMENT ON COLUMN dim.dim_influencer_product.product_id IS
    '公司统一商品稳定主键；修改名称、分类或编码映射时保持不变。';
COMMENT ON COLUMN dim.dim_influencer_product.product_name IS
    '公司统一商品名称；看板按此名称跨平台、店铺及多个原始编码汇总。';
COMMENT ON TABLE dim.dim_company_product_code_mapping IS
    '平台原始商品编码到公司统一商品的映射DIM；同一商品允许关联多条编码。';
COMMENT ON COLUMN dim.dim_company_product_code_mapping.product_id IS
    '关联的公司统一商品ID；不唯一，同一商品可被多个平台原始编码引用。';
