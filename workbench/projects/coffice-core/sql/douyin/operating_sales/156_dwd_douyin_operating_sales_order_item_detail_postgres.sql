CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_operating_sales_order_item_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    source_shop_code VARCHAR(128),
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    stat_date DATE,
    order_submitted_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    product_id VARCHAR(128),
    merchant_code VARCHAR(512),
    product_name TEXT,
    product_spec TEXT,
    product_quantity NUMERIC(18,2) NOT NULL,
    product_unit_price NUMERIC(18,2) NOT NULL,
    order_pay_amount NUMERIC(18,2) NOT NULL,
    gmv_amount NUMERIC(18,2) NOT NULL,
    traffic_content_type VARCHAR(128),
    traffic_channel VARCHAR(128),
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dwd_douyin_operating_sales_source_id UNIQUE (source_id)
);

ALTER TABLE dwd.dwd_douyin_operating_sales_order_item_detail
    ADD COLUMN IF NOT EXISTS product_unit_price NUMERIC(18,2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS merchant_code VARCHAR(512),
    DROP COLUMN IF EXISTS payment_completed_at,
    DROP COLUMN IF EXISTS discount_total_amount,
    DROP COLUMN IF EXISTS merchant_actual_discount_amount;

ALTER TABLE dwd.dwd_douyin_operating_sales_order_item_detail
    ALTER COLUMN product_unit_price DROP DEFAULT;

COMMENT ON TABLE dwd.dwd_douyin_operating_sales_order_item_detail IS '抖音运营成交指标专属DWD，一行一个最新子订单，保留全部订单和售后状态，不执行刷单、订单状态、售后状态或赠品筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.platform_code IS '标准平台编码，固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.platform_name IS '平台展示名称，固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.shop_code IS '标准店铺编码，通过source_batch_id关联common.v_ingest_batch_shop_context获得。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.shop_identity_key IS '标准店铺身份键，由平台编码和店铺编码组成。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.shop_mapping_source IS '批次店铺映射来源，用于审计人工或机器人确认方式。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_shop_code IS 'ODS所属门店ID清洗值；空值或横杠转为空，仅用于与批次店铺上下文核对。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.main_order_no IS '抖音主订单编号，成交订单数按此字段去重。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.sub_order_no IS '抖音子订单编号，DWD最小业务粒度和稳定唯一键。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.stat_date IS '运营成交统计日期，严格取订单提交时间的日期部分，无其他日期兜底。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.order_submitted_at IS '订单提交时间，来自ODS订单提交时间，是成交统计日期依据。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.order_status IS '订单状态原始枚举清洗值；DWD不按状态筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.after_sale_status IS '售后状态原始枚举清洗值，仅保留审计，本指标退款不使用该字段。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.product_id IS '抖音商品ID，来自ODS商品ID，仅保留平台链接审计，不再作为公司产品占比维度。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.merchant_code IS '商家编码原始清洗值，来自ODS商家编码；组合装按加号拆分并在产品分摊DWS映射公司统一产品。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.product_name IS '选购商品名称，来自ODS选购商品并清理首尾空白，仅保留平台链接审计，不再作为公司产品占比维度。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.product_spec IS '商品规格，来自ODS商品规格并清理首尾空白；产品分摊DWS使用“赠”字位置识别有序商家编码中的赠品组件。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.product_quantity IS '商品数量，来自ODS商品数量，清理空白和千分位逗号后解析，单位件。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.product_unit_price IS '商品单价，来自ODS同名字段，清理空白和千分位逗号后解析；整行金额直接作为本行GMV，不乘商品数量，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.order_pay_amount IS '订单应付金额，来自ODS同名字段，清理空白和千分位逗号后解析；仅用于识别任一子行达到2000元的刷单主订单，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.gmv_amount IS '运营GMV，直接等于本行商品单价，不乘商品数量，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.traffic_content_type IS '流量体裁，来自ODS流量体裁，作为流量结构一级维度。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.traffic_channel IS '流量渠道，来自ODS流量渠道，作为流量结构二级维度。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_id IS '来源ODS自增主键，用于逐行追溯。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_batch_id IS '来源导入批次ID，用于店铺上下文和文件追溯。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_file_name IS '来源订单文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_row_no IS '来源CSV行号。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_operating_sales_order_item_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_operating_sales_stat_date
    ON dwd.dwd_douyin_operating_sales_order_item_detail (stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_operating_sales_main_order
    ON dwd.dwd_douyin_operating_sales_order_item_detail (main_order_no);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_operating_sales_product
    ON dwd.dwd_douyin_operating_sales_order_item_detail (product_id);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_operating_sales_source_batch
    ON dwd.dwd_douyin_operating_sales_order_item_detail (source_batch_id);
