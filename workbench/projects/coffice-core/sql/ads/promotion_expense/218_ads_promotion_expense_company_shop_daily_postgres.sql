CREATE SCHEMA IF NOT EXISTS ads;

DROP TABLE IF EXISTS ads.ads_promotion_expense_company_daily;
DROP TABLE IF EXISTS ads.ads_promotion_expense_company_shop_daily;

CREATE TABLE ads.ads_promotion_expense_company_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code, shop_code)
);

COMMENT ON TABLE ads.ads_promotion_expense_company_shop_daily IS '七平台推广费公司店铺日ADS；抖音、拼多多、京东、天猫记录真实推广费，快手、视频号、小红书按有效DIM店铺和真实推广日期补零，服务推广费指标卡、趋势图及平台筛选器。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.stat_date IS '推广费统计日期，用作DataEase日期筛选和趋势横轴。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.platform_name IS '标准平台名称，用作DataEase平台筛选和趋势系列。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.company_code IS '按统计日期从DIM匹配的公司编码；未匹配为unmapped。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.company_name IS '按统计日期从DIM匹配的公司名称；未匹配为未匹配公司。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.shop_code IS '标准店铺编码，用于未来多店铺筛选。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.shop_name IS '标准店铺名称，用作DataEase店铺筛选字段。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.promotion_expense_amount IS '平台推广费日合计，支出为正，单位元；快手、视频号、小红书筛选占位行固定为0。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.included_detail_count IS '纳入本行推广费计算的来源明细数；筛选占位行固定为0。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.source_updated_at IS '参与汇总的DWS最晚来源更新时间；筛选占位行无业务来源，固定为NULL。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_promotion_expense_company_shop_daily.updated_at IS 'ADS记录最后更新时间。';

CREATE INDEX idx_ads_promotion_expense_company_date
    ON ads.ads_promotion_expense_company_shop_daily (company_code, stat_date);
CREATE INDEX idx_ads_promotion_expense_shop_date
    ON ads.ads_promotion_expense_company_shop_daily (platform_code, shop_code, stat_date);
CREATE INDEX idx_ads_promotion_expense_platform_date
    ON ads.ads_promotion_expense_company_shop_daily (platform_code, stat_date);
