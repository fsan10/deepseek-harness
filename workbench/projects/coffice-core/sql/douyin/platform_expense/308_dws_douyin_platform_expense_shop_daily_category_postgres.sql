CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_douyin_platform_expense_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(96) NOT NULL,
    secondary_category_name VARCHAR(128) NOT NULL,
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
        shop_code,
        source_document_type,
        secondary_category_code
    )
);

COMMENT ON TABLE dws.dws_douyin_platform_expense_shop_daily_category IS '抖音平台费用店铺日分类DWS；通过独立平台费用映射表纳入费用，并同时保留人工一级分类和平台原始二级分类。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.stat_date IS '费用统计日期；结算费用取结算日期，资金费用取动账日期。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.primary_category_code IS '财务人工维护的一级费用分类编码；看板按该字段汇总避免重复计算。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.primary_category_name IS '财务人工维护的一级费用分类名称。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.secondary_category_code IS '平台原始费用字段或动账场景对应的稳定二级分类编码。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.secondary_category_name IS '平台原始费用字段名或动账场景名，不做人工合并。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.source_document_type IS '费用来源单据类型；settlement或fund。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.expense_amount IS '店铺日二级分类净费用；正常费用为正、费用退回为负，单位元。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.included_detail_count IS '金额非零且被映射纳入平台费用的来源明细数。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.source_detail_count IS '参与本行汇总的全部来源明细数，包含零金额结算费用字段。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.source_updated_at IS '参与汇总的DWD来源记录最晚时间。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.mapping_updated_at IS '本行所用平台费用映射的最后更新时间。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_platform_expense_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_douyin_platform_expense_primary_date
    ON dws.dws_douyin_platform_expense_shop_daily_category (
        primary_category_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dws_douyin_platform_expense_secondary_date
    ON dws.dws_douyin_platform_expense_shop_daily_category (
        secondary_category_code, stat_date
    );
