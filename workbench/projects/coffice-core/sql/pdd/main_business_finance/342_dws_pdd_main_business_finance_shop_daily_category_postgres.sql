CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_pdd_main_business_income_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL DEFAULT 'settlement',
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, source_document_type, primary_category_code, secondary_category_code)
);

COMMENT ON TABLE dws.dws_pdd_main_business_income_shop_daily_category IS '拼多多主营业务收入店铺日分类DWS；订单及优惠券收入为正、对应退款为负。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.stat_date IS '主营业务收入归属日。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.primary_category_code IS '收入一级分类编码。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.primary_category_name IS '收入一级分类名称。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.secondary_category_code IS '稳定收入二级分类编码。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.secondary_category_name IS '账务类型加业务描述形成的收入二级分类。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.source_document_type IS '来源单据类型，固定为settlement。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.income_amount IS '收入净额，订单收入为正、退款为负，单位元。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.included_detail_count IS '纳入本行汇总的结算流水数。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.source_updated_at IS '参与汇总的来源最晚入库时间。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_main_business_income_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_pdd_main_income_primary_date
    ON dws.dws_pdd_main_business_income_shop_daily_category (primary_category_code, stat_date);

CREATE TABLE IF NOT EXISTS dws.dws_pdd_platform_expense_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL DEFAULT 'settlement',
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    mapping_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, source_document_type, secondary_category_code)
);

COMMENT ON TABLE dws.dws_pdd_platform_expense_shop_daily_category IS '拼多多平台费用店铺日分类DWS；仅汇总财务映射为计入费用的结算场景。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.stat_date IS '费用业务归属日。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.primary_category_code IS '财务人工维护的一级费用分类编码。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.primary_category_name IS '财务人工维护的一级费用分类名称。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.secondary_category_code IS '平台原始场景对应的稳定二级分类编码。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.secondary_category_name IS '账务类型加业务描述形成的二级分类。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.source_document_type IS '来源单据类型，固定为settlement。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.expense_amount IS '平台费用净额；扣费为正、补回为负，单位元。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.included_detail_count IS '金额非零且纳入费用的明细数。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.source_detail_count IS '参与本行汇总的来源明细数。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.source_updated_at IS '参与汇总的来源最晚入库时间。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.mapping_updated_at IS '费用映射最后更新时间。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_platform_expense_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_pdd_platform_expense_primary_date
    ON dws.dws_pdd_platform_expense_shop_daily_category (primary_category_code, stat_date);
