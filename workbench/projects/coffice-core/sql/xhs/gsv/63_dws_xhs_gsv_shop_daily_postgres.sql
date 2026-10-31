CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_xhs_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    merchant_receivable_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    shop_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_item_count BIGINT NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_xhs_gsv_shop_daily IS '小红书GSV店铺日汇总表；仅纳入订单状态为已完成且售后状态为无售后的SKU商品行。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.stat_date IS 'GSV统计日期，支付时间优先、订单创建时间兜底。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.platform_code IS '平台编码，小红书固定为xhs。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.platform_name IS '平台名称，固定为小红书。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.shop_code IS '标准店铺编码，来自DWD批次店铺上下文。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.merchant_receivable_amount IS '纳入SKU行的商家应收金额（支付金额）合计，单位元。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.shop_discount_amount IS '纳入SKU行的店铺优惠合计，单位元，仅用于审计。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.gsv_amount IS '小红书GSV，直接汇总纳入SKU行的商家应收金额（支付金额），单位元。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.included_item_count IS '纳入本行GSV计算的SKU商品行数量。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.included_order_count IS '纳入本行GSV计算的去重订单数量。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_xhs_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_xhs_gsv_shop_daily_date ON dws.dws_xhs_gsv_shop_daily (stat_date);
