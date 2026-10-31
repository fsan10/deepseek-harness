CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_douyin_promotion_expense_detail;

CREATE TABLE dwd.dwd_douyin_promotion_expense_detail (
    source_record_id BIGINT PRIMARY KEY,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    expense_date DATE,
    non_gift_spend_amount NUMERIC(18,2),
    gift_spend_amount NUMERIC(18,2),
    source_date_text VARCHAR(64),
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dwd.dwd_douyin_promotion_expense_detail IS '抖音推广费日明细DWD，一行对应一条千川财务日记录，仅清洗日期和非赠款消耗，不执行业务筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_record_id IS '来源ods.ods_douyin_qianchuan_finance_raw主键。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.platform_name IS '标准平台名称，固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.shop_code IS '由批次店铺上下文解析的标准店铺编码。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.shop_name IS '由批次店铺上下文解析的标准店铺名称。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.shop_identity_key IS '来自批次上下文的平台店铺稳定身份键。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.expense_date IS '推广费统计日期，直接取来源日期。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.non_gift_spend_amount IS '清洗后的非赠款消耗，抖音推广费金额来源，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.gift_spend_amount IS '清洗后的赠款消耗，仅作审计，不计入推广费，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_date_text IS '来源日期原始文本。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_batch_id IS '来源ODS文件导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_promotion_expense_detail.updated_at IS 'DWD记录最后更新时间。';

CREATE INDEX idx_dwd_douyin_promotion_expense_shop_date
    ON dwd.dwd_douyin_promotion_expense_detail (shop_code, expense_date);
CREATE INDEX idx_dwd_douyin_promotion_expense_batch
    ON dwd.dwd_douyin_promotion_expense_detail (source_batch_id);
