CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_wechat_channels_main_business_income_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'wechat_channels',
    platform_name VARCHAR(64) NOT NULL DEFAULT '视频号',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    flow_no VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    after_sale_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    source_direction VARCHAR(32) NOT NULL,
    source_description TEXT,
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

COMMENT ON TABLE dwd.dwd_wechat_channels_main_business_income_source_detail IS '视频号主营业务收入候选DWD；一行一条动账流水，本层还原收支符号，不执行收入退款筛选。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_id IS '来源ods.ods_wechat_channels_settlement_raw.id。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.platform_code IS '标准平台编码，固定为wechat_channels。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.platform_name IS '平台展示名称，固定为视频号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.shop_code IS '标准店铺编码，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.shop_name IS '标准店铺名称，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.stat_date IS '收入归属日，取记账时间日期。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.event_at IS '源记账时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.flow_no IS '平台流水单号，当前全量唯一。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.order_no IS '关联订单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.after_sale_no IS '关联售后单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_business_type IS '平台原始动帐类型。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_direction IS '平台原始收支类型，收入或支出。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_description IS '平台详情原文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.secondary_category_name IS '收入或费用二级分类，使用平台原始动帐类型。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.signed_amount IS '还原后的带符号动账金额；收入为正、支出为负，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_batch_id IS '来源ODS批次ID。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_wechat_main_income_shop_date
    ON dwd.dwd_wechat_channels_main_business_income_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_main_income_type_date
    ON dwd.dwd_wechat_channels_main_business_income_source_detail (source_business_type, stat_date);

CREATE TABLE IF NOT EXISTS dwd.dwd_wechat_channels_platform_expense_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'wechat_channels',
    platform_name VARCHAR(64) NOT NULL DEFAULT '视频号',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    flow_no VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    after_sale_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    source_direction VARCHAR(32) NOT NULL,
    source_description TEXT,
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

COMMENT ON TABLE dwd.dwd_wechat_channels_platform_expense_source_detail IS '视频号平台费用候选DWD；一行一条动账流水，支出为正费用、收入冲回为负费用，本层不执行映射筛选。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_id IS '来源视频号结算ODS主键。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.stat_date IS '费用业务归属日，取记账时间日期。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.event_at IS '源记账时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.flow_no IS '平台流水单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.order_no IS '关联订单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.after_sale_no IS '关联售后单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_business_type IS '平台原始动帐类型。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_direction IS '平台原始收支类型。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_description IS '平台详情原文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.secondary_category_name IS '平台原始动帐类型，作为费用二级分类。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.signed_amount IS '带符号动账金额，收入为正、支出为负，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.directional_expense_amount IS '费用方向金额，支出为正、收入冲回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_batch_id IS '来源ODS批次ID。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_platform_expense_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_wechat_platform_expense_shop_date
    ON dwd.dwd_wechat_channels_platform_expense_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_platform_expense_type_date
    ON dwd.dwd_wechat_channels_platform_expense_source_detail (source_business_type, stat_date);
