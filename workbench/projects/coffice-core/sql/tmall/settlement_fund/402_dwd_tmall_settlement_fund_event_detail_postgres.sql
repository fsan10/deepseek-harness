CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_tmall_settlement_fund_event_detail (
    source_event_key VARCHAR(256) NOT NULL PRIMARY KEY,
    source_account_type VARCHAR(32) NOT NULL,
    source_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    bill_period_raw VARCHAR(8) NOT NULL,
    source_business_type VARCHAR(128) NOT NULL,
    source_direction VARCHAR(16) NOT NULL,
    source_description TEXT,
    order_no VARCHAR(128),
    business_flow_no VARCHAR(128),
    merchant_order_no VARCHAR(128),
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    income_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    expense_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    expense_type_code VARCHAR(64) NOT NULL DEFAULT 'unclassified',
    expense_type_name VARCHAR(128) NOT NULL DEFAULT '未分类',
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_tmall_settlement_fund_event_detail IS '天猫资金来源结算事件明细；完整保留支付宝与聚合账户资金行，在DWS按收款和已识别平台费用口径纳入结算指标。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_event_key IS '资金来源和ODS主键组成的稳定事件键，避免两个账户自增ID碰撞。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_account_type IS '资金账户类型，aggregate表示聚合账户，alipay表示支付宝账户。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_id IS '对应资金ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.shop_identity_key IS '平台与店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.shop_mapping_source IS '店铺映射来源，继承导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.stat_date IS '结算统计日期；聚合账户取入帐日期，支付宝账户取发生时间的日期部分。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.bill_period_raw IS '由资金统计日期生成的YYYYMMDD期间值，用于与旧结算账期口径对齐。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_business_type IS '资金来源业务类型，保留原始枚举且不在DWD丢弃记录。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_direction IS '按资金带符号金额归一的方向：收入、支出或零金额。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_description IS '资金备注或业务描述，保留原文用于费用分类追溯。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.order_no IS '来源主订单号或聚合账户主订单ID。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.business_flow_no IS '支付宝业务流水号；聚合账户无该字段时为空。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.merchant_order_no IS '支付宝商户订单号；聚合账户无该字段时为空。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.income_amount IS '资金正向收入金额，仅交易收款/交易付款进入结算收入候选，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.expense_amount IS '标准化费用金额，支出为正、费用退回为负，只有已识别费用场景进入结算支出候选，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.signed_amount IS '资金原始带符号金额：聚合账户收入减支出，支付宝收入加负向支出，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.refund_amount IS '交易退款金额绝对值，仅作审计；按天猫收入不减退款口径不参与收入扣减，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.income_eligible IS '是否为结算收入候选：聚合账户交易收款或支付宝交易付款。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.expense_eligible IS '是否命中结算费用分类；提现、内部转账、普通退款等非费用资金行保留但不纳入。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.expense_type_code IS '标准费用类型编码，未识别资金行固定为unclassified。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.expense_type_name IS '标准费用类型名称，来自备注/业务类型映射。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_file_name IS '来源资金文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_settlement_fund_event_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_fund_date
    ON dwd.dwd_tmall_settlement_fund_event_detail (stat_date, source_account_type);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_fund_shop
    ON dwd.dwd_tmall_settlement_fund_event_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_settlement_fund_expense_type
    ON dwd.dwd_tmall_settlement_fund_event_detail (expense_type_code, stat_date);
