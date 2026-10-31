CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dwd.dwd_pdd_influencer_commission_zero_order_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    source_row_key VARCHAR(192) NOT NULL,
    stat_date DATE NOT NULL,
    stat_date_source VARCHAR(32) NOT NULL,
    order_submitted_at TIMESTAMP NOT NULL,
    order_status VARCHAR(255),
    after_sale_status VARCHAR(255),
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, source_row_key),
    CONSTRAINT uq_dwd_pdd_influencer_commission_zero_source UNIQUE (source_id),
    CONSTRAINT ck_dwd_pdd_influencer_commission_zero_date_source
        CHECK (stat_date_source IN ('order_completed_time', 'order_no_prefix'))
);

COMMENT ON TABLE dwd.dwd_pdd_influencer_commission_zero_order_detail IS '拼多多达人佣金补零专属DWD，一行对应一个ODS订单来源行；不复用其他指标层，仅保留订单自然日、标准店铺和审计字段用于生成零值店铺日。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.platform_name IS '平台展示名称，固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.shop_identity_key IS '平台和标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.order_no IS '来源拼多多订单号。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_row_key IS '订单号、商品规格字段和同商品行序号组成的来源业务键，不含导入批次或ODS主键。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.stat_date IS '达人佣金补零统计自然日，优先取订单成交时间日期，缺失时由订单号前六位解析。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.stat_date_source IS '统计日期来源，枚举order_completed_time或order_no_prefix。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.order_submitted_at IS '清洗或由订单号解析出的订单时间。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.order_status IS '订单状态原枚举，仅保留审计；拼多多达人佣金固定为0。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.after_sale_status IS '售后状态原枚举，仅保留审计，不参与补零筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_id IS '来源拼多多ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_batch_id IS '来源导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_file_name IS '来源订单文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_influencer_commission_zero_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_influencer_commission_zero_date
    ON dwd.dwd_pdd_influencer_commission_zero_order_detail (stat_date, shop_code);

CREATE TABLE IF NOT EXISTS dws.dws_pdd_influencer_commission_shop_daily_zero (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    influencer_commission_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    included_detail_count BIGINT NOT NULL DEFAULT 0,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (stat_date, platform_code, shop_code),
    CONSTRAINT ck_dws_pdd_influencer_commission_zero_values
        CHECK (influencer_commission_amount = 0 AND included_detail_count = 0),
    CONSTRAINT ck_dws_pdd_influencer_commission_zero_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::date)
);

COMMENT ON TABLE dws.dws_pdd_influencer_commission_shop_daily_zero IS '拼多多达人佣金店铺日补零DWS，一天一个标准店铺占位行，保证平台、日期、公司和店铺筛选器可联动返回0。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.stat_date IS '订单成交自然日，成交时间缺失时由订单号前六位解析。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.stat_month IS '统计日期所属自然月首日。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.platform_code IS '标准平台编码，固定为pdd。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.platform_name IS '平台展示名称，固定为拼多多。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.influencer_commission_amount IS '拼多多达人佣金补零金额，固定为0元。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.included_detail_count IS '纳入达人佣金计算的来源明细数，补零行固定为0。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.source_updated_at IS '本店铺日来源DWD记录的最晚ODS入库时间。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_pdd_influencer_commission_shop_daily_zero.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_pdd_influencer_commission_zero_shop_date
    ON dws.dws_pdd_influencer_commission_shop_daily_zero (shop_code, stat_date);
