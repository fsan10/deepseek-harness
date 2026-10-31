CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_ks_platform_expense_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
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
        shop_code,
        source_document_type,
        secondary_category_code
    )
);

COMMENT ON TABLE dws.dws_ks_platform_expense_shop_daily_category IS '快手平台费用店铺日分类DWS；通过独立平台费用映射表纳入费用，一级分类由财务维护，二级分类保留平台原始业务类型和描述。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.stat_date IS '费用统计日期；结算费用取实际结算日期，资金费用取入账日期。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.primary_category_code IS '财务人工维护的一级费用分类编码。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.primary_category_name IS '财务人工维护的一级费用分类名称。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.secondary_category_code IS '平台原始二级分类稳定编码；资金描述含业务单号时附加原文哈希以保持唯一。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.secondary_category_name IS '结算原始费用字段名，或快手原始“业务类型 + 描述”，不改写平台文案。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.source_document_type IS '费用来源单据类型；settlement或fund。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.expense_amount IS '店铺日原始二级分类净费用；正常费用为正、返还为负，单位元。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.included_detail_count IS '金额非零且映射为计入费用的来源明细数。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.source_detail_count IS '参与本行汇总的全部来源明细数。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.source_updated_at IS '参与汇总的DWD来源记录最晚时间。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.mapping_updated_at IS '本行费用映射最后更新时间。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_platform_expense_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_platform_expense_primary_date
    ON dws.dws_ks_platform_expense_shop_daily_category (
        primary_category_code, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dws_ks_platform_expense_secondary_date
    ON dws.dws_ks_platform_expense_shop_daily_category (
        secondary_category_code, stat_date
    );
