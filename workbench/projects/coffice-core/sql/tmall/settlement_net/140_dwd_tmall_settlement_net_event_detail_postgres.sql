CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_tmall_settlement_net_event_detail (
    source_event_key VARCHAR(128) NOT NULL PRIMARY KEY,
    source_table VARCHAR(128) NOT NULL,
    source_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    bill_period_raw VARCHAR(64) NOT NULL,
    event_direction VARCHAR(32) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_table, source_id)
);

COMMENT ON TABLE dwd.dwd_tmall_settlement_net_event_detail IS '天猫结算净额事件明细表，收入与支出两张ODS分别按方向合并；净额始终由收入减支出计算。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_event_key IS '跨收入、支出ODS的稳定事件键，格式为income:id或expense:id。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_table IS '来源ODS表名，用于区分收入表和支出表。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_id IS '来源ODS自增主键；与source_table共同唯一。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.platform_code IS '平台编码，天猫固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.platform_name IS '平台名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.stat_date IS '结算净额统计日期，收入和支出均取源账期。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.bill_period_raw IS '源账期原值。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.event_direction IS '事件方向，枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.event_type IS '收入取源账单大类，支出取源支出项目。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.order_no IS '源订单或交易主订单号，仅用于追溯。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_amount IS '源方向对应金额；收入为订单实际金额，支出为标准化净扣费金额，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.income_amount IS '收入事件取订单实际金额且不减退款，支出事件为0，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.expense_amount IS '支出事件取标准化净扣费金额并保留冲回负号，收入事件为0，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.settlement_net_amount IS '计算结算净额，等于收入金额减支出金额，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_settlement_amount IS '按两张源表方向还原的带符号组成金额，不是独立源结算金额，仅用于公式核对，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.validation_difference_amount IS '计算净额减源方向组成金额的差额，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_net_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_net_shop_date
    ON dwd.dwd_tmall_settlement_net_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_net_type
    ON dwd.dwd_tmall_settlement_net_event_detail (event_direction, event_type, stat_date);

