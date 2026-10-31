CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_douyin_promotion_expense_shop_daily;

CREATE TABLE dws.dws_douyin_promotion_expense_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    qianchuan_non_gift_spend_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    excluded_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_douyin_promotion_expense_shop_daily IS '抖音推广费店铺日DWS，推广费等于千川非赠款消耗。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.stat_date IS '推广费统计日期。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.platform_name IS '标准平台名称，固定为抖音。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.qianchuan_non_gift_spend_amount IS '千川非赠款消耗日合计，单位元。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.promotion_expense_amount IS '抖音推广费日合计，等于千川非赠款消耗，单位元。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.included_detail_count IS '纳入推广费计算的DWD明细数。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.excluded_detail_count IS '未纳入计算的DWD明细数；当前仅记录无有效金额记录。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.source_updated_at IS '参与汇总的DWD最晚来源更新时间。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_promotion_expense_shop_daily.updated_at IS 'DWS记录最后更新时间。';

CREATE INDEX idx_dws_douyin_promotion_expense_date
    ON dws.dws_douyin_promotion_expense_shop_daily (stat_date);
