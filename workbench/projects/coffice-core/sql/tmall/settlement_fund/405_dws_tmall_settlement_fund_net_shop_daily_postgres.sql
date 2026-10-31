CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_settlement_fund_net_shop_daily (
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

COMMENT ON TABLE dws.dws_tmall_settlement_fund_net_shop_daily IS '天猫资金来源结算净额店铺日汇总；净额严格按收入减支出计算，资金带符号组成金额仅作核验。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.stat_date IS '结算净额统计日期，来自资金入帐日期或发生时间日期部分。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.income_amount IS '交易收款/交易付款收入金额，不减退款，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.expense_amount IS '已识别平台费用支出金额，扣款退回保留负号，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.settlement_net_amount IS '计算结算净额=收入金额-支出金额，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.source_settlement_amount IS '收入候选与费用候选资金带符号金额组成的核验值，不是独立源结算金额，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.validation_difference_amount IS '计算结算净额减资金带符号组成金额，单位元；资金来源模式下应为0。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.included_event_count IS '纳入净额计算的收入与费用事件数。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.source_updated_at IS '参与汇总的资金DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_settlement_fund_net_date
    ON dws.dws_tmall_settlement_fund_net_shop_daily (stat_date);
