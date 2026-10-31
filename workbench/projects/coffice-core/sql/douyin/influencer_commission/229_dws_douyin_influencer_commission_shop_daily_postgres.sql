CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_douyin_influencer_commission_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    creator_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    recruitment_service_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_douyin_influencer_commission_shop_daily IS '抖音达人佣金店铺日DWS；资金单佣金与招商服务费取反后相加，正常费用为正、退款或冲回为负。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.stat_date IS '达人佣金统计日期，取资金动账时间日期。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.creator_commission_amount IS '店铺日达人佣金净费用，正常费用为正、冲回为负，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.recruitment_service_fee_amount IS '店铺日招商服务费净费用，正常费用为正、冲回为负，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.influencer_commission_amount IS '抖音达人佣金指标金额=达人佣金+招商服务费，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.included_event_count IS '佣金与招商服务费之和非零的资金动账事件数。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_influencer_commission_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_douyin_influencer_commission_date
    ON dws.dws_douyin_influencer_commission_shop_daily (stat_date);
