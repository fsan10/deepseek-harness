CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_platform_main_business_income_company_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
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
        company_code,
        shop_code,
        source_document_type,
        primary_category_code,
        secondary_category_code
    )
);

COMMENT ON TABLE ads.ads_platform_main_business_income_company_shop_daily_category IS '七平台主营业务收入公司店铺日分类ADS；统一接入抖音、快手、京东、天猫、拼多多、视频号和小红书各自主营收入DWS，服务收入指标卡与分类明细图。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.stat_date IS '主营业务收入业务归属日期，用于DataEase日期筛选和趋势横轴。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.company_code IS '公司稳定编码，来自dim.dim_platform_shop_company；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.company_name IS '公司名称，来自dim.dim_platform_shop_company；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.primary_category_code IS '收入一级分类编码；商品销售收入或销售退款。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.primary_category_name IS '收入一级分类名称；商品销售收入或销售退款。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.secondary_category_code IS '平台原始收入或退款明细稳定编码。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.secondary_category_name IS '平台原始收入或退款明细名称。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.source_document_type IS '来源单据类型；settlement或fund。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.income_amount IS '主营业务收入净额；订单收入为正、销售退款为负，单位元。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.included_detail_count IS '参与本行汇总的来源明细数。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.source_updated_at IS '参与汇总的DWS来源记录最晚时间。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_platform_main_business_income_company_shop_daily_category.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_platform_main_business_income_company_date
    ON ads.ads_platform_main_business_income_company_shop_daily_category (
        company_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_ads_platform_main_business_income_platform_date
    ON ads.ads_platform_main_business_income_company_shop_daily_category (
        platform_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_ads_platform_main_business_income_primary_date
    ON ads.ads_platform_main_business_income_company_shop_daily_category (
        primary_category_code, stat_date
    );
