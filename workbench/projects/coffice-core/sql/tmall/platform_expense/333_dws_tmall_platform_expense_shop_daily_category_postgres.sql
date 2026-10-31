CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_tmall_platform_expense_shop_daily_category (
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
    expense_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ,
    mapping_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        stat_date,
        platform_code,
        shop_code,
        source_document_type,
        secondary_category_code
    )
);

COMMENT ON TABLE dws.dws_tmall_platform_expense_shop_daily_category IS '天猫主营业务支出店铺日分类DWS；两个资金账户的标准化二级场景经人工映射纳入，一级分类由财务维护。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.stat_date IS '费用业务归属日。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.platform_code IS '标准平台编码。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.platform_name IS '平台展示名称。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.primary_category_code IS '财务人工维护的一级费用分类编码。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.primary_category_name IS '财务人工维护的一级费用分类名称。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.secondary_category_code IS '业务类型加标准化备注对应的稳定二级分类编码。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.secondary_category_name IS '业务类型加标准化备注，例如转账 + 天猫佣金（类目系统）。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.source_document_type IS '来源单据类型，天猫两个账户统一为fund。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.expense_amount IS '主营业务支出净额；正常费用为正、费用退款或返还为负，单位元。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.included_detail_count IS '金额非零且映射为计入费用的来源明细数。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.source_detail_count IS '参与本行汇总的来源明细数。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.source_updated_at IS '参与汇总的DWD来源记录最晚时间。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.mapping_updated_at IS '本行费用映射最后更新时间。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_platform_expense_shop_daily_category.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_tmall_platform_expense_primary_date
    ON dws.dws_tmall_platform_expense_shop_daily_category (
        primary_category_code, stat_date
    );
CREATE INDEX IF NOT EXISTS idx_dws_tmall_platform_expense_secondary_date
    ON dws.dws_tmall_platform_expense_shop_daily_category (
        secondary_category_code, stat_date
    );

