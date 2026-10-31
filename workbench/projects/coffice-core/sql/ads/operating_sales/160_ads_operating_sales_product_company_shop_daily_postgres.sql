CREATE SCHEMA IF NOT EXISTS ads;

DROP TABLE IF EXISTS ads.ads_operating_sales_product_company_shop_daily;

CREATE TABLE ads.ads_operating_sales_product_company_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    product_id VARCHAR(256) NOT NULL,
    company_product_code VARCHAR(128) NOT NULL,
    product_type VARCHAR(32) NOT NULL,
    large_product_category VARCHAR(128) NOT NULL,
    product_category_l2 VARCHAR(128) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    paid_component_count BIGINT NOT NULL DEFAULT 0,
    gift_component_count BIGINT NOT NULL DEFAULT 0,
    mapped_component_count BIGINT NOT NULL DEFAULT 0,
    unmapped_component_count BIGINT NOT NULL DEFAULT 0,
    paid_unit_count NUMERIC(18,2) NOT NULL DEFAULT 0,
    gift_unit_count NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date, platform_code, company_code, shop_code, product_id
    )
);

COMMENT ON TABLE ads.ads_operating_sales_product_company_shop_daily IS '运营成交公司商品ADS；按稳定商品ID与公司商品编码统一跨原始写法汇总，并保留付费和赠品组件统计。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.stat_date IS '成交统计日期。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.platform_code IS '订单来源平台编码。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.platform_name IS '平台展示名称。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.company_code IS '店铺归属公司编码，来自有效期DIM。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.company_name IS '店铺归属公司名称。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.shop_code IS '订单来源标准店铺编码。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.shop_name IS '订单来源标准店铺名称。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.product_id IS '公司商品稳定ID；未映射编码族使用unmapped前缀审计ID。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.company_product_code IS '公司统一业务商品编码；未映射时为待配置编码表达。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.product_type IS '商品类型：merchandise、non_product、promotion或unmapped。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.large_product_category IS '公司商品一级分类。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.product_category_l2 IS '公司商品二级分类。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.product_name IS '公司商品名称。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.gmv_amount IS '仅按实际付费数量分摊的商品GMV；赠品为0元。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.paid_component_count IS 'paid_quantity大于0的组件行数。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.gift_component_count IS '纯赠品组件行数。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.mapped_component_count IS '已识别公司商品的组件行数。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.unmapped_component_count IS '未识别公司商品的组件行数。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.paid_unit_count IS '参与GMV权重的付费商品数量。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.gift_unit_count IS '不参与GMV权重的赠品数量。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.source_sub_order_count IS '来源子订单行去重数。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.source_updated_at IS '参与汇总的来源最晚更新时间。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_operating_sales_product_company_shop_daily.updated_at IS 'ADS记录刷新时间。';

CREATE INDEX idx_ads_operating_sales_product_company
    ON ads.ads_operating_sales_product_company_shop_daily (company_code, stat_date);
CREATE INDEX idx_ads_operating_sales_product_platform
    ON ads.ads_operating_sales_product_company_shop_daily (platform_code, stat_date);
CREATE INDEX idx_ads_operating_sales_product_identity
    ON ads.ads_operating_sales_product_company_shop_daily (
        product_id, company_product_code, stat_date
    );
