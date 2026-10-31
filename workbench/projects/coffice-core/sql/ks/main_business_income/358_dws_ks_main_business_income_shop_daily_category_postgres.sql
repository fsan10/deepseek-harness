CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_main_business_income_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date,
        platform_code,
        shop_code,
        source_document_type,
        primary_category_code,
        secondary_category_code
    ),
    CONSTRAINT ck_dws_ks_main_business_income_source_type
        CHECK (source_document_type IN ('settlement', 'fund'))
);

COMMENT ON TABLE dws.dws_ks_main_business_income_shop_daily_category IS '快手主营业务收入店铺日分类DWS；结算收入扣除订单退款，并补充资金单中未在结算单体现的超售后期实际退款扣减。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.stat_date IS '主营业务收入归属日；结算取实际结算日期，资金补充退款取入账日期。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.primary_category_code IS '收入一级分类编码：product_sales_income、platform_subsidy、merchant_subsidy或sales_refund。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.primary_category_name IS '收入一级分类名称：商品销售收入、平台补贴、商家补贴或销售退款。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.secondary_category_code IS '快手原始收入字段或资金退款场景对应的稳定编码。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.secondary_category_name IS '结算原始收入字段名，或资金原始业务类型与描述按“业务类型 + 描述”拼接的名称。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.source_document_type IS '来源单据类型；settlement为结算单，fund为资金单。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.income_amount IS '主营业务收入报表金额；收入为正，商家补贴和销售退款为负，单位元。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.included_detail_count IS '纳入本行汇总且对应金额非零的来源明细数。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.source_updated_at IS '参与汇总的DWD来源记录最晚时间。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_main_business_income_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_main_business_income_primary_date
    ON dws.dws_ks_main_business_income_shop_daily_category (
        primary_category_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dws_ks_main_business_income_secondary_date
    ON dws.dws_ks_main_business_income_shop_daily_category (
        secondary_category_code, stat_date
    );
