CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_main_business_revenue_company_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    main_business_revenue_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code)
);

CREATE INDEX IF NOT EXISTS idx_ads_main_business_revenue_company_date
    ON ads.ads_main_business_revenue_company_daily (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_main_business_revenue_platform_date
    ON ads.ads_main_business_revenue_company_daily (platform_code, stat_date);

COMMENT ON TABLE ads.ads_main_business_revenue_company_daily IS '主营业务收入公司日ADS，服务主营业务收入指标卡和可选日趋势图；已排除平台提现。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.stat_date IS '统计日期，用于DataEase日期筛选。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.platform_code IS '来源平台编码，银行流水为bank。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.platform_name IS '来源平台名称，银行流水为银行。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.company_code IS '公司稳定编码，通过银行账号名称匹配DIM公司；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.company_name IS '公司名称，来自DIM；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.main_business_revenue_amount IS '主营业务收入指标金额，已排除平台提现，单位元。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.included_detail_count IS '纳入计算的财务拆分明细数。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.source_updated_at IS '参与汇总的DWS记录最晚来源时间。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.created_at IS 'ADS记录创建时间，带时区。';
COMMENT ON COLUMN ads.ads_main_business_revenue_company_daily.updated_at IS 'ADS记录最后刷新时间，带时区。';

