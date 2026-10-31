CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_settlement_net_event_detail (
    source_event_key VARCHAR(128) NOT NULL PRIMARY KEY,
    source_table VARCHAR(128) NOT NULL,
    source_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    settled_at TIMESTAMP NOT NULL,
    event_direction VARCHAR(32) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    source_movement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_settlement_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_sheet_name VARCHAR(128) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_table, source_id)
);

COMMENT ON TABLE dwd.dwd_xhs_settlement_net_event_detail IS '小红书结算净额事件明细表；订单结算与其他服务款按收入型申诉调账、费用类其他服务款分流，净额由收入减支出计算。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_event_key IS '跨两张ODS的稳定事件键，格式为income:id、expense_income:id或expense:id。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_table IS '来源ODS表名，用于区分订单结算和其他服务款。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_id IS '来源ODS自增主键，与source_table共同唯一。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.platform_code IS '平台编码，小红书固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.platform_name IS '平台名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.stat_date IS '结算净额统计日期，两张源表均取结算时间日期。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.settled_at IS '清洗后的源结算时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.event_direction IS '源表归属方向，枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.event_type IS '收入取交易类型或收入型申诉调账业务款项，支出取费用类业务款项。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.order_no IS '订单结算使用源订单号；申诉调账收入使用业务单号或稳定事件标识。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_movement_amount IS '源带符号动账金额；订单结算和其他服务款均可包含正向入账与负向扣款，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.income_amount IS '订单结算及申诉调账收入事件直接取源动账金额，含退款或收入冲回负数；费用事件为0，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.expense_amount IS '费用类其他服务款源动账金额取反；负向扣款形成正费用，正向费用退款或补回形成负费用冲减；申诉调账收入事件为0，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.settlement_net_amount IS '计算结算净额，等于收入金额减支出金额，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_settlement_amount IS '两张源表原始动账金额带符号合计组成项，用于核验总览净收益，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.validation_difference_amount IS '计算净额减源带符号动账金额的差额，单位元。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_sheet_name IS '来源工作表，订单结算或其他服务款。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_settlement_net_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_net_shop_date
    ON dwd.dwd_xhs_settlement_net_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_settlement_net_type
    ON dwd.dwd_xhs_settlement_net_event_detail (event_direction, event_type, stat_date);
