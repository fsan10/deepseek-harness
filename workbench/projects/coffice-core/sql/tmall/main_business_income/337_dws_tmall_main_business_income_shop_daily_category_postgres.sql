CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_main_business_income_shop_daily_category (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    primary_category_code VARCHAR(64) NOT NULL,
    primary_category_name VARCHAR(128) NOT NULL,
    secondary_category_code VARCHAR(128) NOT NULL,
    secondary_category_name VARCHAR(256) NOT NULL,
    source_document_type VARCHAR(32) NOT NULL DEFAULT 'fund',
    income_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date,
        platform_code,
        shop_code,
        source_document_type,
        primary_category_code,
        secondary_category_code
    )
);

COMMENT ON TABLE dws.dws_tmall_main_business_income_shop_daily_category IS '天猫主营业务收入店铺日分类DWS；两个资金账户订单收款为正收入，销售退款为负收入，提现和费用均排除。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.stat_date IS '主营业务收入业务归属日。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.primary_category_code IS '收入一级分类编码；sales_income或sales_refund。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.primary_category_name IS '收入一级分类名称；商品销售收入或销售退款。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.secondary_category_code IS '账户资金场景对应的稳定收入二级分类编码。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.secondary_category_name IS '业务类型加标准化备注形成的收入二级明细名称。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.source_document_type IS '来源单据类型，天猫两个账户统一为fund。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.income_amount IS '主营业务收入金额；订单收款为正、销售退款为负，单位元。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.included_detail_count IS '参与本行汇总的来源资金明细数。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.source_updated_at IS '参与汇总的DWD来源记录最晚时间。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_main_business_income_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_main_business_income_primary_date
    ON dws.dws_tmall_main_business_income_shop_daily_category (
        primary_category_code, stat_date
    );

