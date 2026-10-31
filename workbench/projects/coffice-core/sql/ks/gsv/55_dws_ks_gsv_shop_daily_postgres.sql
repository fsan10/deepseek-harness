CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'ks',
    platform_name VARCHAR(64) NOT NULL DEFAULT '快手',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_item_count BIGINT NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_ks_gsv_shop_daily IS '快手GSV店铺日汇总表，一天、平台、店铺一行；排除订单状态为交易关闭或售后状态为退款成功的商品行。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.stat_date IS 'GSV统计日期，支付时间优先、订单创建时间兜底。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.platform_code IS '平台编码，快手固定为ks。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.platform_name IS '平台名称，快手固定为快手。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.shop_code IS '标准店铺编码，来自DWD的已确认批次店铺上下文。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.gsv_amount IS '快手GSV，排除交易关闭和退款成功商品行后汇总实付款，单位元。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.included_item_count IS '纳入本行GSV计算的订单商品行数量。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.included_order_count IS '纳入本行GSV计算的去重订单数量。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_gsv_shop_daily_date
    ON dws.dws_ks_gsv_shop_daily (stat_date);
