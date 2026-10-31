CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_jd_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    source_line_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_jd_gsv_shop_daily IS '京东GSV店铺日汇总表，一天、平台、店铺一行；排除订单状态以删除标记开头的订单。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.stat_date IS 'GSV统计日期，付款确认时间优先、下单时间兜底。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.platform_code IS '平台编码，京东固定为jd。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.platform_name IS '平台名称，京东固定为京东。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.shop_code IS '标准店铺编码，来自DWD的DIM店铺匹配结果。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.gsv_amount IS '京东GSV，排除删除状态后汇总订单粒度的应付金额，单位元。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.included_order_count IS '纳入本行GSV计算的去重订单数量。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.source_line_count IS '纳入订单在ODS最新批次对应的商品明细行数。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.source_updated_at IS '本行参与汇总的DWD记录最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_jd_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_jd_gsv_shop_daily_date
    ON dws.dws_jd_gsv_shop_daily (stat_date);
