CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_total_revenue_company_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    revenue_type_code VARCHAR(64) NOT NULL,
    revenue_type_name VARCHAR(100) NOT NULL,
    revenue_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code, revenue_type_code)
);

CREATE INDEX IF NOT EXISTS idx_ads_total_revenue_company_date
    ON ads.ads_total_revenue_company_daily_type (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_total_revenue_type_date
    ON ads.ads_total_revenue_company_daily_type (revenue_type_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_total_revenue_platform_date
    ON ads.ads_total_revenue_company_daily_type (platform_code, stat_date);

COMMENT ON TABLE ads.ads_total_revenue_company_daily_type IS '总营收公司日分类ADS；总营收等于全平台结算净额、主营业务收入和营业外收入之和，服务指标卡和收入分类占比图。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.stat_date IS '统计日期；银行使用transaction_date，平台结算净额使用stat_date。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.platform_code IS '来源组编码：bank表示银行分类，all_platforms表示全平台结算净额汇总。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.platform_name IS '来源组名称：银行或全平台结算。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.company_code IS '公司稳定编码；平台收入沿用结算净额ADS，银行收入通过账号名称匹配DIM；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.company_name IS '公司名称；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.revenue_type_code IS '收入分类稳定编码：platform_revenue、main_business_revenue或non_operating_revenue。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.revenue_type_name IS '收入分类展示名称：平台收入、主营业务收入或营业外收入。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.revenue_amount IS '收入分类金额，单位元；三类求和为总营收。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.included_detail_count IS '平台收入为纳入结算事件数，银行收入为纳入财务拆分明细数。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.source_updated_at IS '参与汇总的来源记录最晚更新时间。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.created_at IS 'ADS记录创建时间，带时区。';
COMMENT ON COLUMN ads.ads_total_revenue_company_daily_type.updated_at IS 'ADS记录最后刷新时间，带时区。';

