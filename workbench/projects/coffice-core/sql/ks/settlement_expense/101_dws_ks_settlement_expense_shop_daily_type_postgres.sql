CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_settlement_expense_shop_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    expense_type_code VARCHAR(64) NOT NULL,
    expense_type_name VARCHAR(128) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, expense_type_code)
);

COMMENT ON TABLE dws.dws_ks_settlement_expense_shop_daily_type IS '快手结算支出店铺日类型汇总表，全量纳入所有结算记录并按合计支出的组成字段拆分。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.stat_date IS '支出统计日期，取实际结算时间日期。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.expense_type_code IS '支出组成类型英文编码。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.expense_type_name IS '支出组成类型中文名称。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.expense_amount IS '店铺日支出类型金额，所有类型之和等于支出金额，单位元。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.included_event_count IS '该支出类型金额非零的结算事件数。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_settlement_expense_shop_daily_type.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_settlement_expense_date
    ON dws.dws_ks_settlement_expense_shop_daily_type (stat_date);

