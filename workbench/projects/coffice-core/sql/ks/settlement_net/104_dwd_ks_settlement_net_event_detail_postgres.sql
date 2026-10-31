CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_settlement_net_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'ks',
    platform_name VARCHAR(64) NOT NULL DEFAULT '快手',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    settlement_at TIMESTAMP NOT NULL,
    merchant_id VARCHAR(128),
    order_no VARCHAR(128) NOT NULL,
    product_id VARCHAR(128),
    commission_mode VARCHAR(128),
    settlement_rule TEXT,
    fund_channel VARCHAR(128),
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_ks_settlement_net_event_detail IS '快手结算净额事件明细表，净额由收入减支出计算，源实际结算金额只用于核验。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_id IS '对应快手结算ODS自增主键，作为稳定结算事件粒度。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.platform_code IS '平台编码，快手固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.platform_name IS '平台名称，快手固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.stat_date IS '结算净额统计日期，取实际结算时间日期，无兜底。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.settlement_at IS '清洗后的源实际结算时间。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.merchant_id IS '源商家ID，仅用于与批次标准店铺编码核对。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.order_no IS '源订单号，当前数据一单一条，但以source_id作为稳定主键。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.product_id IS '源商品ID，用于结算明细追溯。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.commission_mode IS '源佣金模式枚举，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.settlement_rule IS '源结算规则文本，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.fund_channel IS '源资金渠道枚举。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.income_amount IS '收入金额，取源合计收入(元)，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.expense_amount IS '支出金额，取源合计支出(元)，正常支出为正，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.settlement_net_amount IS '计算结算净额，等于收入金额减支出金额，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_settlement_amount IS '源实际结算金额，只用于核验，不作为结算净额指标取值。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.validation_difference_amount IS '计算结算净额减源实际结算金额的核验差额；非零表示源数据不满足公式，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_settlement_net_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_settlement_net_shop_date
    ON dwd.dwd_ks_settlement_net_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_ks_settlement_net_order
    ON dwd.dwd_ks_settlement_net_event_detail (order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_ks_settlement_net_validation
    ON dwd.dwd_ks_settlement_net_event_detail (validation_difference_amount)
    WHERE validation_difference_amount <> 0;

