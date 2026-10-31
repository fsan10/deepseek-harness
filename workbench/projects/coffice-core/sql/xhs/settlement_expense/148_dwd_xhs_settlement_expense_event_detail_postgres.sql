CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_settlement_expense_event_detail (
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
    business_item VARCHAR(128) NOT NULL,
    business_no VARCHAR(128) NOT NULL,
    settlement_account VARCHAR(128) NOT NULL,
    source_movement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    remark TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_xhs_settlement_expense_event_detail IS '小红书其他服务款费用事件明细表；申诉调账收入不进入本表，其他服务款扣费为正费用，退款或费用补回为负费用冲减。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_id IS '对应小红书其他服务款ODS自增主键，作为稳定事件粒度。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.platform_code IS '平台编码，小红书固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.platform_name IS '平台名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.stat_date IS '支出统计日期，取源结算时间的日期部分，无其他兜底。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.settled_at IS '清洗后的源结算时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.order_no IS '源订单号，当前ODS内唯一。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.business_item IS '源业务款项，作为费用或费用冲减类型来源；申诉调账收入被收入链路单独处理，不进入本表。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.business_no IS '源业务单号，当前ODS内唯一。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.settlement_account IS '源结算账户，当前为店铺余额。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_movement_amount IS '费用类其他服务款源带符号动账金额，负数表示平台扣款，正数表示费用退款或补回，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.expense_amount IS '费用类标准化费用净额，等于源动账金额取反；扣费为正，费用退款或补回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.remark IS '源备注，用于业务款项追溯。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_sheet_name IS '来源工作表，当前为其他服务款。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_expense_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_expense_shop_date
    ON dwd.dwd_xhs_settlement_expense_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_expense_order
    ON dwd.dwd_xhs_settlement_expense_event_detail (order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_expense_type
    ON dwd.dwd_xhs_settlement_expense_event_detail (business_item, stat_date);
