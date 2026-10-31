CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_settlement_income_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    settled_at TIMESTAMP NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    after_sale_no VARCHAR(128),
    transaction_type VARCHAR(128) NOT NULL,
    settlement_account VARCHAR(128) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    commission_base_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    product_paid_refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    freight_paid_refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    government_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    buyer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    installment_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    component_check_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    component_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_xhs_settlement_income_event_detail IS '小红书结算收入事件明细表；订单结算ODS逐行保留，其他服务款中的申诉调账作为平台补偿收入逐行纳入，所有收入事件保留源金额符号。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_id IS '订单结算来源使用订单结算ODS自增主键；申诉调账收入使用对应其他服务款ODS主键的负值，避免跨源主键冲突。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.platform_code IS '平台编码，小红书固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.platform_name IS '平台名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.stat_date IS '收入统计日期，取源结算时间的日期部分，无其他兜底。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.settled_at IS '清洗后的源结算时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.order_no IS '订单结算使用源订单号；申诉调账使用源业务单号，缺失时使用稳定的申诉调账事件标识；不按订单去重。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.after_sale_no IS '源售后单号；横杠或空值清洗为NULL。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.transaction_type IS '收入业务类型；订单结算取源交易类型，申诉调账收入固定为申诉调账。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.settlement_account IS '源结算账户，当前为店铺余额。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.income_amount IS '源动账金额直接作为收入；结算入账、平台补偿通常为正，退款或补偿冲回保留负号，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.commission_base_amount IS '源计佣基数，单位元，仅用于审计。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.product_paid_refund_amount IS '源商品实付/实退，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.freight_paid_refund_amount IS '源运费实付/实退，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.merchant_discount_amount IS '源商家优惠总额，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.platform_subsidy_amount IS '源平台优惠补贴，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.government_subsidy_amount IS '源政府券优惠补贴，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.platform_commission_amount IS '源平台佣金，收入时通常为负、退款时通常为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.buyer_commission_amount IS '源买手佣金，收入时通常为负、退款时可能为正，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.installment_fee_amount IS '源花呗分期手续费，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.component_check_amount IS '订单结算为除计佣基数外的源组成金额带符号合计；申诉调账收入无订单组成，直接等于源动账金额；仅用于核对，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.component_difference_amount IS '动账金额减组成金额；订单结算按分项重算，申诉调账收入直接取源金额，因此差额为0，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_sheet_name IS '来源工作表，为订单结算或其他服务款。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_income_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_income_shop_date
    ON dwd.dwd_xhs_settlement_income_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_income_order
    ON dwd.dwd_xhs_settlement_income_event_detail (order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_income_type
    ON dwd.dwd_xhs_settlement_income_event_detail (transaction_type, stat_date);
