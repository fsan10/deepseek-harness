CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dws.dws_douyin_operating_sales_paid_order_item;

CREATE TABLE IF NOT EXISTS dws.dws_douyin_operating_sales_order_item (
    stat_date DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    product_id VARCHAR(128),
    product_name TEXT,
    traffic_content_type VARCHAR(128),
    traffic_channel VARCHAR(128),
    product_unit_price NUMERIC(18,2) NOT NULL,
    order_pay_amount NUMERIC(18,2) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL,
    refund_amount NUMERIC(18,2) NOT NULL,
    is_closed_refund BOOLEAN NOT NULL,
    sold_unit_count NUMERIC(18,2) NOT NULL,
    included_sub_order_count BIGINT NOT NULL DEFAULT 1,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dws_douyin_operating_sales_source_id UNIQUE (source_id)
);

COMMENT ON TABLE dws.dws_douyin_operating_sales_order_item IS '抖音运营成交指标专属DWS，一行一个非刷单子订单；若主订单任一子行订单应付金额达到2000元则整单排除，不筛选订单状态和售后状态。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.stat_date IS '成交统计日期，严格取订单提交日期，无兜底。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.shop_code IS '标准店铺编码，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.shop_name IS '标准店铺名称，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.main_order_no IS '主订单编号，ADS按统计日期、平台、公司和店铺去重计算成交订单数。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.sub_order_no IS '子订单编号，DWS最小业务粒度。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.order_status IS '订单状态清洗值；除已关闭用于生成退款外，不用于筛选。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.after_sale_status IS '售后状态清洗值，仅用于审计，不参与GMV或退款筛选。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.product_id IS '平台商品ID，仅保留订单链接审计；公司产品占比改由独立产品分摊DWS按商家编码计算。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.product_name IS '平台选购商品名称，仅保留订单链接审计；不再作为公司产品占比维度。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.traffic_content_type IS '流量体裁，流量结构一级维度。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.traffic_channel IS '流量渠道，流量结构二级维度。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.product_unit_price IS '来源商品单价，整行直接作为GMV，不乘商品数量，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.order_pay_amount IS '来源订单应付金额，单位元；主订单任一子行达到2000元时，该主订单全部子行不进入DWS。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.gmv_amount IS '运营GMV，直接等于商品单价，不乘商品数量，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.refund_amount IS '退款金额代理值；订单状态为已关闭时取本行商品单价GMV，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.is_closed_refund IS '订单状态是否为已关闭；true表示该行GMV计入退款。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.sold_unit_count IS '成交件数；商品单价大于0时取商品数量，零金额赠品记0，单位件。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.included_sub_order_count IS '纳入DWS的非刷单子订单计数，每行固定为1。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.source_id IS '来源ODS主键，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.source_batch_id IS '来源批次ID，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.source_updated_at IS '来源ODS最晚入库时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_operating_sales_order_item.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_douyin_operating_sales_date_shop
    ON dws.dws_douyin_operating_sales_order_item (stat_date, shop_code);

CREATE INDEX IF NOT EXISTS idx_dws_douyin_operating_sales_main_order
    ON dws.dws_douyin_operating_sales_order_item (main_order_no);

CREATE INDEX IF NOT EXISTS idx_dws_douyin_operating_sales_traffic
    ON dws.dws_douyin_operating_sales_order_item (traffic_content_type, traffic_channel);

CREATE INDEX IF NOT EXISTS idx_dws_douyin_operating_sales_product
    ON dws.dws_douyin_operating_sales_order_item (product_id);
