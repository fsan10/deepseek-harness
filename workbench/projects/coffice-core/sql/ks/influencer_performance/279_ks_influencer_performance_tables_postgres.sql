CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_influencer_sales_order_item_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(192) NOT NULL,
    stat_date DATE NOT NULL,
    order_submitted_at TIMESTAMP NOT NULL,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    influencer_id_raw VARCHAR(128),
    influencer_name_raw VARCHAR(255),
    sales_channel VARCHAR(128),
    order_carrier VARCHAR(128),
    product_unit_price NUMERIC(18,2) NOT NULL,
    order_pay_amount NUMERIC(18,2) NOT NULL,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dwd_ks_influencer_source UNIQUE (source_id)
);

COMMENT ON TABLE dwd.dwd_ks_influencer_sales_order_item_detail IS '快手达人业绩专属DWD，一行对应一个ODS订单商品行，只清洗字段并保留状态，不执行达人、刷单或退款筛选。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.shop_code IS '标准店铺编码，通过batch_id关联批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.shop_identity_key IS '平台和标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.main_order_no IS '快手订单号，用于按整单识别实付款大于2000元的刷单。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.sub_order_no IS '订单号、商品规格字段和同商品行序号组成的商品行唯一键，不含导入批次。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.stat_date IS '达人业绩统计自然日，取订单创建时间日期。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.order_submitted_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.order_status IS '订单状态原枚举；DWD不筛选，DWS仅用交易关闭计算退款。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.after_sale_status IS '售后状态，仅供审计，不参与指标筛选。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.influencer_id_raw IS '来源CPS达人ID清洗值；空值、短横线和0的排除在DWS执行。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.influencer_name_raw IS '来源CPS达人昵称清洗值。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.sales_channel IS '来源渠道，例如分销或自营。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.order_carrier IS '来源订单载体，例如直播、短视频或商品卡。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.product_unit_price IS '商品单价，去货币符号后解析；每行直接作为GMV，不乘数量，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.order_pay_amount IS '实付款，仅用于整单识别大于2000元刷单，单位元。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.source_id IS '来源快手ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.source_batch_id IS '来源导入批次ID。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.source_file_name IS '来源订单文件名。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_influencer_sales_order_item_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_influencer_date
    ON dwd.dwd_ks_influencer_sales_order_item_detail (stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_ks_influencer_order
    ON dwd.dwd_ks_influencer_sales_order_item_detail (main_order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_ks_influencer_id
    ON dwd.dwd_ks_influencer_sales_order_item_detail (influencer_id_raw);

CREATE TABLE IF NOT EXISTS dws.dws_ks_influencer_sales_order_item (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(192) NOT NULL,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    influencer_id VARCHAR(128) NOT NULL,
    influencer_name VARCHAR(255) NOT NULL,
    influencer_key VARCHAR(193) NOT NULL,
    product_unit_price NUMERIC(18,2) NOT NULL,
    order_pay_amount NUMERIC(18,2) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL,
    refund_amount NUMERIC(18,2) NOT NULL,
    is_closed_refund BOOLEAN NOT NULL,
    included_sub_order_count BIGINT NOT NULL DEFAULT 1,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dws_ks_influencer_source UNIQUE (source_id),
    CONSTRAINT ck_dws_ks_influencer_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::date)
);

COMMENT ON TABLE dws.dws_ks_influencer_sales_order_item IS '快手达人业绩专属DWS，一行一个有效CPS达人ID且非刷单的订单商品行；交易关闭订单的同口径GMV计为退款。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.stat_date IS '达人业绩自然日，取订单创建日期。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.stat_month IS '订单创建日期所属自然月首日。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.platform_code IS '标准平台编码，固定为ks。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.platform_name IS '平台展示名称，固定为快手。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.shop_code IS '标准店铺编码，来自指标DWD。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.shop_name IS '标准店铺名称，来自指标DWD。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.main_order_no IS '订单号，用于整单排除大于2000元刷单。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.sub_order_no IS '订单商品行唯一键。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.order_status IS '订单状态；GMV不筛状态，交易关闭计退款。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.after_sale_status IS '售后状态，仅保留审计。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.influencer_id IS '有效CPS达人ID。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.influencer_name IS '快手达人展示昵称。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.influencer_key IS '跨平台达人去重键，格式为ks|达人ID。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.product_unit_price IS '商品单价，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.order_pay_amount IS '实付款，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.gmv_amount IS '达人GMV，等于本行商品单价，不乘数量，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.refund_amount IS '订单状态为交易关闭时取本行GMV，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.is_closed_refund IS '是否属于退款代理状态；快手true表示订单状态为交易关闭。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.included_sub_order_count IS '纳入指标的商品行数，每行固定为1。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.source_id IS '来源快手ODS主键。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.source_batch_id IS '来源导入批次ID。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_ks_influencer_sales_order_item.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_ks_influencer_date_shop
    ON dws.dws_ks_influencer_sales_order_item (stat_date, shop_code);
CREATE INDEX IF NOT EXISTS idx_dws_ks_influencer_month_id
    ON dws.dws_ks_influencer_sales_order_item (stat_month, influencer_id);
