CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_xhs_settlement_income_shop_daily_type (
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

COMMENT ON TABLE dws.dws_xhs_settlement_income_shop_daily_type IS '小红书结算收入店铺日类型汇总表，订单结算和收入型申诉调账按收入类型全部纳入，退款或收入冲回保留负数。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.stat_date IS '收入统计日期，取结算时间日期。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.platform_code IS '标准平台编码，固定为xhs。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.platform_name IS '平台展示名称，固定为小红书。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.income_type_code IS '由源交易类型映射的收入类型英文编码。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.income_type_name IS '收入类型中文名称；订单结算直接使用源交易类型，申诉调账收入固定使用申诉调账。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.income_amount IS '店铺日交易类型收入金额；退款或收入冲回可为负，单位元。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.included_event_count IS '纳入该类型的订单结算或申诉调账收入事件数。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_xhs_settlement_income_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_xhs_settlement_income_date
    ON dws.dws_xhs_settlement_income_shop_daily_type (stat_date);
