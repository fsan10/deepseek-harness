CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_bank_total_revenue_account_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_account_name VARCHAR(256) NOT NULL,
    revenue_type_code VARCHAR(64) NOT NULL,
    revenue_type_name VARCHAR(100) NOT NULL,
    revenue_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, source_account_name, revenue_type_code)
);

CREATE INDEX IF NOT EXISTS idx_dws_bank_total_revenue_account_date
    ON dws.dws_bank_total_revenue_account_daily_type (source_account_name, stat_date);
CREATE INDEX IF NOT EXISTS idx_dws_bank_total_revenue_type_date
    ON dws.dws_bank_total_revenue_account_daily_type (revenue_type_code, stat_date);

COMMENT ON TABLE dws.dws_bank_total_revenue_account_daily_type IS '银行总营收组成账号日类型DWS；输出主营业务收入和营业外收入，平台收入在ADS由现有结算净额ADS汇总。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.stat_date IS '统计日期，使用银行ODS交易日期transaction_date。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.platform_code IS '来源平台编码，银行流水固定为bank。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.platform_name IS '来源平台名称，银行流水固定为银行。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.source_account_name IS '银行账号名称，用于ADS匹配标准公司。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.revenue_type_code IS '营收分类稳定编码：main_business_revenue或non_operating_revenue。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.revenue_type_name IS '营收分类名称：主营业务收入或营业外收入。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.revenue_amount IS '对应营收分类净额，单位元；主营业务收入排除平台提现，冲回保留负号。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.included_detail_count IS '纳入该营收分类的财务拆分明细数；无符合记录时为0。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.source_updated_at IS '参与统计的财务拆分明细最晚更新时间。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.created_at IS 'DWS记录创建时间，带时区。';
COMMENT ON COLUMN dws.dws_bank_total_revenue_account_daily_type.updated_at IS 'DWS记录最后刷新时间，带时区。';

