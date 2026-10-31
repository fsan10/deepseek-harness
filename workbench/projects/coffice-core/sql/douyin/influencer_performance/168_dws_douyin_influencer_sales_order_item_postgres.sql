CREATE SCHEMA IF NOT EXISTS dws;

CREATE TABLE IF NOT EXISTS dws.dws_douyin_influencer_sales_order_item (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    traffic_source VARCHAR(128) NOT NULL,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    influencer_id VARCHAR(128) NOT NULL,
    influencer_name VARCHAR(255) NOT NULL,
    influencer_key VARCHAR(193) NOT NULL,
    traffic_channel VARCHAR(128),
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
    CONSTRAINT uq_dws_douyin_influencer_sales_source_id UNIQUE (source_id),
    CONSTRAINT ck_dws_douyin_influencer_sales_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::date)
);

COMMENT ON TABLE dws.dws_douyin_influencer_sales_order_item IS '抖音达人业绩指标专属DWS，一行一个精选联盟非刷单子订单；主订单任一子行订单应付金额大于2000元时整单排除。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.stat_date IS '达人业绩自然日，严格取订单提交日期。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.stat_month IS '订单提交日期所属自然月首日，仅供月度Top5、10万+和商务目标派生。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.shop_code IS '标准店铺编码，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.shop_name IS '标准店铺名称，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.main_order_no IS '主订单编号，用于整单排除刷单。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.sub_order_no IS '子订单编号，DWS最小业务粒度。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.traffic_source IS '流量来源，DWS固定只纳入精选联盟。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.order_status IS '订单状态；GMV不按此筛选，仅已关闭计入退款。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.after_sale_status IS '售后状态，仅保留审计，不参与GMV或退款筛选。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.influencer_id IS '规范达人ID；源ID为0的封禁或注销账号统一保留为0。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.influencer_name IS '达人展示名称；ID为0时统一为其他，其他ID使用源达人昵称。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.influencer_key IS '跨平台达人去重键，由平台编码和达人ID组成。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.traffic_channel IS '源流量渠道清洗值，仅供审计。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.product_unit_price IS '来源商品单价，整行直接作为GMV，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.order_pay_amount IS '来源订单应付金额，单位元；主订单任一子行大于2000元时整单不进入DWS。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.gmv_amount IS '达人GMV，直接等于本行商品单价，不乘商品数量，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.refund_amount IS '达人退款金额代理值；订单状态为已关闭时取本行商品单价，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.is_closed_refund IS '订单状态是否为已关闭；true表示本行GMV计入退款。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.included_sub_order_count IS '纳入达人DWS的子订单行计数，每行固定为1。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.source_id IS '来源ODS主键，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.source_batch_id IS '来源导入批次ID，来自指标DWD。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_douyin_influencer_sales_order_item.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dws_douyin_influencer_sales_date_shop
    ON dws.dws_douyin_influencer_sales_order_item (stat_date, shop_code);
CREATE INDEX IF NOT EXISTS idx_dws_douyin_influencer_sales_month_influencer
    ON dws.dws_douyin_influencer_sales_order_item (stat_month, influencer_id);
CREATE INDEX IF NOT EXISTS idx_dws_douyin_influencer_sales_influencer_key
    ON dws.dws_douyin_influencer_sales_order_item (influencer_key);
