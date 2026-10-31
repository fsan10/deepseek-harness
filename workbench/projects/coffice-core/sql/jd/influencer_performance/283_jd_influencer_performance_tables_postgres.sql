CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dwd.dwd_jd_influencer_zero_order_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    source_row_key VARCHAR(192) NOT NULL,
    stat_date DATE NOT NULL,
    order_submitted_at TIMESTAMP NOT NULL,
    order_status VARCHAR(255),
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, source_row_key),
    CONSTRAINT uq_dwd_jd_influencer_zero_source UNIQUE (source_id)
);

COMMENT ON TABLE dwd.dwd_jd_influencer_zero_order_detail IS '京东达人指标补零专属DWD，一行对应一个ODS订单来源行；京东当前无达人字段，仅清洗订单自然日和店铺用于生成零值店铺日。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.platform_code IS '标准平台编码，固定为jd。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.platform_name IS '平台展示名称，固定为京东。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.shop_identity_key IS '平台和标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.order_no IS '来源京东订单号。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_row_key IS '订单号、商品规格字段和同商品行序号组成的来源业务键，不含导入批次或ODS主键。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.stat_date IS '补零统计自然日，取下单时间日期。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.order_submitted_at IS '清洗后的下单时间。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.order_status IS '订单状态原枚举，仅保留审计；京东达人指标固定为0。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_id IS '来源京东ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_batch_id IS '来源导入批次ID。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_file_name IS '来源订单文件名。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_jd_influencer_zero_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_jd_influencer_zero_date
    ON dwd.dwd_jd_influencer_zero_order_detail (stat_date, shop_code);

CREATE TABLE IF NOT EXISTS dws.dws_jd_influencer_sales_shop_daily_zero (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    influencer_id VARCHAR(128) NOT NULL,
    influencer_name VARCHAR(255) NOT NULL,
    influencer_key VARCHAR(193) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_sub_order_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code, influencer_id),
    CONSTRAINT ck_dws_jd_influencer_zero_amount
        CHECK (gmv_amount = 0 AND refund_amount = 0 AND included_sub_order_count = 0),
    CONSTRAINT ck_dws_jd_influencer_zero_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::date)
);

COMMENT ON TABLE dws.dws_jd_influencer_sales_shop_daily_zero IS '京东达人指标店铺日补零DWS，一天一个店铺占位行，保证平台、日期、公司和店铺筛选器可返回0。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.stat_date IS '订单下单自然日。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.stat_month IS '统计日期所属自然月首日。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.platform_code IS '标准平台编码，固定为jd。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.platform_name IS '平台展示名称，固定为京东。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.influencer_id IS '补零占位ID，固定为__no_influencer__，不得计入达人总量。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.influencer_name IS '补零展示名称，固定为无达人。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.influencer_key IS '补零跨平台键，固定为jd|__no_influencer__。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.gmv_amount IS '京东达人GMV预留值，固定为0元。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.refund_amount IS '京东达人退款预留值，固定为0元。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.included_sub_order_count IS '达人订单行数预留值，固定为0。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.source_updated_at IS '本店铺日来源DWD记录的最晚ODS入库时间。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_jd_influencer_sales_shop_daily_zero.updated_at IS 'DWS记录最后刷新时间。';
