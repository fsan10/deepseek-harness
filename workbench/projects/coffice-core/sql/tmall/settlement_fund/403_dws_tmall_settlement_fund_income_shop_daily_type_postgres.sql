CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_settlement_fund_income_shop_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_type_code VARCHAR(64) NOT NULL,
    income_type_name VARCHAR(128) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, income_type_code)
);

COMMENT ON TABLE dws.dws_tmall_settlement_fund_income_shop_daily_type IS '天猫资金来源结算收入店铺日类型汇总；仅交易收款/交易付款，退款不冲减收入。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.stat_date IS '结算统计日期，来自资金入帐日期或发生时间日期部分。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.income_type_code IS '资金结算收入类型编码，当前为fund_goods_income。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.income_type_name IS '资金结算收入类型名称，当前为货款收入。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.income_amount IS '交易收款/交易付款正向收入金额，不减交易退款，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.included_event_count IS '纳入收入汇总的资金事件数，不含退款、提现和内部转账。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.source_updated_at IS '参与汇总的资金DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_fund_income_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_settlement_fund_income_date
    ON dws.dws_tmall_settlement_fund_income_shop_daily_type (stat_date);
