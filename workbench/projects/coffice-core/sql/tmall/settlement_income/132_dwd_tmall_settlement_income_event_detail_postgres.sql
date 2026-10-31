CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_tmall_settlement_income_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    bill_period_raw VARCHAR(64) NOT NULL,
    bill_category VARCHAR(128) NOT NULL,
    business_category VARCHAR(128) NOT NULL,
    business_subcategory VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    business_flow_no VARCHAR(128),
    merchant_order_no VARCHAR(128),
    payment_channel VARCHAR(128),
    paid_at TIMESTAMP,
    paid_updated_at TIMESTAMP,
    order_actual_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_tmall_settlement_income_event_detail IS '天猫结算收入事件明细表，一条收入ODS记录一行；仅清洗账期、金额和批次店铺，不扣减退款。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.source_id IS '对应天猫结算收入ODS自增主键，作为稳定事件粒度。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.platform_code IS '平台编码，天猫固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.platform_name IS '平台名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.stat_date IS '收入统计日期，将源账期YYYYMMDD解析为DATE，无其他兜底。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.bill_period_raw IS '源账期原值，用于统计日期追溯。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.bill_category IS '源账单大类，作为收入类型来源，当前为货款收入。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.business_category IS '源业务大类，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.business_subcategory IS '源业务小类，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.order_no IS '源订单号；同一订单可有多条收入明细，不用于去重。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.sub_order_no IS '源子订单号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.business_flow_no IS '源业务流水号；同一流水可对应多个商品明细。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.merchant_order_no IS '源商户订单号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.payment_channel IS '源收/付渠道。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.paid_at IS '清洗后的源打款时间，仅用于核对，不作为统计日期。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.paid_updated_at IS '清洗后的源打款更新时间，仅用于核对。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.order_actual_amount IS '清洗后的订单实际金额，用户确认直接作为收入且不减退款，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.refund_amount IS '清洗后的源退款金额，仅保留审计，不从收入金额扣减，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_income_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_income_shop_date
    ON dwd.dwd_tmall_settlement_income_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_income_order
    ON dwd.dwd_tmall_settlement_income_event_detail (order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_income_type
    ON dwd.dwd_tmall_settlement_income_event_detail (bill_category, stat_date);

