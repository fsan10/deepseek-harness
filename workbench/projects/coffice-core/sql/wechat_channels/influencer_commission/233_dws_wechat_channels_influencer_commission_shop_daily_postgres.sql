CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_wechat_channels_influencer_commission_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    creator_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    agency_service_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_wechat_channels_influencer_commission_shop_daily IS '视频号达人佣金店铺日DWS；仅纳入动帐类型为达人佣金或带货机构服务费的流水。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.stat_date IS '达人佣金统计日期，取记账时间日期。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.platform_code IS '标准平台编码，固定为wechat_channels。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.platform_name IS '平台展示名称，固定为视频号。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.creator_commission_amount IS '动帐类型为达人佣金的带符号费用，支出为正、收入冲回为负，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.agency_service_fee_amount IS '动帐类型为带货机构服务费的带符号费用，支出为正、收入冲回为负，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.influencer_commission_amount IS '视频号达人佣金指标金额=达人佣金+带货机构服务费，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.included_event_count IS '纳入两个目标动帐类型且带符号金额非零的流水数。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_influencer_commission_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_wechat_channels_influencer_commission_date
    ON dws.dws_wechat_channels_influencer_commission_shop_daily (stat_date);

