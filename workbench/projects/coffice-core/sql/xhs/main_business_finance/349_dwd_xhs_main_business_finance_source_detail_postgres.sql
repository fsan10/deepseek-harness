CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_main_business_income_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    after_sale_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    source_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    buyer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    installment_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    restored_income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_row_hash CHAR(64) NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_xhs_main_business_income_source_detail IS '小红书主营业务收入DWD；订单结算事件以源动账净额加回佣金和手续费还原佣金前收入，申诉调账平台补偿按源金额作为带符号收入。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_id IS '订单结算来源使用ods.ods_xhs_settlement_income_raw.id；申诉调账收入使用对应其他服务款ODS主键的负值，避免跨源主键冲突。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.platform_code IS '标准平台编码，固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.platform_name IS '平台展示名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.shop_code IS '标准店铺编码，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.shop_name IS '标准店铺名称，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.stat_date IS '主营业务收入归属日，取结算时间日期。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.event_at IS '源结算时间。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.order_no IS '订单结算使用平台订单号；申诉调账收入使用业务单号或稳定事件标识。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.after_sale_no IS '平台售后单号，非退款记录通常为空。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_business_type IS '源收入业务类型，包括订单结算入账、退款和其他服务款中的申诉调账收入。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.secondary_category_name IS '收入二级分类；订单结算保留源交易类型，申诉调账收入保留申诉调账收入。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_net_amount IS '源动账金额；订单结算已扣除佣金和手续费，申诉调账为平台补偿收入源金额，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.platform_commission_amount IS '源平台佣金，正常扣费为负、退款返还为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.buyer_commission_amount IS '源买手佣金，正常扣费为负、退款返还为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.installment_fee_amount IS '源花呗分期手续费，正常扣费为负、退款返还为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.restored_income_amount IS '收入金额；订单结算为动账金额减佣金和分期手续费，申诉调账直接等于源金额，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_batch_id IS '来源ODS批次ID。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_main_income_shop_date
    ON dwd.dwd_xhs_main_business_income_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_main_income_type_date
    ON dwd.dwd_xhs_main_business_income_source_detail (source_business_type, stat_date);

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_platform_expense_source_detail (
    source_table VARCHAR(64) NOT NULL,
    source_id BIGINT NOT NULL,
    source_component_code VARCHAR(64) NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    source_business_type VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    directional_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_row_hash CHAR(64) NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_table, source_id, source_component_code)
);

COMMENT ON TABLE dwd.dwd_xhs_platform_expense_source_detail IS '小红书平台费用候选DWD；订单结算事件拆为三类费用组件，费用类其他服务款按业务款项保留，收入型申诉调账不进入费用候选。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_table IS '来源ODS表简称，income为订单结算、expense为其他服务款。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_id IS '来源ODS记录主键。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_component_code IS '来源费用组件编码。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.platform_code IS '标准平台编码，固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.platform_name IS '平台展示名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.shop_code IS '标准店铺编码，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.shop_name IS '标准店铺名称，来自批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.shop_identity_key IS '标准平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.stat_date IS '费用业务归属日，取结算时间日期。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.event_at IS '源结算时间。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.order_no IS '平台订单号。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_business_type IS '订单结算交易类型或其他服务款业务款项。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.secondary_category_name IS '平台原始费用字段名或业务款项，作为二级分类。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.signed_amount IS '源带符号费用组件，正常扣费为负、退款返还为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.directional_expense_amount IS '费用方向金额，正常扣费为正、退款返还为负，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_batch_id IS '来源ODS批次ID。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_row_hash IS '来源ODS行级SHA256。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_platform_expense_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_platform_expense_shop_date
    ON dwd.dwd_xhs_platform_expense_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_platform_expense_category_date
    ON dwd.dwd_xhs_platform_expense_source_detail (secondary_category_name, stat_date);
