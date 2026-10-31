CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_jd_settlement_net_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_jd_settlement_net_shop_daily IS '京东结算净额店铺日汇总DWS，全量纳入所有单据类型，结算净额等于收入减支出。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.stat_date IS '结算净额统计日期，取账单日期。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.income_amount IS '店铺日收入金额，单位元。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.expense_amount IS '店铺日支出金额，对源负数支出取反，单位元。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.settlement_net_amount IS '店铺日计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.source_settlement_amount IS '店铺日源带符号金额汇总，用于核验结算净额。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.validation_difference_amount IS '店铺日计算净额与源带符号金额差额，必须为0。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.included_event_count IS '纳入计算的最新单据数。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_jd_settlement_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_jd_settlement_net_date
    ON dws.dws_jd_settlement_net_shop_daily (stat_date);

