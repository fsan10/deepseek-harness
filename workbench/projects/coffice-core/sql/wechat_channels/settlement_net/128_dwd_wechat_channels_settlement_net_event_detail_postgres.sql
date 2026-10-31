CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_wechat_channels_settlement_net_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'wechat_channels',
    platform_name VARCHAR(64) NOT NULL DEFAULT '视频号',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    occurred_at TIMESTAMP NOT NULL,
    flow_no VARCHAR(128) NOT NULL,
    movement_type VARCHAR(128) NOT NULL,
    income_expense_direction VARCHAR(64) NOT NULL,
    source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    account_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    related_order_no VARCHAR(128),
    related_after_sale_no VARCHAR(128),
    related_withdrawal_no VARCHAR(128),
    related_policy_no VARCHAR(128),
    related_gift_no VARCHAR(128),
    detail_text TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_wechat_channels_settlement_net_event_detail IS '视频号结算净额动账事件明细表，净额由收入减支出计算，源方向还原金额用于核验。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_id IS '对应视频号结算ODS自增主键，作为稳定动账事件粒度。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.platform_code IS '平台编码，视频号固定为wechat_channels。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.platform_name IS '平台名称，固定为视频号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.stat_date IS '结算净额统计日期，取源记账时间日期，无兜底。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.occurred_at IS '清洗后的源记账时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.flow_no IS '源流水单号，当前ODS内唯一。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.movement_type IS '源动帐类型，全部类型均纳入净额。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.income_expense_direction IS '源收支类型，枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_amount IS '源收支金额，源值均为正数，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.income_amount IS '收入金额，收入方向取源金额，其他方向为0，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.expense_amount IS '支出金额，支出方向取源金额，其他方向为0，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.settlement_net_amount IS '计算结算净额，等于收入金额减支出金额，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_settlement_amount IS '按源收支方向还原的带符号流水金额，仅用于核验，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.validation_difference_amount IS '计算净额减源带符号流水金额的核验差额，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.account_balance IS '源账户余额，仅用于流水核对，不参与指标求和，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.related_order_no IS '源关联订单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.related_after_sale_no IS '源关联售后单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.related_withdrawal_no IS '源关联提现单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.related_policy_no IS '源关联保单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.related_gift_no IS '源关联礼物单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.detail_text IS '源详情文本，用于动账追溯。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_settlement_net_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_settlement_net_shop_date
    ON dwd.dwd_wechat_channels_settlement_net_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_settlement_net_flow
    ON dwd.dwd_wechat_channels_settlement_net_event_detail (flow_no);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_settlement_net_type
    ON dwd.dwd_wechat_channels_settlement_net_event_detail (movement_type, stat_date);

