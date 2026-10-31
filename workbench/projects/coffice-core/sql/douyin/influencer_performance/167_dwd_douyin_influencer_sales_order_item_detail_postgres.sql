CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_influencer_sales_order_item_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    source_shop_code VARCHAR(128),
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    stat_date DATE NOT NULL,
    order_submitted_at TIMESTAMP NOT NULL,
    traffic_source VARCHAR(128),
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    influencer_id_raw VARCHAR(128),
    influencer_name_raw VARCHAR(255),
    traffic_channel VARCHAR(128),
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
    CONSTRAINT uq_dwd_douyin_influencer_sales_source_id UNIQUE (source_id)
);

COMMENT ON TABLE dwd.dwd_douyin_influencer_sales_order_item_detail IS '抖音达人业绩指标专属DWD，一行一个最新子订单，保留全部流量来源、订单状态和售后状态，不执行指标筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.shop_code IS '标准店铺编码，通过来源批次关联common.v_ingest_batch_shop_context获得。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.shop_identity_key IS '标准店铺身份键，由平台编码和店铺编码组成。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_shop_code IS 'ODS所属门店ID清洗值，仅用于与批次店铺上下文核对。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.main_order_no IS '抖音主订单编号，用于按整单识别订单应付金额大于2000元的刷单。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.sub_order_no IS '抖音子订单编号，DWD最小业务粒度。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.stat_date IS '达人业绩统计自然日，严格取订单提交时间的日期部分。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.order_submitted_at IS '订单提交时间，是本指标的日期依据。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.traffic_source IS '流量来源清洗值；DWD不筛选，DWS仅纳入精选联盟。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.order_status IS '订单状态清洗值；DWD不筛选，DWS仅用已关闭计算退款。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.after_sale_status IS '售后状态清洗值，仅保留审计，不参与GMV或退款筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.influencer_id_raw IS '源达人ID清洗值；0的特殊处理在DWS完成。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.influencer_name_raw IS '源达人昵称清洗值；ID为0时在DWS统一为其他。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.traffic_channel IS '流量渠道清洗值，仅供达人流量审计；看板所称渠道使用标准平台维度。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.product_unit_price IS '商品单价，来自ODS同名字段；每行金额直接作为达人GMV，不乘商品数量，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.order_pay_amount IS '订单应付金额，来自ODS同名字段；仅用于识别大于2000元的刷单，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_id IS '来源ODS自增主键，用于逐行追溯。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_batch_id IS '来源导入批次ID，用于店铺上下文和文件追溯。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_file_name IS '来源订单文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_row_no IS '来源文件行号。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_influencer_sales_order_item_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_sales_stat_date
    ON dwd.dwd_douyin_influencer_sales_order_item_detail (stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_sales_main_order
    ON dwd.dwd_douyin_influencer_sales_order_item_detail (main_order_no);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_sales_influencer
    ON dwd.dwd_douyin_influencer_sales_order_item_detail (influencer_id_raw);
CREATE INDEX IF NOT EXISTS idx_dwd_douyin_influencer_sales_batch
    ON dwd.dwd_douyin_influencer_sales_order_item_detail (source_batch_id);
