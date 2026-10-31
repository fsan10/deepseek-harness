CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_settlement_net_company_shop_monthly (
    stat_month DATE NOT NULL,
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

    PRIMARY KEY (stat_month, platform_code, company_code, shop_code)
);

ALTER TABLE ads.ads_settlement_net_company_shop_monthly
    ADD COLUMN IF NOT EXISTS display_expense_amount NUMERIC(18,2);

COMMENT ON TABLE ads.ads_settlement_net_company_shop_monthly IS '结算净额公司店铺月度ADS底表；由结算净额日ADS按自然月汇总，保留收入、支出、净额和源金额核验字段，供DataEase月度透视视图使用。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.stat_month IS '统计月份首日，用于DataEase月份列和月份筛选。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.platform_code IS '标准平台编码，来自结算净额日ADS。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.platform_name IS '平台展示名称，来自结算净额日ADS。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.company_code IS '公司稳定编码，来自日ADS按统计日期匹配DIM后的结果；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.company_name IS '公司展示名称，来自日ADS按统计日期匹配DIM后的结果；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.shop_code IS '标准店铺编码，来自结算净额日ADS。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.shop_name IS '标准店铺名称，来自结算净额日ADS。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.income_amount IS '对应自然月、平台、公司和店铺的收入合计，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.expense_amount IS '对应自然月、平台、公司和店铺的支出合计，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.display_expense_amount IS '对应自然月来源日ADS指定的带符号展示支出汇总，单位元；NULL时展示沿用expense_amount，内部净额仍按收入减正向支出计算。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.settlement_net_amount IS '对应自然月、平台、公司和店铺的结算净额，等于收入合计减支出合计，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.source_settlement_amount IS '日ADS源结算金额的月合计，仅用于源数据核验，不作为指标取值，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.validation_difference_amount IS '月度计算结算净额减源结算金额的核验差额；非零表示源金额与收入减支出口径不一致，单位元。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.included_event_count IS '对应自然月纳入结算净额计算的结算事件数。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.source_updated_at IS '参与月度汇总的日ADS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.created_at IS '月度ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_settlement_net_company_shop_monthly.updated_at IS '月度ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_monthly_platform
    ON ads.ads_settlement_net_company_shop_monthly (stat_month, platform_code);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_monthly_company
    ON ads.ads_settlement_net_company_shop_monthly (stat_month, company_code);
CREATE INDEX IF NOT EXISTS idx_ads_settlement_net_monthly_shop
    ON ads.ads_settlement_net_company_shop_monthly (stat_month, shop_code);
