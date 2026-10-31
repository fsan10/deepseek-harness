CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_total_expense_company_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    expense_type_code VARCHAR(64) NOT NULL,
    expense_type_name VARCHAR(100) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code, expense_type_code)
);

CREATE INDEX IF NOT EXISTS idx_ads_total_expense_company_date
    ON ads.ads_total_expense_company_daily_type (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_total_expense_type_date
    ON ads.ads_total_expense_company_daily_type (expense_type_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_total_expense_platform_date
    ON ads.ads_total_expense_company_daily_type (platform_code, stat_date);

COMMENT ON TABLE ads.ads_total_expense_company_daily_type IS '总费用公司日分类ADS；六类费用求和为总费用，服务指标卡和各费用占比图。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.stat_date IS '统计日期，用于DataEase日期筛选。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.platform_code IS '来源平台编码，银行流水为bank。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.platform_name IS '来源平台名称，银行流水为银行。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.company_code IS '公司稳定编码，通过银行账号名称匹配DIM；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.company_name IS '公司名称，来自DIM；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.expense_type_code IS '费用分类稳定编码。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.expense_type_name IS '费用分类展示名称。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.expense_amount IS '费用分类净额，单位元；六类求和为总费用。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.included_detail_count IS '纳入计算的财务拆分明细数。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.source_updated_at IS '参与汇总的DWS记录最晚来源时间。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.created_at IS 'ADS记录创建时间，带时区。';
COMMENT ON COLUMN ads.ads_total_expense_company_daily_type.updated_at IS 'ADS记录最后刷新时间，带时区。';

