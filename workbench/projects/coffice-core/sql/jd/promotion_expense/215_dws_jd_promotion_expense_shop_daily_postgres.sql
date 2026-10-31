CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_jd_promotion_expense_shop_daily;

CREATE TABLE dws.dws_jd_promotion_expense_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    jd_tong_spend_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    jd_union_spend_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    excluded_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_jd_promotion_expense_shop_daily IS '京东推广费店铺日DWS，等于全站营销扣费京东通支出加京东联盟结算金额。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.stat_date IS '推广费统计日期。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.platform_code IS '标准平台编码，固定为jd。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.platform_name IS '标准平台名称，固定为京东。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.jd_tong_spend_amount IS '交易类型为全站营销扣费的京东通支出日合计，单位元。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.jd_union_spend_amount IS '京东联盟结算金额日合计，单位元。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.promotion_expense_amount IS '京东推广费日合计，等于京东通与京东联盟两项之和，单位元。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.included_detail_count IS '纳入公式的京东通和京东联盟DWD明细数。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.excluded_detail_count IS '因京东通交易类型不符而排除的DWD明细数。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.source_updated_at IS '参与本日来源的DWD最晚更新时间。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_jd_promotion_expense_shop_daily.updated_at IS 'DWS记录最后更新时间。';

CREATE INDEX idx_dws_jd_promotion_expense_date
    ON dws.dws_jd_promotion_expense_shop_daily (stat_date);
