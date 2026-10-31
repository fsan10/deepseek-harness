CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_jd_settlement_net_document_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    source_shop_code VARCHAR(128),
    stat_date DATE NOT NULL,
    bill_date_raw VARCHAR(64) NOT NULL,
    document_no VARCHAR(128) NOT NULL,
    order_no VARCHAR(128),
    merchant_order_no VARCHAR(128),
    document_type VARCHAR(128),
    fee_item_name VARCHAR(128) NOT NULL,
    currency_code VARCHAR(32),
    income_expense_direction VARCHAR(64) NOT NULL,
    merchant_receivable_payable VARCHAR(64),
    source_amount NUMERIC(18,2) NOT NULL,
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    settlement_net_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    validation_difference_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_jd_settlement_net_document_detail IS '京东结算净额单据明细DWD，一个最新单据编号一行；结算净额由收入减支出计算，并与源带符号金额核验。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_id IS '最新版本ODS原始记录主键。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.platform_code IS '平台编码，京东固定为jd。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.platform_name IS '平台名称，京东固定为京东。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.shop_code IS '标准店铺编码，通过batch_id关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.shop_identity_key IS '稳定店铺身份键。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.shop_mapping_source IS '店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_shop_code IS '源结算单店铺号，仅用于与批次标准店铺核对。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.stat_date IS '结算净额统计日期，使用账单日期，无其他日期兜底。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.bill_date_raw IS '源账单日期原始值。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.document_no IS '清洗后单据编号，京东结算流水最小业务粒度。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.order_no IS '清洗后京东订单编号。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.merchant_order_no IS '清洗后商户订单号。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.document_type IS '源单据类型，本层不筛选。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.fee_item_name IS '源费用项名称。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.currency_code IS '源币种，当前为CNY。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.income_expense_direction IS '源收支方向，枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.merchant_receivable_payable IS '源商家应收/应付枚举，用于与收支方向交叉核对。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_amount IS '源带符号金额，收入为正、支出为负，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.income_amount IS '收入金额，仅收入方向取源金额，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.expense_amount IS '支出金额，仅支出方向对源金额取反，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.settlement_net_amount IS '计算结算净额，等于收入减支出，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.validation_difference_amount IS '计算结算净额减源带符号金额的差额，验收必须为0。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_jd_settlement_net_document_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE UNIQUE INDEX IF NOT EXISTS uq_dwd_jd_settlement_net_document
    ON dwd.dwd_jd_settlement_net_document_detail (platform_code, document_no);
CREATE INDEX IF NOT EXISTS idx_dwd_jd_settlement_net_shop_date
    ON dwd.dwd_jd_settlement_net_document_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_jd_settlement_net_validation
    ON dwd.dwd_jd_settlement_net_document_detail (validation_difference_amount)
    WHERE validation_difference_amount <> 0;

