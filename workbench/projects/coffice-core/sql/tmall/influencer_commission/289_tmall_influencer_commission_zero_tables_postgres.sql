CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dwd.dwd_tmall_influencer_commission_zero_order_detail;

CREATE TABLE dwd.dwd_tmall_influencer_commission_zero_order_detail (
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
    source_sheet_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, source_row_key),
    CONSTRAINT uq_dwd_tmall_influencer_commission_zero_source UNIQUE (source_id)
);

COMMENT ON TABLE dwd.dwd_tmall_influencer_commission_zero_order_detail IS '天猫达人佣金补零专属DWD，一行一个标准店铺下最新子订单版本；仅保留订单创建自然日、标准店铺及审计字段用于生成0元店铺日。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.shop_code IS '标准店铺编码，通过source_batch_id关联批次店铺上下文取得。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.shop_identity_key IS '平台与标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.order_no IS '来源天猫主订单编号。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_row_key IS '来源天猫子订单编号，作为补零DWD最小业务键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.stat_date IS '达人佣金补零统计自然日，取订单创建时间日期。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.order_submitted_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.order_status IS '子订单状态原枚举，仅用于审计；天猫达人佣金固定为0。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_id IS '所选最新版本对应的天猫ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_file_name IS '来源销售明细文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_sheet_name IS '来源工作表名称。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_commission_zero_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX idx_dwd_tmall_influencer_commission_zero_date
    ON dwd.dwd_tmall_influencer_commission_zero_order_detail (stat_date, shop_code);

DROP TABLE IF EXISTS dws.dws_tmall_influencer_commission_shop_daily_zero;

CREATE TABLE dws.dws_tmall_influencer_commission_shop_daily_zero (
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
    CONSTRAINT ck_dws_tmall_influencer_commission_zero_values
        CHECK (influencer_commission_amount = 0 AND included_detail_count = 0),
    CONSTRAINT ck_dws_tmall_influencer_commission_zero_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::DATE)
);

COMMENT ON TABLE dws.dws_tmall_influencer_commission_shop_daily_zero IS '天猫达人佣金店铺日补零DWS，一天一个标准店铺0元占位行，保证公司、平台、店铺和日期筛选器联动。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.stat_date IS '订单创建自然日。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.stat_month IS '统计日期所属自然月首日。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.shop_code IS '标准店铺编码。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.shop_name IS '标准店铺名称。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.influencer_commission_amount IS '天猫达人佣金补零金额，固定为0元。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.included_detail_count IS '纳入达人佣金计算的明细数，补零行固定为0。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.source_updated_at IS '本店铺日来源DWD记录的最晚ODS入库时间。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_influencer_commission_shop_daily_zero.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX idx_dws_tmall_influencer_commission_zero_shop_date
    ON dws.dws_tmall_influencer_commission_shop_daily_zero (shop_code, stat_date);
