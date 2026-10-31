CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_tmall_promotion_expense_detail;

CREATE TABLE dwd.dwd_tmall_promotion_expense_detail (
    source_type VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    expense_date DATE,
    receipts_type VARCHAR(64),
    transaction_type VARCHAR(64),
    source_amount NUMERIC(18,2),
    source_description TEXT,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_type, source_record_id),
    CONSTRAINT ck_dwd_tmall_promotion_expense_source_type
        CHECK (source_type IN ('taobao_union', 'wanxiangtai'))
);

COMMENT ON TABLE dwd.dwd_tmall_promotion_expense_detail IS '天猫推广费统一明细DWD，合并淘宝联盟日数据和万相台流水，不在本层执行收支或交易类型筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_type IS '来源类型：taobao_union淘宝联盟或wanxiangtai万相台。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_record_id IS '对应来源ODS表主键。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.platform_name IS '标准平台名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.shop_code IS '由批次店铺上下文解析的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.shop_name IS '由批次店铺上下文解析的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.shop_identity_key IS '来自批次上下文的平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.expense_date IS '推广费统计日期；淘宝联盟取日期，万相台取记账时间日期。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.receipts_type IS '万相台来源收支类型；淘宝联盟为空。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.transaction_type IS '万相台来源交易类型；淘宝联盟固定为淘宝联盟结算。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_amount IS '清洗后的淘宝联盟结算支出费用或万相台操作金额，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_description IS '来源辅助说明；万相台为备注，淘宝联盟为结算笔数。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_batch_id IS '来源ODS文件导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_promotion_expense_detail.updated_at IS 'DWD记录最后更新时间。';

CREATE INDEX idx_dwd_tmall_promotion_expense_shop_date
    ON dwd.dwd_tmall_promotion_expense_detail (shop_code, expense_date);
CREATE INDEX idx_dwd_tmall_promotion_expense_batch
    ON dwd.dwd_tmall_promotion_expense_detail (source_batch_id);
