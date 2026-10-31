CREATE SCHEMA IF NOT EXISTS ads;
CREATE TABLE IF NOT EXISTS ads.ads_product_code_mapping_workbench (
    snapshot_id UUID NOT NULL,
    row_key TEXT NOT NULL,
    mapping_id BIGINT,
    source_product_code VARCHAR(128) NOT NULL,
    code_pattern VARCHAR(255) NOT NULL,
    quantity_position VARCHAR(16) NOT NULL,
    mapping_kind VARCHAR(32),
    current_product_id VARCHAR(128),
    company_product_code VARCHAR(128),
    product_type VARCHAR(32),
    large_product_category VARCHAR(128),
    product_category_l2 VARCHAR(128),
    product_name VARCHAR(255),
    mapping_is_active BOOLEAN,
    product_is_active BOOLEAN,
    observed_source_codes TEXT[],
    observed_platform_codes TEXT[],
    observed_platform_names TEXT[],
    shop_count BIGINT NOT NULL,
    component_row_count BIGINT NOT NULL,
    gift_component_row_count BIGINT NOT NULL,
    parsed_quantity NUMERIC(18,2) NOT NULL,
    paid_quantity NUMERIC(18,2) NOT NULL,
    gift_quantity NUMERIC(18,2) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL,
    first_seen_date DATE,
    last_seen_date DATE,
    mapping_status TEXT NOT NULL CHECK (mapping_status IN ('mapped', 'unmapped', 'inactive')),
    code_role TEXT,
    mapping_source TEXT,
    match_rule TEXT,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(snapshot_id, row_key)
);
COMMENT ON TABLE ads.ads_product_code_mapping_workbench IS '商品编码映射页面预计算ADS；一行一个配置规则或未映射编码族，按版本原子发布，页面不再扫描订单DWS。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.snapshot_id IS '本次成功生成结果的UUID版本，与ops.refresh_watermark中的当前版本关联。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.row_key IS '版本内唯一身份：rule加规则ID，或unmapped加编码表达与数量位置的JSON数组。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.mapping_id IS 'DIM映射规则ID；未映射编码族为空；不建外键以保留上一成功版本。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.source_product_code IS '去除数量后的公司编码或别名表达，来自商品编码观察汇总。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.code_pattern IS 'DIM编码匹配模式；未映射时由编码表达和数量位置生成。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.quantity_position IS '数量位置：none精确、prefix数量前缀、suffix数量后缀。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.mapping_kind IS 'DIM规则种类：company_code、alias或special；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.current_product_id IS '本版本规则归属的稳定公司商品ID；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.company_product_code IS 'DIM公司商品业务编码；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.product_type IS 'DIM商品类型：merchandise、non_product或promotion；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.large_product_category IS '发布时DIM公司商品一级分类名称；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.product_category_l2 IS '发布时DIM公司商品二级分类名称；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.product_name IS '发布时DIM公司商品名称；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.mapping_is_active IS '发布时DIM映射规则启用状态；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.product_is_active IS '发布时DIM公司商品启用状态；未映射为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.observed_source_codes IS '七平台商品组件DWS实际观察到的完整组件编码去重有序集合。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.observed_platform_codes IS '观察到该规则或编码族的平台编码去重有序集合。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.observed_platform_names IS '观察到该规则或编码族的平台名称去重有序集合。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.shop_count IS '商品组件DWS中shop_code去重数量，沿用观察页面现有口径。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.component_row_count IS '七平台商品分摊DWS的组件明细行数，单位行。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.gift_component_row_count IS '组件DWS中is_gift为真的行数，单位行。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.parsed_quantity IS '组件DWS的component_quantity之和，单位件，汇总后保留两位小数。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.paid_quantity IS '组件DWS的paid_quantity之和，单位件，汇总后保留两位小数。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.gift_quantity IS '组件DWS的gift_quantity之和，单位件，汇总后保留两位小数。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.gmv_amount IS '组件DWS的allocated_gmv_amount之和，单位元；赠品为0，汇总后保留两位小数。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.first_seen_date IS '参与汇总组件最早业务日期；无观察订单的配置规则为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.last_seen_date IS '参与汇总组件最晚业务日期；无观察订单的配置规则为空。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.mapping_status IS '观察工作台状态：mapped已映射、unmapped未映射、inactive规则或商品停用。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.code_role IS '发布时DIM组件角色，如box、bag、gift或special。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.mapping_source IS '发布时DIM规则维护来源，如manual或excel。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.match_rule IS '发布时DIM匹配方式，如suffix_quantity、exact或code_prefix。';
COMMENT ON COLUMN ads.ads_product_code_mapping_workbench.generated_at IS '本版本结果生成时间，带时区。';
CREATE INDEX IF NOT EXISTS idx_product_mapping_workbench_status
ON ads.ads_product_code_mapping_workbench(snapshot_id, mapping_status, gmv_amount DESC);
