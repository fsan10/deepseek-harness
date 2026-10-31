CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_tmall_promotion_expense_shop_daily;

CREATE TABLE dws.dws_tmall_promotion_expense_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    taobao_union_spend_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    wanxiangtai_spend_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    excluded_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code)
);

COMMENT ON TABLE dws.dws_tmall_promotion_expense_shop_daily IS '天猫推广费店铺日DWS，等于淘宝联盟结算支出费用加万相台支出扣款操作金额。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.stat_date IS '推广费统计日期。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.platform_name IS '标准平台名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.taobao_union_spend_amount IS '淘宝联盟结算支出费用日合计，单位元。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.wanxiangtai_spend_amount IS '收支类型为支出且交易类型为扣款的万相台操作金额日合计，单位元。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.promotion_expense_amount IS '天猫推广费日合计，等于淘宝联盟与万相台两项之和，单位元。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.included_detail_count IS '纳入公式的淘宝联盟和万相台DWD明细数。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.excluded_detail_count IS '因万相台收支或交易类型不符而排除的DWD明细数。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.source_updated_at IS '参与本日来源的DWD最晚更新时间。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_promotion_expense_shop_daily.updated_at IS 'DWS记录最后更新时间。';

CREATE INDEX idx_dws_tmall_promotion_expense_date
    ON dws.dws_tmall_promotion_expense_shop_daily (stat_date);
