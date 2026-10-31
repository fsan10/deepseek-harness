CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_pdd_promotion_expense_detail;

CREATE TABLE dwd.dwd_pdd_promotion_expense_detail (
    source_record_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    expense_date DATE,
    fund_type VARCHAR(64),
    flow_type VARCHAR(64),
    source_shop_name VARCHAR(255),
    transaction_amount NUMERIC(18,2),
    balance_amount NUMERIC(18,2),
    transaction_summary TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_pdd_promotion_expense_detail IS '拼多多推广费流水DWD，一行对应一条来源资金流水，仅清洗字段，不筛选现金或支出状态。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_record_id IS '来源ods.ods_pdd_promotion_expense_raw主键。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.platform_name IS '标准平台名称，固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.shop_code IS '由批次店铺上下文解析的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.shop_name IS '由批次店铺上下文解析的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.shop_identity_key IS '来自批次上下文的平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.expense_date IS '推广费统计日期，取来源时间的日期部分。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.fund_type IS '来源资金类型，DWS要求为现金。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.flow_type IS '来源流水类型，DWS要求为支出。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_shop_name IS '来源店铺名称，用于与批次标准店铺核对。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.transaction_amount IS '清洗后的来源交易金额，单位元。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.balance_amount IS '清洗后的交易后余额，单位元，仅用于审计。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.transaction_summary IS '来源推广支出组成说明。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_batch_id IS '来源ODS文件导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_promotion_expense_detail.updated_at IS 'DWD记录最后更新时间。';

CREATE INDEX idx_dwd_pdd_promotion_expense_shop_date
    ON dwd.dwd_pdd_promotion_expense_detail (shop_code, expense_date);
CREATE INDEX idx_dwd_pdd_promotion_expense_batch
    ON dwd.dwd_pdd_promotion_expense_detail (source_batch_id);
