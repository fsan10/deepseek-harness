CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_settlement_income_shop_daily_type (
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

COMMENT ON TABLE dws.dws_tmall_settlement_income_shop_daily_type IS '天猫结算收入店铺日类型汇总表，收入直接汇总订单实际金额，不扣减退款金额。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.stat_date IS '收入统计日期，取源账期。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.income_type_code IS '由源账单大类映射的收入类型英文编码。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.income_type_name IS '收入类型中文名称，直接使用源账单大类。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.income_amount IS '店铺日收入金额，汇总订单实际金额且不减退款，单位元。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.included_event_count IS '订单实际金额非零且纳入该类型的收入事件数。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_settlement_income_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_settlement_income_date
    ON dws.dws_tmall_settlement_income_shop_daily_type (stat_date);

