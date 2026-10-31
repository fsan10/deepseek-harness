CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_pdd_main_business_income_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    source_description TEXT NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_row_hash CHAR(64) NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_pdd_main_business_income_source_detail IS '拼多多主营业务收入候选DWD；一行一条结算账务流水，本层只清洗日期、金额和来源字段，不执行收入退款筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_id IS '来源ods.ods_pdd_settlement_raw.id，作为稳定流水主键。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.platform_name IS '平台展示名称，固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.shop_code IS '通过batch_id关联批次上下文取得的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.shop_name IS '通过批次上下文取得的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.stat_date IS '收入业务归属日，取源发生时间日期。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.event_at IS '源账务流水发生时间。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.order_no IS '平台商户订单号；无订单号流水保留为空。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_business_type IS '源账务类型。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_description IS '源业务描述原文。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.secondary_category_name IS '二级分类，固定为账务类型加业务描述。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.signed_amount IS '带符号结算金额；收入为正、支出或退款为负，单位元。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_main_income_shop_date
    ON dwd.dwd_pdd_main_business_income_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_pdd_main_income_scene
    ON dwd.dwd_pdd_main_business_income_source_detail (secondary_category_name, stat_date);

CREATE TABLE IF NOT EXISTS dwd.dwd_pdd_platform_expense_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    source_description TEXT NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    directional_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_row_hash CHAR(64) NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_pdd_platform_expense_source_detail IS '拼多多平台费用候选DWD；一行一条结算账务流水，支出转为正费用、补回转为负费用，本层不执行映射筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_id IS '来源ods.ods_pdd_settlement_raw.id。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.platform_name IS '平台展示名称，固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.shop_code IS '标准店铺编码，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.shop_name IS '标准店铺名称，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.stat_date IS '费用业务归属日，取源发生时间日期。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.event_at IS '源账务流水发生时间。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.order_no IS '平台商户订单号。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_business_type IS '源账务类型。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_description IS '源业务描述原文。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.secondary_category_name IS '二级分类，固定为账务类型加业务描述。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.signed_amount IS '带符号结算金额，收入为正、支出为负，单位元。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.directional_expense_amount IS '费用方向金额，支出为正、补回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_platform_expense_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_platform_expense_shop_date
    ON dwd.dwd_pdd_platform_expense_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_pdd_platform_expense_scene
    ON dwd.dwd_pdd_platform_expense_source_detail (secondary_category_name, stat_date);
