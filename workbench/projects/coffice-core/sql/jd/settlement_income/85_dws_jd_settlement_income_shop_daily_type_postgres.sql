CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_jd_settlement_income_shop_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
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

COMMENT ON TABLE dws.dws_jd_settlement_income_shop_daily_type IS '京东结算收入店铺日类型汇总DWS，仅按收支方向识别收入，不排除任何单据类型。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.stat_date IS '收入统计日期，取账单日期。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.income_type_code IS '京东费用项对应的稳定收入类型编码。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.income_type_name IS '京东费用项名称，用于DataEase收入类型占比。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.income_amount IS '店铺日收入类型金额，单位元。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.included_event_count IS '纳入本收入类型的收入方向单据数。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_jd_settlement_income_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_jd_settlement_income_type_date
    ON dws.dws_jd_settlement_income_shop_daily_type (income_type_code, stat_date);

