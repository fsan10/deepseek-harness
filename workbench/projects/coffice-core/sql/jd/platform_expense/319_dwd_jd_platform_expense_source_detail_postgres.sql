CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_jd_platform_expense_source_detail (
    source_document_type VARCHAR(32) NOT NULL,
    source_event_key VARCHAR(128) NOT NULL,
    source_id BIGINT NOT NULL,
    secondary_category_name VARCHAR(768) NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
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
    merchant_order_no VARCHAR(128),
    document_type VARCHAR(128),
    source_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    directional_expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shop_identity_key, source_document_type, source_event_key),
    CONSTRAINT ck_dwd_jd_platform_expense_source_type
        CHECK (source_document_type IN ('settlement', 'fund'))
);

COMMENT ON TABLE dwd.dwd_jd_platform_expense_source_detail IS '京东平台费用候选DWD；结算单和钱包资金单保持独立来源，按业务唯一键选择最新版本，本层不执行费用映射或排除。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_document_type IS '来源单据类型；settlement为结算单，fund为京东钱包资金单。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_event_key IS '来源业务唯一键；结算取清洗后单据编号，资金取七个原始业务字段组合哈希。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_id IS '被选中最新版本的ODS记录主键。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.secondary_category_name IS '平台原始二级分类；结算取费用项，资金取交易类型，与原始费用候选一致；备注仍保留供已配置的细分规则匹配。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.platform_code IS '标准平台编码，京东固定为jd。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.platform_name IS '平台展示名称，固定为京东。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.stat_date IS '费用业务归属日；结算取账单日期，资金补充费用取入账日期。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.event_at IS '结算取原始费用结算时间，缺失时使用账单日期零点；该零点是兼容值，不代表真实结算时刻。资金仍取入账时间。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_direction IS '平台原始收支方向，枚举为收入或支出。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_business_type IS '结算取单据类型，资金取交易类型。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_description IS '资金动账备注原文；结算来源为空。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.flow_no IS '结算单据编号或资金交易订单号。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.order_no IS '结算订单编号或资金交易订单号中的关联订单标识。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.merchant_order_no IS '商户订单号，用于结算单和钱包商户结算跨日对账。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.document_type IS '结算单据类型；资金来源为空。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_amount IS '平台导出非负绝对金额，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.signed_amount IS '标准资金方向金额；收入为正、支出为负，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.directional_expense_amount IS '标准费用候选金额；支出为正、收入或返还为负，单位元。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_jd_platform_expense_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_jd_platform_expense_shop_date
    ON dwd.dwd_jd_platform_expense_source_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_jd_platform_expense_business
    ON dwd.dwd_jd_platform_expense_source_detail (
        source_document_type, source_business_type, stat_date
    );

CREATE INDEX IF NOT EXISTS idx_dwd_jd_platform_expense_merchant_order
    ON dwd.dwd_jd_platform_expense_source_detail (merchant_order_no);
