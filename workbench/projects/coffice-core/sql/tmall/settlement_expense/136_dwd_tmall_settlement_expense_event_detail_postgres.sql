CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_tmall_settlement_expense_event_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    bill_period_raw VARCHAR(64) NOT NULL,
    funds_direction VARCHAR(128) NOT NULL,
    bill_category VARCHAR(128) NOT NULL,
    business_category VARCHAR(128) NOT NULL,
    business_subcategory VARCHAR(128) NOT NULL,
    expense_item VARCHAR(128) NOT NULL,
    charged_at TIMESTAMP,
    ordered_at TIMESTAMP,
    confirmed_at TIMESTAMP,
    main_order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    charge_transaction_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    gross_charge_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount_source VARCHAR(64) NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_tmall_settlement_expense_event_detail IS '天猫结算支出事件明细表，一条支出ODS记录一行；兼容八类服务费文件的字段超集并保留退款冲回负号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.source_id IS '对应天猫结算支出ODS自增主键，作为稳定事件粒度。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.platform_code IS '平台编码，天猫固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.platform_name IS '平台名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.stat_date IS '支出统计日期，将源账期YYYYMMDD解析为DATE，无其他兜底。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.bill_period_raw IS '源账期原值，用于统计日期追溯。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.funds_direction IS '源资金方向，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.bill_category IS '源账单大类，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.business_category IS '源业务大类，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.business_subcategory IS '源业务小类，本层保留且不筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.expense_item IS '源支出项目，作为支出类型来源。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.charged_at IS '清洗后的源扣费日期；部分基础软件服务费为空，仅用于核对。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.ordered_at IS '清洗后的源订单日期，仅用于核对。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.confirmed_at IS '清洗后的源确认收货日期，仅用于核对。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.main_order_no IS '源交易主订单号，兼容交易主单号字段。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.sub_order_no IS '源交易子订单号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.charge_transaction_amount IS '源扣费交易金额或扣款交易金额，单位元，仅用于核对扣费基数。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.gross_charge_amount IS '源扣费金额字段的正向金额，优先使用带元字段并兼容净扣费列，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.refund_amount IS '源退款金额，单位元，用于核对退款冲回。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.expense_amount IS '标准化支出净额：优先扣费金额，其次支出金额（元），最后扣费金额（元）减退款；退款冲回保留负号，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.expense_amount_source IS '本行支出净额实际采用的源字段或计算路径。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.source_file_name IS '来源文件名，用于识别八类服务费来源。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_expense_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_expense_shop_date
    ON dwd.dwd_tmall_settlement_expense_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_expense_order
    ON dwd.dwd_tmall_settlement_expense_event_detail (main_order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_expense_type
    ON dwd.dwd_tmall_settlement_expense_event_detail (expense_item, stat_date);

