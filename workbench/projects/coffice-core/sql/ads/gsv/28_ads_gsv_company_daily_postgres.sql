CREATE SCHEMA IF NOT EXISTS ads;

DROP TABLE IF EXISTS ads.ads_gsv_platform_daily;

CREATE TABLE IF NOT EXISTS ads.ads_gsv_company_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, company_code, shop_code)
);

ALTER TABLE ads.ads_gsv_company_daily
    ADD COLUMN IF NOT EXISTS shop_code VARCHAR(128),
    ADD COLUMN IF NOT EXISTS shop_name VARCHAR(255);
UPDATE ads.ads_gsv_company_daily
SET shop_code = 'legacy_unmapped', shop_name = '历史未刷新店铺'
WHERE shop_code IS NULL OR shop_name IS NULL;
ALTER TABLE ads.ads_gsv_company_daily
    ALTER COLUMN shop_code SET NOT NULL,
    ALTER COLUMN shop_name SET NOT NULL,
    DROP CONSTRAINT IF EXISTS ads_gsv_company_daily_pkey;
ALTER TABLE ads.ads_gsv_company_daily
    ADD CONSTRAINT ads_gsv_company_daily_pkey
    PRIMARY KEY (stat_date, platform_code, company_code, shop_code);

COMMENT ON TABLE ads.ads_gsv_company_daily IS '公司店铺维度GSV日指标ADS表，一天、平台、公司、店铺一行，供DataEase指标卡、趋势图和店铺分析使用。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.stat_date IS 'GSV统计日期，用作DataEase时间筛选字段。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.platform_name IS '平台展示名称。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.company_code IS '公司稳定编码，来自平台店铺公司DIM映射。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.company_name IS '公司完整名称，用作DataEase公司筛选字段。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.shop_code IS '标准店铺编码，来自平台DWS及DIM店铺映射，用作稳定店铺标识。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.shop_name IS '标准店铺名称，优先来自DIM，用作DataEase店铺筛选和店铺对比维度。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.gsv_amount IS '公司、店铺在对应平台的日销售额GSV，单位元。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.source_updated_at IS '参与本行汇总的DWS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_gsv_company_daily.updated_at IS 'ADS记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_gsv_company_daily_company
    ON ads.ads_gsv_company_daily (company_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_gsv_company_daily_platform
    ON ads.ads_gsv_company_daily (platform_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_ads_gsv_company_daily_shop
    ON ads.ads_gsv_company_daily (shop_code, stat_date);
