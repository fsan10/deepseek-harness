CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_main_business_income_source_detail (
    source_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    settlement_type VARCHAR(128),
    has_pre_settlement_refund VARCHAR(64),
    business_type VARCHAR(128),
    order_type VARCHAR(128),
    user_payment_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    government_platform_advance_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    talent_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    douyin_pay_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    douyin_monthly_pay_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    bank_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    trade_in_deduction_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_shipping_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    component_income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    reconciliation_difference NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_douyin_main_business_income_source_detail IS '抖音主营业务收入来源DWD；逐条保留结算ODS并清洗十项收入组成，本层不筛选结算类型或退款状态。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_id IS '来源ods.ods_douyin_settlement_raw自增主键，作为结算事件唯一键。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.stat_date IS '主营业务收入归属日，严格取源结算时间日期。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.event_at IS '清洗后的源结算时间。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.order_no IS '平台订单号，清理引号和首尾空白。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.sub_order_no IS '平台子订单号，清理引号和首尾空白。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.settlement_type IS '平台原始结算单类型，用于DWS识别结算后退款。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.has_pre_settlement_refund IS '平台原始有结算前退款标识，仅保留审计；收入组成已经是退款后的净值。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.business_type IS '平台原始业务类型。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.order_type IS '平台原始订单类型。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.user_payment_amount IS '源用户实付带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.platform_subsidy_amount IS '源平台补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.other_platform_subsidy_amount IS '源其他平台补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.government_platform_advance_amount IS '源政府补贴平台垫资带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.talent_subsidy_amount IS '源达人补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.douyin_pay_subsidy_amount IS '源抖音支付补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.douyin_monthly_pay_subsidy_amount IS '源抖音月付营销补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.bank_subsidy_amount IS '源银行补贴带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.trade_in_deduction_amount IS '源以旧换新抵扣带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.platform_shipping_subsidy_amount IS '源平台补贴运费带符号金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_income_amount IS '源收入合计带符号金额，已包含结算前及结算后退款冲销，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.component_income_amount IS '十项收入组成重新汇总金额，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.reconciliation_difference IS '源收入合计减十项组成金额，验收应为0，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_main_business_income_shop_date
    ON dwd.dwd_douyin_main_business_income_source_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_main_business_income_settlement_type
    ON dwd.dwd_douyin_main_business_income_source_detail (
        settlement_type, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_main_business_income_order
    ON dwd.dwd_douyin_main_business_income_source_detail (
        order_no, sub_order_no
    );
