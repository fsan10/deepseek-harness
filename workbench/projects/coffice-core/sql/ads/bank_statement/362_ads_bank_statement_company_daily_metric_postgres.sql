CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_bank_statement_company_daily_metric (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    metric_group_code VARCHAR(32) NOT NULL,
    metric_group_name VARCHAR(64) NOT NULL,
    metric_code VARCHAR(64) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, company_code, metric_code)
);

CREATE INDEX IF NOT EXISTS idx_ads_bank_statement_metric_company_date
    ON ads.ads_bank_statement_company_daily_metric (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_bank_statement_metric_group_date
    ON ads.ads_bank_statement_company_daily_metric (metric_group_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_bank_statement_metric_code_date
    ON ads.ads_bank_statement_company_daily_metric (metric_code, stat_date);

COMMENT ON TABLE ads.ads_bank_statement_company_daily_metric IS '银行流水经营指标公司日ADS；仅包含银行收入、费用和主营业务成本，作为DataEase银行指标唯一主数据集。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.stat_date IS '统计日期，来源银行交易日期transaction_date。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.platform_code IS '来源编码，固定为bank。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.platform_name IS '来源名称，固定为银行。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.company_code IS '公司稳定编码；由银行账号名称唯一匹配DIM，未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.company_name IS '公司展示名称；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.metric_group_code IS '指标组稳定编码：revenue收入、expense费用或cost成本。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.metric_group_name IS '指标组展示名称：收入、费用或成本。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.metric_code IS '银行指标分类稳定编码；覆盖两类收入、六类费用和主营业务成本。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.metric_name IS '银行指标分类展示名称，用于收入或费用占比图分类。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.metric_amount IS '指标净额，单位元；收入按净流入，费用和成本按净流出。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.included_detail_count IS '纳入公司日指标分类的财务拆分明细数；无明细的分类为0。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.source_updated_at IS '参与公司日汇总的DWS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.created_at IS 'ADS记录创建时间，带时区。';
COMMENT ON COLUMN ads.ads_bank_statement_company_daily_metric.updated_at IS 'ADS记录最后刷新时间，带时区。';
