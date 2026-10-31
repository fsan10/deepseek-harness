CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_bank_main_business_cost_account_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_account_name VARCHAR(256) NOT NULL,
    main_business_cost_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, source_account_name)
);

CREATE INDEX IF NOT EXISTS idx_dws_bank_main_business_cost_account_date
    ON dws.dws_bank_main_business_cost_account_daily (source_account_name, stat_date);

COMMENT ON TABLE dws.dws_bank_main_business_cost_account_daily IS '银行主营业务成本账号日DWS；读取财务已提交拆分明细，成本按净流出计算。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.stat_date IS '统计日期，使用银行ODS交易日期transaction_date。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.platform_code IS '来源平台编码，银行流水固定为bank。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.platform_name IS '来源平台名称，银行流水固定为银行。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.source_account_name IS '银行账号名称，用于ADS匹配标准公司。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.main_business_cost_amount IS '主营业务成本净额，借方流出为正成本、贷方退款或冲回为负成本，单位元。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.included_detail_count IS '纳入主营业务成本的财务拆分明细数；当日无符合记录时为0。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.source_updated_at IS '参与统计的财务拆分明细最晚更新时间。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.created_at IS 'DWS记录创建时间，带时区。';
COMMENT ON COLUMN dws.dws_bank_main_business_cost_account_daily.updated_at IS 'DWS记录最后刷新时间，带时区。';

