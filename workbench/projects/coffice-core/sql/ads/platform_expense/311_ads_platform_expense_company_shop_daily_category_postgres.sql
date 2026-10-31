CREATE SCHEMA IF NOT EXISTS ads;

CREATE TABLE IF NOT EXISTS ads.ads_platform_expense_company_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    company_code VARCHAR(32) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    mapping_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date,
        platform_code,
        company_code,
        shop_code,
        source_document_type,
        secondary_category_code
    )
);

ALTER TABLE ads.ads_platform_expense_company_shop_daily_category
    ALTER COLUMN secondary_category_code TYPE VARCHAR(128),
    ALTER COLUMN secondary_category_name TYPE VARCHAR(768);

COMMENT ON TABLE ads.ads_platform_expense_company_shop_daily_category IS '七平台费用公司店铺日分类ADS；统一接入各平台结算或资金费用，服务平台总费用指标卡及人工一级分类、平台二级分类明细图。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.stat_date IS '平台费用统计日期，用于DataEase日期筛选和趋势横轴。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.company_code IS '公司稳定编码，来自dim.dim_platform_shop_company；未匹配时为unmapped。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.company_name IS '公司名称，来自dim.dim_platform_shop_company；未匹配时为未匹配公司。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.primary_category_code IS '财务人工维护的一级费用分类编码；指标卡或图表按该字段汇总。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.primary_category_name IS '财务人工维护的一级费用分类名称。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.secondary_category_code IS '平台原始费用字段或动账场景对应的稳定二级分类编码。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.secondary_category_name IS '平台原始费用字段、原始动账场景或经确认标准化的业务类型加备注，用于费用明细和一级到二级下钻。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.source_document_type IS '费用来源单据类型；settlement或fund。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.expense_amount IS '平台费用净额；正常费用为正、退款或费用退回为负，单位元。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.included_detail_count IS '金额非零且纳入平台费用的来源明细数。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.source_detail_count IS '参与汇总的全部来源明细数。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.source_updated_at IS '参与汇总的DWS来源记录最晚时间。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.mapping_updated_at IS '本行费用映射最后更新时间。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.created_at IS 'ADS记录创建时间。';
COMMENT ON COLUMN ads.ads_platform_expense_company_shop_daily_category.updated_at IS 'ADS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_ads_platform_expense_company_date
    ON ads.ads_platform_expense_company_shop_daily_category (
        company_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_ads_platform_expense_platform_date
    ON ads.ads_platform_expense_company_shop_daily_category (
        platform_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_ads_platform_expense_primary_date
    ON ads.ads_platform_expense_company_shop_daily_category (
        primary_category_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_ads_platform_expense_secondary_date
    ON ads.ads_platform_expense_company_shop_daily_category (
        secondary_category_code, stat_date
    );
