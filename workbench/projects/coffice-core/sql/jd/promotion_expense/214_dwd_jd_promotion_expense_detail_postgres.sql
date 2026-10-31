CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_jd_promotion_expense_detail;

CREATE TABLE dwd.dwd_jd_promotion_expense_detail (
    source_type VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    expense_date DATE,
    transaction_id VARCHAR(128),
    transaction_type VARCHAR(128),
    settlement_status VARCHAR(64),
    settlement_type VARCHAR(128),
    source_amount NUMERIC(18,2),
    source_account_name VARCHAR(255),
    source_account_id VARCHAR(128),
    source_description TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_type, source_record_id),
    CONSTRAINT ck_dwd_jd_promotion_expense_source_type
        CHECK (source_type IN ('jd_tong', 'jd_union'))
);

COMMENT ON TABLE dwd.dwd_jd_promotion_expense_detail IS '京东推广费统一明细DWD，合并京东通和京东联盟流水，不在本层执行交易类型筛选。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_type IS '来源类型：jd_tong京东通或jd_union京东联盟。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_record_id IS '对应来源ODS表主键。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.platform_code IS '标准平台编码，固定为jd。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.platform_name IS '标准平台名称，固定为京东。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.shop_code IS '由批次店铺上下文解析的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.shop_name IS '由批次店铺上下文解析的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.shop_identity_key IS '来自批次上下文的平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.expense_date IS '推广费统计日期，两个来源均取结算时间日期。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.transaction_id IS '来源流水单号。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.transaction_type IS '京东通来源交易类型；联盟来源固定为京东联盟结算。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.settlement_status IS '京东联盟支付状态；京东通为空。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.settlement_type IS '京东联盟结算类型；京东通记录开票方式。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_amount IS '清洗后的京东通支出或京东联盟结算金额，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_account_name IS '京东通投放账户名称；联盟来源为空。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_account_id IS '京东通投放账户ID或从联盟流水号解析的账号ID。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_description IS '来源辅助说明；京东通为投放日期，联盟为费用时间。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_batch_id IS '来源ODS文件导入批次ID。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_jd_promotion_expense_detail.updated_at IS 'DWD记录最后更新时间。';

CREATE INDEX idx_dwd_jd_promotion_expense_shop_date
    ON dwd.dwd_jd_promotion_expense_detail (shop_code, expense_date);
CREATE INDEX idx_dwd_jd_promotion_expense_batch
    ON dwd.dwd_jd_promotion_expense_detail (source_batch_id);
