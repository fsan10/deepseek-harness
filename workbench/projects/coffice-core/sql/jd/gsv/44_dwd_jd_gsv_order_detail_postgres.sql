CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_jd_gsv_order_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'jd',
    platform_name VARCHAR(64) NOT NULL DEFAULT '京东',
    source_fulfillment_shop_code VARCHAR(128),
    source_order_shop_code VARCHAR(128),
    source_shop_name VARCHAR(255),
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    order_no VARCHAR(128) NOT NULL,

    stat_date DATE,
    stat_date_source VARCHAR(32) NOT NULL,
    order_created_at TIMESTAMP,
    payment_confirmed_at TIMESTAMP,
    order_status VARCHAR(128),
    order_type VARCHAR(128),

    payable_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    order_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_receivable_amount NUMERIC(18,2) NOT NULL DEFAULT 0,

    source_line_count INTEGER NOT NULL,
    source_ids BIGINT[] NOT NULL,
    source_batch_ids BIGINT[] NOT NULL,
    source_file_names TEXT[] NOT NULL,
    source_sheet_names TEXT[] NOT NULL,
    source_row_nos INTEGER[] NOT NULL,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, order_no),
    CONSTRAINT ck_dwd_jd_gsv_stat_date_source
        CHECK (stat_date_source IN ('payment_confirmation_time', 'order_time', 'missing')),
    CONSTRAINT ck_dwd_jd_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

ALTER TABLE dwd.dwd_jd_gsv_order_detail
    ADD COLUMN IF NOT EXISTS shop_identity_key VARCHAR(161);
ALTER TABLE dwd.dwd_jd_gsv_order_detail
    DROP CONSTRAINT IF EXISTS ck_dwd_jd_gsv_shop_code_source;
UPDATE dwd.dwd_jd_gsv_order_detail
SET shop_code_source = 'batch_context'
WHERE shop_code_source IS DISTINCT FROM 'batch_context';
ALTER TABLE dwd.dwd_jd_gsv_order_detail
    ADD CONSTRAINT ck_dwd_jd_gsv_shop_code_source CHECK (shop_code_source = 'batch_context');

COMMENT ON TABLE dwd.dwd_jd_gsv_order_detail IS '京东GSV订单明细表，一个订单一行；对源商品行按订单号及最新导入批次去重，不执行订单状态筛选。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.platform_code IS '平台编码，京东固定为jd。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.platform_name IS '平台名称，京东固定为京东。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_fulfillment_shop_code IS '来源ODS履约门店ID原值，用于追溯店铺字段。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_order_shop_code IS '来源ODS下单门店Id原值，用于追溯店铺字段。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_shop_name IS '来源ODS门店名称原值。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.shop_code IS '标准店铺编码，通过订单最新导入批次关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.shop_name IS '标准店铺名称，来自dim.dim_platform_shop_company。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.shop_code_source IS '店铺编码来源，固定为batch_context，表示来自已确认的导入批次上下文。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.shop_identity_key IS '稳定店铺身份键，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.order_no IS '京东订单号，为本DWD最小粒度标识。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.stat_date IS 'GSV统计日期，优先取付款确认时间，缺失时取下单时间。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.stat_date_source IS '统计日期来源：payment_confirmation_time、order_time或missing。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.order_created_at IS '清洗后的下单时间。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.payment_confirmed_at IS '清洗后的付款确认时间。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.order_status IS '订单状态原枚举；DWD保留原值，不在本层排除删除状态。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.order_type IS '订单类型，来自ODS订单类型。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.payable_amount IS '清洗后的应付金额，单位元，为京东GSV公式金额。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.order_amount IS '清洗后的订单金额，单位元，仅用于与应付金额核对。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.merchant_receivable_amount IS '清洗后的商家应收，单位元，可解析带系统说明的文本，仅用于核对。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_line_count IS '本订单在最新ODS批次中对应的商品明细行数。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_ids IS '本订单最新批次的全部ODS主键ID数组，用于完整追溯多商品行。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_batch_ids IS '本订单对应的ODS导入批次ID数组。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_file_names IS '本订单对应的ODS来源文件名数组。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_sheet_names IS '本订单对应的ODS来源Sheet名数组。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_row_nos IS '本订单对应的ODS来源文件行号数组。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.source_updated_at IS '本订单参与聚合的ODS记录最晚入库时间。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_jd_gsv_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_jd_gsv_stat_date
    ON dwd.dwd_jd_gsv_order_detail (stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_jd_gsv_shop_date
    ON dwd.dwd_jd_gsv_order_detail (shop_code, stat_date);
