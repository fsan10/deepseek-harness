CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_wechat_channels_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'wechat_channels',
    platform_name VARCHAR(64) NOT NULL DEFAULT '视频号',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    actual_received_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    activity_merchant_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    source_line_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_wechat_channels_gsv_shop_daily IS '视频号GSV店铺日汇总表；仅纳入已完成且任一商品售后均不是退货退款完成或退款完成的订单。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.stat_date IS 'GSV统计日期，支付时间优先、订单下单时间兜底。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.platform_code IS '平台编码，视频号固定为wechat_channels。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.platform_name IS '平台名称，固定为视频号。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.shop_code IS '标准店铺编码，来自DWD批次店铺上下文。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.actual_received_amount IS '纳入订单的订单实际收款金额合计，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.activity_merchant_subsidy_amount IS '纳入订单的活动商家补贴合计，单位元，仅用于审计。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.gsv_amount IS '视频号GSV，直接汇总纳入订单的订单实际收款金额，单位元。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.included_order_count IS '纳入本行GSV计算的订单数量。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.source_line_count IS '纳入订单在ODS最新批次对应的商品明细行数。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_wechat_channels_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_wechat_channels_gsv_shop_daily_date
    ON dws.dws_wechat_channels_gsv_shop_daily (stat_date);
