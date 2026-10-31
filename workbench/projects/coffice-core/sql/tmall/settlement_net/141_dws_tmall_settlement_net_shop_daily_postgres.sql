CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_settlement_net_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
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

COMMENT ON TABLE dws.dws_tmall_settlement_net_shop_daily IS '天猫结算净额店铺日汇总表，收入和八类支出全部按账期纳入，净额由收入减支出计算。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.stat_date IS '结算净额统计日期，取源账期。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.income_amount IS '店铺日收入金额，订单实际金额不减退款，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.expense_amount IS '店铺日支出净额，退款冲回保留负号，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.settlement_net_amount IS '店铺日计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.source_settlement_amount IS '店铺日两张源表带符号组成金额，不是独立源结算金额，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.validation_difference_amount IS '计算净额减源方向组成金额的差额，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.included_event_count IS '纳入计算的收入与支出ODS事件数，包括金额为0的记录。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_settlement_net_date
    ON dws.dws_tmall_settlement_net_shop_daily (stat_date);

