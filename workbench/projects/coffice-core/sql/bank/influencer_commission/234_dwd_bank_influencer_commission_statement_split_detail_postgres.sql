CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_bank_influencer_commission_statement_split_detail (
    source_split_id BIGINT NOT NULL PRIMARY KEY,
    source_ods_id BIGINT NOT NULL,
    source_batch_id VARCHAR(32) NOT NULL,
    split_index INTEGER NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'bank',
    platform_name VARCHAR(64) NOT NULL DEFAULT '银行',
    stat_date DATE NOT NULL,
    transaction_time TIME,
    source_account_no VARCHAR(128),
    source_account_name VARCHAR(256) NOT NULL,
    transaction_type VARCHAR(128),
    summary TEXT,
    transaction_no VARCHAR(128),
    debit_amount NUMERIC(18,2),
    credit_amount NUMERIC(18,2),
    split_amount NUMERIC(18,2) NOT NULL,
    original_amount NUMERIC(18,2) NOT NULL,
    adjusted_diff NUMERIC(18,2) NOT NULL DEFAULT 0,
    adjusted_amount NUMERIC(18,2) NOT NULL,
    expense_type_code VARCHAR(32) NOT NULL,
    expense_type_name VARCHAR(128) NOT NULL,
    account_entry_code VARCHAR(32) NOT NULL,
    account_entry_name VARCHAR(128) NOT NULL,
    directional_expense_amount NUMERIC(18,2) NOT NULL,
    is_adjusted BOOLEAN NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_bank_influencer_commission_statement_split_detail IS '银行达人佣金指标专属拆分明细DWD；读取财务成功且已提交批次的全部拆分分类，不在本层筛选达人佣金分类。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_split_id IS '来源dwd.dwd_statement_split.id，作为财务拆分明细稳定主键。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_ods_id IS '来源银行ODS流水ID。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_batch_id IS '来源银行导入批次号，仅纳入成功且财务已提交批次。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.split_index IS '同一ODS流水内的拆分序号。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.platform_code IS '来源平台编码，固定为bank。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.platform_name IS '来源平台名称，固定为银行。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.stat_date IS '统计日期，取银行ODS交易日期transaction_date。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.transaction_time IS '银行源交易时间。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_account_no IS '银行源账号。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_account_name IS '银行源账号名称，用于ADS唯一解析公司。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.transaction_type IS '银行源交易类型。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.summary IS '银行源交易摘要，仅用于审计，不参与分类筛选。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.transaction_no IS '银行源流水号。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.debit_amount IS '银行源借方金额，单位元；存在时表示资金流出。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.credit_amount IS '银行源贷方金额，单位元；存在时表示资金流入或费用冲回。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.split_amount IS '财务拆分基准金额，单位元。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.original_amount IS '拆分行调账前金额，单位元。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.adjusted_diff IS '财务手工调账差额，单位元。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.adjusted_amount IS '调账后金额=original_amount+adjusted_diff，单位元。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.expense_type_code IS '财务费用类型编码。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.expense_type_name IS '财务费用类型名称，本层保留全部分类。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.account_entry_code IS '财务入账科目编码。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.account_entry_name IS '财务入账科目名称，本层保留全部分类。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.directional_expense_amount IS '按费用口径标准化的带符号金额：借方流出为正、贷方冲回为负，单位元。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.is_adjusted IS '该拆分明细是否发生财务手工调账。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.source_updated_at IS 'ODS、拆分或提交状态中的最晚来源更新时间。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_bank_influencer_commission_statement_split_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_bank_influencer_commission_account_date
    ON dwd.dwd_bank_influencer_commission_statement_split_detail (source_account_name, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_bank_influencer_commission_classification
    ON dwd.dwd_bank_influencer_commission_statement_split_detail (expense_type_code, account_entry_code, stat_date);

