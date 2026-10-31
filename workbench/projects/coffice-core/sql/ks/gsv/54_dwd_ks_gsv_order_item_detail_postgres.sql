CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_ks_gsv_order_item_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'ks',
    platform_name VARCHAR(64) NOT NULL DEFAULT '快手',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL,

    order_no VARCHAR(128) NOT NULL,
    product_id VARCHAR(128),
    sku_code VARCHAR(255),
    stat_date DATE,
    stat_date_source VARCHAR(32) NOT NULL,
    order_created_at TIMESTAMP,
    order_paid_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,

    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128),
    source_row_no INTEGER,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, source_id),
    CONSTRAINT ck_dwd_ks_gsv_stat_date_source
        CHECK (stat_date_source IN ('payment_time', 'creation_time', 'missing')),
    CONSTRAINT ck_dwd_ks_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

COMMENT ON TABLE dwd.dwd_ks_gsv_order_item_detail IS '快手GSV订单商品行明细表，一条ODS订单商品行对应一行；只做金额和日期清洗及批次店铺解析，不执行订单或售后状态筛选。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.platform_code IS '平台编码，快手固定为ks。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.platform_name IS '平台名称，快手固定为快手。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.shop_code IS '标准店铺编码，通过ODS批次ID关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.shop_name IS '标准店铺名称，来自已确认的批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.shop_identity_key IS '稳定店铺身份键，来自common.v_ingest_batch_shop_context。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.shop_code_source IS '店铺编码来源，固定为batch_context。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.order_no IS '快手订单号，同一订单可包含多个商品行。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.product_id IS '商品ID，来自ODS商品ID，用于识别订单商品行。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.sku_code IS 'SKU编码，来自ODS SKU编码。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.stat_date IS 'GSV统计日期，优先取订单支付时间，缺失时取订单创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.stat_date_source IS '统计日期来源：payment_time、creation_time或missing。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.order_created_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.order_paid_at IS '清洗后的订单支付时间。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.order_status IS '订单状态原枚举；DWD保留原值，不在本层排除交易关闭。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.after_sale_status IS '售后状态原枚举；DWD不筛选，DWS排除退款成功商品行。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.paid_amount IS '清洗后的实付款，单位元，去除货币符号后保留原始正负号，为快手GSV公式金额。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_id IS '对应ODS原始记录的主键ID，与平台编码共同组成DWD主键。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_batch_id IS '对应ODS导入批次ID，用于关联批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_file_name IS '对应ODS来源文件名。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_sheet_name IS '对应ODS来源Sheet名。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_row_no IS '对应ODS来源文件行号。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.source_updated_at IS '对应ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_ks_gsv_order_item_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_ks_gsv_stat_date
    ON dwd.dwd_ks_gsv_order_item_detail (stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_ks_gsv_shop_date
    ON dwd.dwd_ks_gsv_order_item_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_ks_gsv_order_no
    ON dwd.dwd_ks_gsv_order_item_detail (order_no);
