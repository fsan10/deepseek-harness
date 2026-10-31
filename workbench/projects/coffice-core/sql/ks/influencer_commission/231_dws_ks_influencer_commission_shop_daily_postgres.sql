CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_influencer_commission_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    talent_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    leader_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    included_refund_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_ks_influencer_commission_shop_daily IS '快手达人佣金店铺日DWS；达人佣金等于达人佣金、团长佣金和其他收费之和，退款记录全部纳入。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.stat_date IS '达人佣金统计日期，取实际结算时间日期。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.talent_commission_amount IS '店铺日达人佣金费用，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.leader_commission_amount IS '店铺日团长佣金费用，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.other_fee_amount IS '店铺日其他收费费用，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.influencer_commission_amount IS '快手达人佣金指标金额=达人佣金+团长佣金+其他收费，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.included_event_count IS '三个组成金额之和非零的结算事件数，包括退款记录。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.included_refund_event_count IS '纳入计算且源订单退款金额大于0的结算事件数。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.source_updated_at IS '参与汇总的DWD记录最晚来源时间。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_influencer_commission_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_influencer_commission_date
    ON dws.dws_ks_influencer_commission_shop_daily (stat_date);

