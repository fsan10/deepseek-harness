CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_wechat_channels_settlement_net_shop_daily (
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

COMMENT ON TABLE dws.dws_wechat_channels_settlement_net_shop_daily IS '视频号结算净额店铺日汇总表，两个批次和提现等全部动账类型均纳入。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.stat_date IS '结算净额统计日期，取记账时间日期。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.platform_code IS '标准平台编码，固定为wechat_channels。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.platform_name IS '平台展示名称，固定为视频号。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.income_amount IS '店铺日收入金额，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.expense_amount IS '店铺日支出金额，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.settlement_net_amount IS '店铺日计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.source_settlement_amount IS '店铺日源方向还原带符号流水金额，仅用于核验，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.validation_difference_amount IS '店铺日计算净额减源带符号流水金额的差额，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.included_event_count IS '纳入计算的全部动账事件数，不执行任何排除。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_settlement_net_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_wechat_channels_settlement_net_date
    ON dws.dws_wechat_channels_settlement_net_shop_daily (stat_date);

