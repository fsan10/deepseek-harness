CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_settlement_income_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    settlement_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    settlement_type VARCHAR(128),
    has_pre_settlement_refund VARCHAR(64),
    business_type VARCHAR(128),
    order_type VARCHAR(128),
    source_company_name VARCHAR(255),
    user_payment_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    government_platform_advance_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    creator_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    douyin_pay_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    douyin_monthly_pay_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    bank_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    trade_in_deduction_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_shipping_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_douyin_settlement_income_event_detail IS '抖音结算收入事件明细表，一条ODS结算事件一行，只清洗字段与金额，不筛选结算、退款或业务类型。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_id IS '对应ODS结算原始表自增主键，作为结算事件稳定粒度。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.platform_code IS '平台编码，抖音固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.platform_name IS '平台名称，抖音固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.shop_identity_key IS '稳定店铺身份键，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.stat_date IS '收入统计日期，取源字段结算时间的日期部分，无兜底日期。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.settlement_at IS '清洗后的结算时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.order_no IS '源结算单订单号，去除Excel文本前缀单引号。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.sub_order_no IS '源结算单子订单号，去除Excel文本前缀单引号。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.settlement_type IS '源结算单类型，保留已结算、结算后退款和保证金退回等枚举，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.has_pre_settlement_refund IS '源字段有结算前退款，保留原枚举，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.business_type IS '源业务类型，如巨量千川、小店自卖或精选联盟。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.order_type IS '源订单类型枚举。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_company_name IS '源文件商户主体原始值，仅作审计展示；公司归属以当前DIM店铺映射为准。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.user_payment_amount IS '用户实付收入，源字段用户实付，保留退款负号，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.platform_subsidy_amount IS '平台补贴收入，源字段平台补贴，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.other_platform_subsidy_amount IS '其他平台补贴收入，源字段其他平台补贴，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.government_platform_advance_amount IS '政府补贴平台垫资收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.creator_subsidy_amount IS '达人补贴收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.douyin_pay_subsidy_amount IS '抖音支付补贴收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.douyin_monthly_pay_subsidy_amount IS '抖音月付营销补贴收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.bank_subsidy_amount IS '银行补贴收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.trade_in_deduction_amount IS '以旧换新抵扣收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.platform_shipping_subsidy_amount IS '平台补贴运费收入，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.income_amount IS '收入金额，源字段收入合计，组成字段重算必须与其相等，退款为负，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_income_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_settlement_income_shop_date
    ON dwd.dwd_douyin_settlement_income_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_settlement_income_type
    ON dwd.dwd_douyin_settlement_income_event_detail (settlement_type, stat_date);
