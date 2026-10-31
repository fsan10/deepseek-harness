CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_douyin_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(128) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_douyin_gsv_shop_daily IS '抖音GSV店铺日汇总表，一天、平台、店铺一行；执行本指标固定的订单和售后筛选。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.stat_date IS 'GSV统计日期。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.platform_code IS '平台编码，抖音固定为douyin。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.platform_name IS '平台名称，抖音固定为抖音。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.shop_code IS '店铺编码。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.shop_name IS '店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.gsv_amount IS '销售额GSV，订单应付金额加优惠总金额减商家实际承担优惠金额，单位元。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.included_sub_order_count IS '纳入本行GSV计算的子订单数量。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_gsv_shop_daily.updated_at IS 'DWS记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_douyin_gsv_shop_daily_date
    ON dws.dws_douyin_gsv_shop_daily (stat_date);
