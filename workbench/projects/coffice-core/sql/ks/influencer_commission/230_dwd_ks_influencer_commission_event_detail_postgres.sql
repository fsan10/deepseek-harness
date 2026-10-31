CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_influencer_commission_event_detail (
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
    influencer_id VARCHAR(128),
    mcn_id VARCHAR(128),
    leader_id VARCHAR(128),
    commission_mode VARCHAR(128),
    settlement_rule TEXT,
    fund_channel VARCHAR(128),
    order_refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    talent_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    leader_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    other_fee_detail TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_ks_influencer_commission_event_detail IS '快手达人佣金结算事件DWD；一条ODS结算记录一行，退款记录、佣金模式、结算规则及零金额记录全部保留。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.source_id IS '来源ods.ods_ks_settlement_raw.id，作为稳定结算事件主键。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.shop_code IS '通过batch_id关联公共批次店铺上下文取得的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.shop_name IS '通过批次店铺上下文取得的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.shop_identity_key IS '平台与标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.shop_mapping_source IS '标准店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.stat_date IS '指标统计日期，严格取源实际结算时间的日期部分，无兜底。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.settlement_at IS '清洗后的源实际结算时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.merchant_id IS '源商家ID，用于与批次标准店铺编码核对。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.order_no IS '源订单号，当前数据唯一。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.product_id IS '源商品ID，仅用于追溯。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.influencer_id IS '源达人ID，仅用于结算追溯。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.mcn_id IS '源MCN机构ID，仅用于结算追溯。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.leader_id IS '源团长ID，仅用于结算追溯。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.commission_mode IS '源佣金模式，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.settlement_rule IS '源结算规则，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.fund_channel IS '源资金渠道。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.order_refund_amount IS '源订单退款金额，单位元；仅用于退款口径审计，不从达人佣金中扣除。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.talent_commission_amount IS '源达人佣金费用，费用为正，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.leader_commission_amount IS '源团长佣金费用，费用为正，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.other_fee_amount IS '源其他收费，费用为正，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.other_fee_detail IS '源其他收费明细文本。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_commission_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_influencer_commission_shop_date
    ON dwd.dwd_ks_influencer_commission_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_ks_influencer_commission_order
    ON dwd.dwd_ks_influencer_commission_event_detail (order_no);

