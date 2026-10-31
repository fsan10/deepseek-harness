CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_tmall_main_business_income_source_detail (
    source_account_type VARCHAR(32) NOT NULL,
    source_event_key VARCHAR(160) NOT NULL,
    source_id BIGINT NOT NULL,
    standardized_note VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    stat_date DATE NOT NULL,
    event_at TIMESTAMP NOT NULL,
    source_business_type VARCHAR(128) NOT NULL,
    source_description TEXT,
    flow_no VARCHAR(128) NOT NULL,
    business_flow_no VARCHAR(128),
    merchant_order_no VARCHAR(256),
    main_order_no VARCHAR(128),
    sub_order_no VARCHAR(128),
    signed_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shop_identity_key, source_account_type, source_event_key),
    CONSTRAINT ck_dwd_tmall_main_business_income_account
        CHECK (source_account_type IN ('aggregate', 'alipay'))
);

COMMENT ON TABLE dwd.dwd_tmall_main_business_income_source_detail IS '天猫主营业务收入候选DWD；聚合账户和支付宝账户一行一条最新资金流水，本层清洗字段和备注但不筛选收入、退款或提现。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_account_type IS '资金账户来源；aggregate为聚合账户，alipay为支付宝账户。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_event_key IS '账户内业务唯一键；聚合账户取支付流水号，支付宝账户取账务流水号。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_id IS '被选中最新版本的ODS记录主键。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.standardized_note IS '去除实例订单号后的稳定资金场景。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.secondary_category_name IS '平台业务类型加标准化备注形成的收入或退款二级明细名称。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.shop_code IS '标准店铺编码，通过批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.shop_identity_key IS '稳定店铺身份键，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.shop_mapping_source IS '批次店铺映射来源。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.stat_date IS '主营业务收入归属日；聚合账户取入帐日期，支付宝账户取发生时间日期。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.event_at IS '资金流水发生时间。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_business_type IS '平台原始业务类型。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_description IS '平台资金备注原文。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.flow_no IS '聚合账户支付流水号或支付宝账务流水号。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.business_flow_no IS '支付宝业务流水号；聚合账户为空。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.merchant_order_no IS '支付宝商户订单号；聚合账户为空。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.main_order_no IS '聚合账户主订单ID；支付宝来源为空。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.sub_order_no IS '聚合账户子订单ID；支付宝来源为空。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.signed_amount IS '标准资金方向金额；订单收款为正、销售退款和提现为负，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_file_name IS '来源文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_main_business_income_source_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_tmall_main_business_income_shop_date
    ON dwd.dwd_tmall_main_business_income_source_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_tmall_main_business_income_type_date
    ON dwd.dwd_tmall_main_business_income_source_detail (
        source_business_type, standardized_note, stat_date
    );

