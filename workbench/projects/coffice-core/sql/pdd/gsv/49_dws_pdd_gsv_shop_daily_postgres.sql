CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_pdd_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    merchant_received_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    store_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_pdd_gsv_shop_daily IS '拼多多GSV店铺日汇总表，一天、平台、店铺一行；仅纳入已发货待收货或已收货且无售后或售后取消的订单。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.stat_date IS 'GSV统计日期，来自订单成交时间。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.platform_code IS '平台编码，拼多多固定为pdd。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.platform_name IS '平台名称，拼多多固定为拼多多。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.shop_code IS '标准店铺编码，来自DWD的已确认DIM店铺。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.merchant_received_amount IS '纳入订单的商家实收金额合计，单位元。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.store_discount_amount IS '纳入订单的店铺优惠折扣合计，单位元，仅用于审计。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.gsv_amount IS '拼多多GSV，直接汇总纳入订单的商家实收金额，单位元。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.included_order_count IS '纳入本行GSV计算的订单数量。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_pdd_gsv_shop_daily_date
    ON dws.dws_pdd_gsv_shop_daily (stat_date);
