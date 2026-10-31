CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_bank_statement_account_daily_metric (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_account_name VARCHAR(256) NOT NULL,
    metric_group_code VARCHAR(32) NOT NULL,
    metric_group_name VARCHAR(64) NOT NULL,
    metric_code VARCHAR(64) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, source_account_name, metric_code)
);

CREATE INDEX IF NOT EXISTS idx_dws_bank_statement_metric_account_date
    ON dws.dws_bank_statement_account_daily_metric (source_account_name, stat_date);
CREATE INDEX IF NOT EXISTS idx_dws_bank_statement_metric_group_date
    ON dws.dws_bank_statement_account_daily_metric (metric_group_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dws_bank_statement_metric_code_date
    ON dws.dws_bank_statement_account_daily_metric (metric_code, stat_date);

COMMENT ON TABLE dws.dws_bank_statement_account_daily_metric IS '银行流水经营指标账号日DWS；统一输出银行收入、费用和主营业务成本九个分类，不包含任何平台结算数据。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.stat_date IS '统计日期，严格使用银行ODS交易日期transaction_date。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.platform_code IS '来源编码，银行流水固定为bank。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.platform_name IS '来源名称，银行流水固定为银行。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.source_account_name IS '银行账号名称，用于ADS按公司名称唯一映射标准公司编码。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.metric_group_code IS '指标组稳定编码：revenue收入、expense费用或cost成本。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.metric_group_name IS '指标组展示名称：收入、费用或成本。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.metric_code IS '银行指标分类稳定编码；覆盖两类收入、六类费用和主营业务成本。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.metric_name IS '银行指标分类展示名称，来源于财务费用类型标准名称。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.metric_amount IS '指标净额，单位元；收入按净流入，费用和成本按净流出，冲回保留负号。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.included_detail_count IS '纳入该指标分类的财务拆分明细数；当日该分类无明细时为0。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.source_updated_at IS '参与账号日统计的来源记录最晚更新时间。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.created_at IS 'DWS记录创建时间，带时区。';
COMMENT ON COLUMN dws.dws_bank_statement_account_daily_metric.updated_at IS 'DWS记录最后刷新时间，带时区。';
