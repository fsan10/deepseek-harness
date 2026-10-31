CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_settlement_net_company_shop_daily (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    display_expense_amount NUMERIC(18,2),
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_event_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, company_code, shop_code)
);

ALTER TABLE ads.ads_settlement_net_company_shop_daily
    ADD COLUMN IF NOT EXISTS display_expense_amount NUMERIC(18,2);

COMMENT ON TABLE ads.ads_settlement_net_company_shop_daily IS '结算净额公司店铺日ADS，结算净额由收入减支出计算，源结算金额只用于核验。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.stat_date IS '结算净额统计日期，用于DataEase日期筛选。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.platform_name IS '平台展示名称。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.company_code IS '公司稳定编码，来自DIM；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.company_name IS '公司名称，来自DIM；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.income_amount IS '指定公司店铺日收入金额，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.expense_amount IS '指定公司店铺日支出金额，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.display_expense_amount IS '来源DWS指定的带符号展示支出汇总，单位元；NULL表示来源未指定展示金额，展示时沿用expense_amount，不改变内部净额公式。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.settlement_net_amount IS '结算净额指标字段，等于收入减支出，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.source_settlement_amount IS '源结算金额汇总，只用于核验，不作为指标取值。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.validation_difference_amount IS '计算净额减源结算金额的核验差额；非零表示平台源数据不满足收入减支出公式，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.included_event_count IS '纳入计算的结算事件数。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.source_updated_at IS '参与汇总的DWS记录最晚来源时间。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_daily.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_company_date
    ON ads.ads_settlement_net_company_shop_daily (company_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_shop_date
    ON ads.ads_settlement_net_company_shop_daily (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_platform_date
    ON ads.ads_settlement_net_company_shop_daily (platform_code, stat_date);
