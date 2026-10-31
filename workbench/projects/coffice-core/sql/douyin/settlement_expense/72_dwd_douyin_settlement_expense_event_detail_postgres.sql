CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_settlement_expense_event_detail (
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
    platform_service_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    creator_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    service_provider_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    channel_share_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_recruitment_service_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    offsite_promotion_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_share_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_douyin_settlement_expense_event_detail IS '抖音结算支出事件明细表，一条ODS结算事件一行，正常支出统一为正、退款冲回为负，不执行任何结算或退款筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_id IS '对应ODS原始结算事件主键。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.platform_code IS '平台编码，抖音固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.platform_name IS '平台名称，抖音固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.shop_mapping_source IS '店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.stat_date IS '支出统计日期，取结算时间日期，无兜底。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.settlement_at IS '清洗后的结算时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.order_no IS '源订单号，已去除Excel单引号前缀。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.sub_order_no IS '源子订单号，已去除Excel单引号前缀。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.settlement_type IS '源结算单类型，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.has_pre_settlement_refund IS '源字段有结算前退款，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.business_type IS '源业务类型。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.order_type IS '源订单类型。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_company_name IS '源文件商户主体原始值，仅作审计展示；公司归属以当前DIM店铺映射为准。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.platform_service_fee_amount IS '平台服务费净支出，为源字段平台服务费取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.creator_commission_amount IS '达人佣金净支出，为源字段达人佣金取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.service_provider_commission_amount IS '服务商佣金净支出，为源字段取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.channel_share_amount IS '渠道分成净支出，为源字段取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.merchant_recruitment_service_fee_amount IS '招商服务费净支出，为源字段取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.offsite_promotion_fee_amount IS '站外推广费净支出，为源字段取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.other_share_amount IS '其他分成净支出，为源字段取反，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.expense_amount IS '支出金额，为源字段支出合计取反；正常支出为正，退款冲回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.source_updated_at IS '来源ODS入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_settlement_expense_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_settlement_expense_shop_date
    ON dwd.dwd_douyin_settlement_expense_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_settlement_expense_type
    ON dwd.dwd_douyin_settlement_expense_event_detail (settlement_type, stat_date);
