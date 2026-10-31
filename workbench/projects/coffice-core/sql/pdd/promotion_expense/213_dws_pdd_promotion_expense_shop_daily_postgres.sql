CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_pdd_promotion_expense_shop_daily;

CREATE TABLE dws.dws_pdd_promotion_expense_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    cash_outflow_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    excluded_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_pdd_promotion_expense_shop_daily IS '拼多多推广费店铺日DWS，只纳入资金类型为现金且流水类型为支出的交易金额。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.stat_date IS '推广费统计日期。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.platform_name IS '标准平台名称，固定为拼多多。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.cash_outflow_amount IS '现金支出交易金额日合计，单位元。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.promotion_expense_amount IS '拼多多推广费日合计，等于现金支出交易金额，单位元。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.included_detail_count IS '满足现金且支出的DWD明细数。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.excluded_detail_count IS '不满足现金且支出筛选的DWD明细数。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.source_updated_at IS '参与本日来源的DWD最晚更新时间。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_promotion_expense_shop_daily.updated_at IS 'DWS记录最后更新时间。';

CREATE INDEX idx_dws_pdd_promotion_expense_date
    ON dws.dws_pdd_promotion_expense_shop_daily (stat_date);
