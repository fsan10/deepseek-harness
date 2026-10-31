CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_settlement_income_company_shop_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_type_code VARCHAR(64) NOT NULL,
    income_type_name VARCHAR(128) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code, shop_code, income_type_code)
);

COMMENT ON TABLE ads.ads_settlement_income_company_shop_daily_type IS '结算收入公司店铺日类型ADS，服务收入指标卡、收入类型占比以及平台、公司、店铺收入占比图。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.stat_date IS '结算收入统计日期，用于DataEase日期筛选。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.platform_name IS '平台展示名称，用于平台筛选和占比。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.company_code IS '公司稳定编码，来自DIM；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.company_name IS '公司名称，来自DIM；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.shop_code IS '标准店铺编码，用于店铺筛选和占比。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.income_type_code IS '收入类型英文编码。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.income_type_name IS '收入类型中文名称。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.income_amount IS '指定维度下的收入净额，指标卡对本字段求和，单位元。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.included_event_count IS '收入类型金额非零的结算事件数。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.source_updated_at IS '参与汇总的DWS记录最晚来源时间。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_settlement_income_company_shop_daily_type.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_settlement_income_company_date
    ON ads.ads_settlement_income_company_shop_daily_type (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_income_shop_date
    ON ads.ads_settlement_income_company_shop_daily_type (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_income_platform_date
    ON ads.ads_settlement_income_company_shop_daily_type (platform_code, stat_date);

