CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_platform_expense_source_detail (
    source_document_type VARCHAR(32) NOT NULL,
    source_id BIGINT NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'ks',
    platform_name VARCHAR(64) NOT NULL DEFAULT '快手',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    source_direction VARCHAR(32) NOT NULL,
    source_business_type VARCHAR(128),
    source_description TEXT,
    flow_no VARCHAR(128),
    order_no VARCHAR(128),
    source_company_name VARCHAR(255),
    source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    directional_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_document_type, source_id, secondary_category_name),
    CONSTRAINT ck_dwd_ks_platform_expense_source_type
        CHECK (source_document_type IN ('settlement', 'fund'))
);

COMMENT ON TABLE dwd.dwd_ks_platform_expense_source_detail IS '快手平台费用候选来源DWD；结算单每条记录拆为八个原始费用字段，资金单每条流水保留平台原始业务类型和描述，本层不执行费用映射或排除。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_document_type IS '来源单据类型；settlement为结算明细，fund为资金账单。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_id IS '来源ODS记录主键。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.secondary_category_name IS '结算原始费用字段名，或资金原始业务类型与原始描述按“业务类型 + 描述”拼接的二级分类名称。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.platform_code IS '标准平台编码，快手固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.platform_name IS '平台展示名称，快手固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.stat_date IS '费用统计日期；结算来源取实际结算时间，资金来源取入账时间，均无兜底。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.event_at IS '清洗后的实际结算时间或资金入账时间。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_direction IS '源金额方向；结算来源固定为支出，资金来源原样保留收或支。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_business_type IS '快手资金账单原始业务类型；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_description IS '快手资金账单原始描述，原文完整保留；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.flow_no IS '资金账务流水号；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.order_no IS '源订单号或资金关联业务单号，清理首尾空白和制表符。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_company_name IS '结算来源账户名称，仅用于审计；资金来源为空。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_amount IS '来源原始符号金额；结算费用为非负，资金发生额为非负，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.directional_expense_amount IS '标准方向费用候选；结算费用为正，资金支出为正、收入为负，尚未执行映射筛选，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_platform_expense_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_platform_expense_shop_date
    ON dwd.dwd_ks_platform_expense_source_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_ks_platform_expense_business_description
    ON dwd.dwd_ks_platform_expense_source_detail (
        source_document_type, source_business_type, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dwd_ks_platform_expense_batch
    ON dwd.dwd_ks_platform_expense_source_detail (
        source_document_type, source_batch_id
    );
