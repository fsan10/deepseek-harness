CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_gsv_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_order_count BIGINT NOT NULL DEFAULT 0,
    included_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_tmall_gsv_shop_daily IS '天猫GSV店铺日DWS；排除交易关闭、退款成功及商品标题包含购物金的子订单后汇总买家实付金额，并分别保留唯一主订单数和子订单数。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.stat_date IS 'GSV统计日期，付款时间优先、订单创建时间兜底。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.shop_code IS '标准店铺编码，来自天猫GSV DWD。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.shop_name IS '标准店铺名称，来自天猫GSV DWD。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.gsv_amount IS '非交易关闭、非退款成功且商品标题不包含购物金的子订单买家实付金额合计，单位元。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.included_order_count IS '纳入GSV的唯一主订单数量。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.included_sub_order_count IS '纳入GSV的子订单明细数量。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.source_updated_at IS '参与本店铺日汇总的DWD最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_gsv_shop_daily.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_gsv_shop_daily_date
    ON dws.dws_tmall_gsv_shop_daily (stat_date);
