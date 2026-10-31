CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_platform_bank_total_revenue_company_daily_type (
    stat_date DATE NOT NULL,
    source_type_code VARCHAR(32) NOT NULL,
    source_type_name VARCHAR(64) NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    financial_direction_code VARCHAR(32) NOT NULL,
    financial_direction_name VARCHAR(64) NOT NULL,
    metric_group_code VARCHAR(64) NOT NULL,
    metric_group_name VARCHAR(128) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL,
    source_table_code VARCHAR(128) NOT NULL,
    metric_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date,
        source_type_code,
        platform_code,
        company_code,
        financial_direction_code,
        metric_group_code,
        primary_category_code,
        secondary_category_code,
        source_document_type
    ),
    CONSTRAINT chk_ads_platform_bank_financial_direction
        CHECK (financial_direction_code IN ('income', 'expense'))
);

CREATE INDEX IF NOT EXISTS idx_ads_platform_bank_summary_company_date
    ON ads.ads_platform_bank_total_revenue_company_daily_type (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_platform_bank_summary_direction_date
    ON ads.ads_platform_bank_total_revenue_company_daily_type (financial_direction_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_platform_bank_summary_group_date
    ON ads.ads_platform_bank_total_revenue_company_daily_type (metric_group_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_platform_bank_summary_platform_date
    ON ads.ads_platform_bank_total_revenue_company_daily_type (platform_code, stat_date);

COMMENT ON TABLE ads.ads_platform_bank_total_revenue_company_daily_type IS '平台与银行收入支出公司日分类汇总ADS；汇总平台主营收入、平台费用、独立推广费及银行收入费用成本，服务DataEase经营汇总看板。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.stat_date IS '统计日期；平台沿用来源ADS的stat_date，银行沿用transaction_date加工出的stat_date。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.source_type_code IS '来源大类编码：platform平台或bank银行。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.source_type_name IS '来源大类名称：平台或银行。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.platform_code IS '标准平台编码；银行数据固定为bank。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.platform_name IS '平台展示名称；银行数据固定为银行。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.company_code IS '公司稳定编码，沿用四张来源ADS；unmapped表示未匹配公司并会阻断正式刷新。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.company_name IS '公司展示名称，沿用来源ADS。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.financial_direction_code IS '财务方向编码：income收入或expense支出；银行成本归入expense。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.financial_direction_name IS '财务方向名称：收入或支出。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.metric_group_code IS '来源指标组编码：platform_main_business_income、platform_expense、independent_promotion_expense、bank_income、bank_expense或bank_cost。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.metric_group_name IS '来源指标组名称，用于区分平台主营收入、平台费用、独立推广费、银行收入、银行费用和银行主营业务成本。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.primary_category_code IS '一级分类编码；平台沿用原分类，独立推广费固定分类，银行沿用银行metric_code。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.primary_category_name IS '一级分类名称，用于收入和支出构成图。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.secondary_category_code IS '二级分类编码；平台沿用原分类，银行和独立推广费固定为all。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.secondary_category_name IS '二级分类名称；平台沿用原分类，银行和独立推广费固定为全部。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.source_document_type IS '来源单据类型；平台沿用settlement或fund，独立推广费为promotion_account，银行为bank_statement。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.source_table_code IS '直接来源ADS表名编码，用于四来源对账和审计。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.metric_amount IS '收入或支出净额，单位元；收入退款、费用冲回保留负数。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.included_detail_count IS '纳入本行汇总的来源明细数；独立推广费补零行可为0。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.source_updated_at IS '参与本行汇总的来源记录最晚更新时间。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.created_at IS 'ADS记录创建时间，带时区。';
COMMENT ON COLUMN ads.ads_platform_bank_total_revenue_company_daily_type.updated_at IS 'ADS记录最后刷新时间，带时区。';
