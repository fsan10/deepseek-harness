CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_bank_influencer_commission_account_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_account_name VARCHAR(256) NOT NULL,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, source_account_name)
);

COMMENT ON TABLE dws.dws_bank_influencer_commission_account_daily IS '银行达人佣金账号日DWS；仅纳入销售费用下入账-达人佣金费用的财务已提交拆分明细。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.stat_date IS '统计日期，取银行交易日期。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.platform_code IS '来源平台编码，固定为bank。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.platform_name IS '来源平台名称，固定为银行。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.source_account_name IS '银行账号名称，用于ADS唯一解析公司。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.influencer_commission_amount IS '销售费用-入账达人佣金费用净额，借方流出为正、贷方冲回为负，单位元。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.included_detail_count IS '纳入计算的财务拆分明细数。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_bank_influencer_commission_account_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_bank_influencer_commission_account_date
    ON dws.dws_bank_influencer_commission_account_daily (source_account_name, stat_date);

