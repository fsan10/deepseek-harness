CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_pdd_gsv_order_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'pdd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '拼多多',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    order_no VARCHAR(128) NOT NULL,

    stat_date DATE,
    order_deal_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),

    merchant_received_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    store_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    user_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,

    source_id BIGINT NOT NULL,
    source_batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128),
    source_row_no INTEGER,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, order_no),
    CONSTRAINT ck_dwd_pdd_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

ALTER TABLE dwd.dwd_pdd_gsv_order_detail
    ADD COLUMN IF NOT EXISTS shop_identity_key VARCHAR(161);
ALTER TABLE dwd.dwd_pdd_gsv_order_detail
    DROP CONSTRAINT IF EXISTS ck_dwd_pdd_gsv_shop_code_source;
UPDATE dwd.dwd_pdd_gsv_order_detail
SET shop_code_source = 'batch_context'
WHERE shop_code_source IS DISTINCT FROM 'batch_context';
ALTER TABLE dwd.dwd_pdd_gsv_order_detail
    ADD CONSTRAINT ck_dwd_pdd_gsv_shop_code_source CHECK (shop_code_source = 'batch_context');

COMMENT ON TABLE dwd.dwd_pdd_gsv_order_detail IS '拼多多GSV订单明细表，一个订单一行；只做字段清洗与已确认DIM店铺归属，不执行订单或售后状态筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.platform_code IS '平台编码，拼多多固定为pdd。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.platform_name IS '平台名称，拼多多固定为拼多多。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.shop_code IS '标准店铺编码，通过ODS批次ID关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.shop_name IS '标准店铺名称，来自dim.dim_platform_shop_company，当前为养颜轻食。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.shop_code_source IS '店铺编码来源，固定为batch_context，表示来自已确认的导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.shop_identity_key IS '稳定店铺身份键，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.order_no IS '拼多多订单号，为本DWD最小粒度标识。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.stat_date IS 'GSV统计日期，取订单成交时间的日期部分，无兜底字段。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.order_deal_at IS '清洗后的订单成交时间。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.order_status IS '订单状态原枚举；DWD保留原值，不在本层筛选。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.after_sale_status IS '售后状态原枚举；DWD不筛选，DWS仅纳入无售后或售后取消。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.merchant_received_amount IS '清洗后的商家实收金额，单位元，为拼多多GSV公式金额。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.store_discount_amount IS '清洗后的店铺优惠折扣，单位元，仅用于审计，不参与当前GSV公式。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.user_paid_amount IS '清洗后的用户实付金额，单位元，仅用于核对，不参与已确认GSV公式。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_id IS '对应ODS原始记录的主键ID。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_batch_id IS '对应ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_file_name IS '对应ODS来源文件名。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_sheet_name IS '对应ODS来源Sheet名。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_row_no IS '对应ODS来源文件行号。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.source_updated_at IS '对应ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_pdd_gsv_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_gsv_stat_date
    ON dwd.dwd_pdd_gsv_order_detail (stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_pdd_gsv_shop_date
    ON dwd.dwd_pdd_gsv_order_detail (shop_code, stat_date);
