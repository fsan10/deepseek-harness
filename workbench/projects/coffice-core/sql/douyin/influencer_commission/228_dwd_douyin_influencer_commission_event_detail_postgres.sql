CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_influencer_commission_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    movement_at TIMESTAMP NOT NULL,
    flow_no VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    influencer_id VARCHAR(128),
    influencer_name VARCHAR(255),
    movement_direction VARCHAR(64),
    movement_account VARCHAR(128),
    movement_scenario VARCHAR(255),
    billing_type VARCHAR(128),
    order_type VARCHAR(128),
    source_company_name VARCHAR(255),
    creator_commission_source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    recruitment_service_fee_source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    creator_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    recruitment_service_fee_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'settlement_at'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'movement_at'
    ) THEN
        ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
            RENAME COLUMN settlement_at TO movement_at;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'settlement_type'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'movement_direction'
    ) THEN
        ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
            RENAME COLUMN settlement_type TO movement_direction;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'has_pre_settlement_refund'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'movement_account'
    ) THEN
        ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
            RENAME COLUMN has_pre_settlement_refund TO movement_account;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'business_type'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'dwd'
          AND table_name = 'dwd_douyin_influencer_commission_event_detail'
          AND column_name = 'movement_scenario'
    ) THEN
        ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
            RENAME COLUMN business_type TO movement_scenario;
    END IF;
END
$$;

ALTER TABLE dwd.dwd_douyin_influencer_commission_event_detail
    ADD COLUMN IF NOT EXISTS flow_no VARCHAR(128),
    ADD COLUMN IF NOT EXISTS billing_type VARCHAR(128);

COMMENT ON TABLE dwd.dwd_douyin_influencer_commission_event_detail IS '抖音达人佣金资金事件DWD；每个店铺动账流水保留最新导入版本，佣金与招商服务费均来自资金单。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_id IS '来源ods.ods_douyin_fund_raw.id，作为所选最新资金事件主键。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.shop_code IS '通过batch_id关联公共批次店铺上下文取得的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.shop_name IS '通过批次店铺上下文取得的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.shop_identity_key IS '平台与标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.shop_mapping_source IS '标准店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.stat_date IS '指标统计日期，严格取源资金动账时间的日期部分，无兜底。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.movement_at IS '清洗后的源资金动账时间。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.flow_no IS '源资金动账流水号；同一店铺重复导出时按此业务键选择最新批次。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.order_no IS '源订单号，去除Excel文本单引号前缀。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.sub_order_no IS '源子订单号，去除Excel文本单引号前缀。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.influencer_id IS '源达人ID，仅用于资金追溯，不进入共享ADS维度。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.influencer_name IS '源达人名称，仅用于资金追溯。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.movement_direction IS '源资金动账方向，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.movement_account IS '源资金动账账户，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.movement_scenario IS '源资金动账场景，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.billing_type IS '源资金计费类型，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.order_type IS '源订单类型，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_company_name IS '源文件商户主体原始值，仅作审计展示；公司归属以当前DIM店铺映射为准。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.creator_commission_source_amount IS '资金单源佣金带符号金额；正常支出为负、退款冲回为正，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.recruitment_service_fee_source_amount IS '源招商服务费带符号金额；正常支出为负、退款冲回为正，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.creator_commission_amount IS '标准化达人佣金，源金额取反后正常费用为正、冲回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.recruitment_service_fee_amount IS '标准化招商服务费，源金额取反后正常费用为正、冲回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_commission_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_commission_shop_date
    ON dwd.dwd_douyin_influencer_commission_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_commission_order
    ON dwd.dwd_douyin_influencer_commission_event_detail (order_no, sub_order_no);

CREATE UNIQUE INDEX IF NOT EXISTS uk_dwd_douyin_influencer_commission_shop_flow
    ON dwd.dwd_douyin_influencer_commission_event_detail (shop_identity_key, flow_no);
