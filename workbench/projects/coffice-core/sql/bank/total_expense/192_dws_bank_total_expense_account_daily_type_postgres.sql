CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_bank_total_expense_account_daily_type (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    source_account_name VARCHAR(256) NOT NULL,
    expense_type_code VARCHAR(64) NOT NULL,
    expense_type_name VARCHAR(100) NOT NULL,
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, source_account_name, expense_type_code)
);

CREATE INDEX IF NOT EXISTS idx_dws_bank_total_expense_account_date
    ON dws.dws_bank_total_expense_account_daily_type (source_account_name, stat_date);
CREATE INDEX IF NOT EXISTS idx_dws_bank_total_expense_type_date
    ON dws.dws_bank_total_expense_account_daily_type (expense_type_code, stat_date);

COMMENT ON TABLE dws.dws_bank_total_expense_account_daily_type IS '银行总费用账号日类型DWS；汇总销售费用、管理费用、税金及附加、人员成本、财务费用和营业外支出净额。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.stat_date IS '统计日期，使用银行ODS交易日期transaction_date。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.platform_code IS '来源平台编码，银行流水固定为bank。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.platform_name IS '来源平台名称，银行流水固定为银行。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.source_account_name IS '银行账号名称，用于ADS匹配标准公司。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.expense_type_code IS '费用分类稳定编码：selling_expense、administrative_expense、tax_and_surcharge、personnel_cost、financial_expense或non_operating_expense。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.expense_type_name IS '费用分类展示名称，来自用户确认的六类费用。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.expense_amount IS '费用净额，借方流出为正费用、贷方退款或冲回为负费用，单位元。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.included_detail_count IS '纳入该费用分类的财务拆分明细数；无符合记录时为0。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.source_updated_at IS '参与统计的财务拆分明细最晚更新时间。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.created_at IS 'DWS记录创建时间，带时区。';
COMMENT ON COLUMN dws.dws_bank_total_expense_account_daily_type.updated_at IS 'DWS记录最后刷新时间，带时区。';

