CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_xhs_gsv_order_item_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'xhs',
    platform_name VARCHAR(64) NOT NULL DEFAULT '小红书',
    source_shop_name VARCHAR(255),
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    specification_id VARCHAR(128),
    product_id VARCHAR(128),
    product_name TEXT,
    sku_name TEXT,
    sku_quantity NUMERIC(18,2) NOT NULL DEFAULT 0,
    stat_date DATE,
    stat_date_source VARCHAR(32) NOT NULL,
    order_created_at TIMESTAMP,
    order_paid_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),
    merchant_receivable_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    shop_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    user_payable_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128),
    source_row_no INTEGER,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, source_id),
    CONSTRAINT ck_dwd_xhs_gsv_stat_date_source
        CHECK (stat_date_source IN ('payment_time', 'creation_time', 'missing')),
    CONSTRAINT ck_dwd_xhs_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

COMMENT ON TABLE dwd.dwd_xhs_gsv_order_item_detail IS '小红书GSV订单SKU明细表，一条ODS包裹商品行对应一行；只清洗字段并解析批次店铺，不执行订单或售后状态筛选。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.platform_code IS '平台编码，小红书固定为xhs。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.platform_name IS '平台名称，固定为小红书。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_shop_name IS 'ODS店铺名称原值，用于与批次店铺上下文核对。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.shop_code IS '标准店铺编码，通过ODS批次ID关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.shop_name IS '标准店铺名称，来自已确认的批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.shop_identity_key IS '稳定店铺身份键，来自common.v_ingest_batch_shop_context。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.shop_code_source IS '店铺编码来源，固定为batch_context。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.order_no IS '小红书订单号，同一订单可包含多条SKU明细。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.specification_id IS '规格ID，来自ODS规格ID。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.product_id IS '商品ID，来自ODS商品ID。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.product_name IS '商品名称，来自ODS商品名称。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.sku_name IS 'SKU名称，来自ODS SKU名称。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.sku_quantity IS 'SKU件数，来自ODS SKU件数。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.stat_date IS 'GSV统计日期，支付时间优先、订单创建时间兜底。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.stat_date_source IS '统计日期来源：payment_time、creation_time或missing。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.order_created_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.order_paid_at IS '清洗后的支付时间。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.order_status IS '订单状态原枚举；DWD不筛选，DWS仅纳入已完成。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.after_sale_status IS '售后状态原枚举；DWD不筛选，DWS仅纳入无售后。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.merchant_receivable_amount IS '商家应收金额（支付金额），SKU行级金额，单位元，为当前GSV公式金额。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.shop_discount_amount IS '店铺优惠，SKU行级金额，单位元，仅用于审计，不参与当前GSV公式。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.user_payable_amount IS '用户应付金额，SKU行级金额，单位元，仅用于审计。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.platform_discount_amount IS '平台优惠，SKU行级金额，单位元，仅用于审计。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_id IS '对应ODS原始记录主键ID，与平台编码组成DWD主键。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_batch_id IS '对应ODS导入批次ID，用于关联批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_file_name IS '对应ODS来源文件名。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_sheet_name IS '对应ODS来源Sheet名。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_row_no IS '对应ODS来源文件行号。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.source_updated_at IS '对应ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_xhs_gsv_order_item_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_xhs_gsv_stat_date ON dwd.dwd_xhs_gsv_order_item_detail (stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_gsv_shop_date ON dwd.dwd_xhs_gsv_order_item_detail (shop_code, stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_xhs_gsv_order_no ON dwd.dwd_xhs_gsv_order_item_detail (order_no);
