CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_gsv_promotion_expense_company_shop_monthly (
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    gsv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    actual_promotion_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    roi NUMERIC(18,6),
    gsv_source_updated_at TIMESTAMPTZ,
    promotion_source_updated_at TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (stat_month, platform_code, company_code, shop_code)
);

COMMENT ON TABLE ads.ads_gsv_promotion_expense_company_shop_monthly IS 'GSV与实际平台推广费公司店铺月度ADS；一行对应自然月、平台、公司和店铺，按月度汇总后计算ROI，供DataEase月度明细表和汇总指标使用。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.stat_month IS '统计月份首日，用作DataEase月度时间筛选和表格月份维度。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.platform_code IS '标准平台编码，来自GSV日ADS。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.platform_name IS '平台展示名称，来自GSV日ADS。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.company_code IS '公司稳定编码，来自GSV日ADS按统计日期匹配DIM后的结果。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.company_name IS '公司展示名称，来自GSV日ADS按统计日期匹配DIM后的结果。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.shop_code IS '标准店铺编码，来自GSV日ADS。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.shop_name IS '标准店铺名称，来自GSV日ADS。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.gsv_amount IS '对应自然月、平台、公司和店铺的销售额GSV月合计，单位元。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.actual_promotion_expense_amount IS '对应自然月、平台、公司和店铺的实际平台推广费月合计，来源推广费日ADS，单位元；GSV有记录但推广费无匹配时为0。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.roi IS '月度ROI=GSV月合计÷实际平台推广费月合计，保留6位小数；实际推广费为0时为NULL，单位为倍而非金额。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.gsv_source_updated_at IS '参与本月GSV汇总的日ADS记录最晚来源更新时间。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.promotion_source_updated_at IS '参与本月推广费汇总的日ADS记录最晚来源更新时间；无匹配推广费时为NULL。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.source_updated_at IS 'GSV与推广费两类来源更新时间的较晚值。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.created_at IS '月度ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_gsv_promotion_expense_company_shop_monthly.updated_at IS '月度ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_gsv_promotion_monthly_platform
    ON ads.ads_gsv_promotion_expense_company_shop_monthly (stat_month, platform_code);

CREATE INDEX IF NOT EXISTS idx_ads_gsv_promotion_monthly_company
    ON ads.ads_gsv_promotion_expense_company_shop_monthly (stat_month, company_code);

CREATE INDEX IF NOT EXISTS idx_ads_gsv_promotion_monthly_shop
    ON ads.ads_gsv_promotion_expense_company_shop_monthly (stat_month, shop_code);
