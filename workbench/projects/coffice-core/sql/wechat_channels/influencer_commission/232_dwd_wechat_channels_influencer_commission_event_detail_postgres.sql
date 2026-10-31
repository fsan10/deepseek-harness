CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_wechat_channels_influencer_commission_event_detail (
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
    directional_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    account_balance NUMERIC(18,2) NOT NULL DEFAULT 0,
    related_order_no VARCHAR(128),
    related_after_sale_no VARCHAR(128),
    related_withdrawal_no VARCHAR(128),
    detail_text TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_wechat_channels_influencer_commission_event_detail IS '视频号达人佣金动账事件DWD；一条ODS流水一行，全部动账类型和收支方向均保留。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_id IS '来源ods.ods_wechat_channels_settlement_raw.id。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.platform_code IS '标准平台编码，固定为wechat_channels。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.platform_name IS '平台展示名称，固定为视频号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.shop_code IS '通过batch_id关联公共批次店铺上下文取得的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.shop_name IS '通过批次店铺上下文取得的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.shop_identity_key IS '平台与标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.shop_mapping_source IS '标准店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.stat_date IS '指标统计日期，严格取源记账时间的日期部分，无兜底。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.occurred_at IS '清洗后的源记账时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.flow_no IS '源流水单号，当前ODS内唯一。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.movement_type IS '源动帐类型，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.income_expense_direction IS '源收支类型，当前枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_amount IS '源收支金额，源值为正数，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.directional_expense_amount IS '按费用口径标准化的带符号金额：支出为正、收入冲回为负，其他方向为0，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.account_balance IS '源账户余额，仅用于流水核对，单位元。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.related_order_no IS '源关联订单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.related_after_sale_no IS '源关联售后单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.related_withdrawal_no IS '源关联提现单号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.detail_text IS '源详情文本，用于流水追溯。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_influencer_commission_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_influencer_commission_shop_date
    ON dwd.dwd_wechat_channels_influencer_commission_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_influencer_commission_flow
    ON dwd.dwd_wechat_channels_influencer_commission_event_detail (flow_no);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_influencer_commission_type
    ON dwd.dwd_wechat_channels_influencer_commission_event_detail (movement_type, stat_date);

