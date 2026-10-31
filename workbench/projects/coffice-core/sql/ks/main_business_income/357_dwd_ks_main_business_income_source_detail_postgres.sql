CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_main_business_income_source_detail (
    source_document_type VARCHAR(32) NOT NULL,
    source_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'ks',
    platform_name VARCHAR(64) NOT NULL DEFAULT '快手',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    source_direction VARCHAR(32) NOT NULL,
    source_business_type VARCHAR(128),
    source_description TEXT,
    flow_no VARCHAR(128),
    order_no VARCHAR(128),
    related_order_no VARCHAR(128),
    order_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    government_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    payment_marketing_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    talent_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    order_refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_formula_income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    signed_fund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_document_type, source_id),
    CONSTRAINT ck_dwd_ks_main_business_income_source_type
        CHECK (source_document_type IN ('settlement', 'fund'))
);

COMMENT ON TABLE dwd.dwd_ks_main_business_income_source_detail IS '快手主营业务收入来源DWD；逐条保留结算单和资金单，清洗结算收入组成及资金方向，本层不筛选退款场景或执行跨表去重。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_document_type IS '来源单据类型；settlement为结算单，fund为资金单。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_id IS '来源ODS自增主键，与来源单据类型共同构成唯一键。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.stat_date IS '主营业务收入归属日；结算取实际结算时间，资金取入账时间。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.event_at IS '清洗后的实际结算时间或资金入账时间。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_direction IS '源金额方向；结算固定为结算，资金原样保留收或支。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_business_type IS '资金单原始业务类型；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_description IS '资金单原始描述；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.flow_no IS '资金账务流水号；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.order_no IS '结算单订单号；资金来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.related_order_no IS '资金关联业务单号，作为对应订单号用于结算退款跨表查重。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.order_paid_amount IS '源订单实付金额，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.government_subsidy_amount IS '源政府补贴金额，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.payment_marketing_subsidy_amount IS '源支付营销补贴金额，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.platform_subsidy_amount IS '源平台补贴金额，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.talent_subsidy_amount IS '源达人补贴金额，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.merchant_subsidy_amount IS '源商家补贴金额，DWS按收入冲减处理，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.order_refund_amount IS '源订单退款金额，DWS按收入冲减处理，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_income_amount IS '源合计收入金额，平台未扣订单退款，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.settlement_formula_income_amount IS '按订单实付及补贴减商家补贴和订单退款重算的结算主营业务收入，单位元；资金来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.signed_fund_amount IS '资金带符号发生额，收为正、支为负，单位元；结算来源为0。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_main_business_income_shop_date
    ON dwd.dwd_ks_main_business_income_source_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_ks_main_business_income_order
    ON dwd.dwd_ks_main_business_income_source_detail (
        order_no, related_order_no
    );

CREATE INDEX IF NOT EXISTS idx_dwd_ks_main_business_income_fund_scene
    ON dwd.dwd_ks_main_business_income_source_detail (
        source_document_type, source_business_type, stat_date
    );
