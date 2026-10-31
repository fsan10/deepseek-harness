CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_pdd_settlement_income_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    merchant_order_no VARCHAR(128),
    account_type VARCHAR(128) NOT NULL,
    remark TEXT,
    business_description TEXT,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_signed_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE dwd.dwd_pdd_settlement_income_event_detail
    ADD COLUMN IF NOT EXISTS source_signed_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0;

COMMENT ON TABLE dwd.dwd_pdd_settlement_income_event_detail IS '拼多多结算收入账务事件明细表，一条ODS账务流水一行，全部账务类型纳入且本层不筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_id IS '对应拼多多结算ODS自增主键，作为稳定账务事件粒度。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.platform_code IS '平台编码，拼多多固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.platform_name IS '平台名称，拼多多固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.stat_date IS '收入统计日期，取源发生时间的日期部分，无兜底。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.occurred_at IS '清洗后的源发生时间。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.merchant_order_no IS '源商户订单号；提现、转账等非订单流水允许为空。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.account_type IS '源账务类型，如交易收入、优惠券结算、技术服务费、提现或转账，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.remark IS '源备注文本，用于账务追溯。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.business_description IS '源业务描述，包含业务编码及描述文本。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.income_amount IS '收入金额，取源收入金额（+元），保持非负，单位元。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_signed_expense_amount IS '原始支出金额（-元），保留负号，单位元；仅供结算收入DWS识别并冲减退款，本层保留全部流水且不执行归类。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_settlement_income_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_settlement_income_shop_date
    ON dwd.dwd_pdd_settlement_income_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_pdd_settlement_income_order
    ON dwd.dwd_pdd_settlement_income_event_detail (merchant_order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_pdd_settlement_income_type
    ON dwd.dwd_pdd_settlement_income_event_detail (account_type, stat_date);

