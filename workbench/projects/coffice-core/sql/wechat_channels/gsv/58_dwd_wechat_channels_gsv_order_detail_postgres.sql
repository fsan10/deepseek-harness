CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_wechat_channels_gsv_order_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'wechat_channels',
    platform_name VARCHAR(64) NOT NULL DEFAULT '视频号',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL,
    order_no VARCHAR(128) NOT NULL,
    stat_date DATE,
    stat_date_source VARCHAR(32) NOT NULL,
    order_created_at TIMESTAMP,
    order_paid_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_statuses TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    actual_received_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    activity_merchant_subsidy_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    actual_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    platform_coupon_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    refunded_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
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
    CONSTRAINT ck_dwd_wechat_channels_gsv_stat_date_source
        CHECK (stat_date_source IN ('payment_time', 'order_time', 'missing')),
    CONSTRAINT ck_dwd_wechat_channels_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

COMMENT ON TABLE dwd.dwd_wechat_channels_gsv_order_detail IS '视频号GSV订单明细表，一个订单一行；按订单号及最新导入批次聚合源商品行，不执行订单或售后状态筛选。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.platform_code IS '平台编码，视频号固定为wechat_channels。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.platform_name IS '平台名称，固定为视频号。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.shop_code IS '标准店铺编码，通过订单最新导入批次关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.shop_name IS '标准店铺名称，来自已确认的批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.shop_identity_key IS '稳定店铺身份键，来自common.v_ingest_batch_shop_context。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.shop_code_source IS '店铺编码来源，固定为batch_context。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.order_no IS '视频号订单号，为本DWD最小业务粒度标识。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.stat_date IS 'GSV统计日期，支付时间优先、订单下单时间兜底。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.stat_date_source IS '统计日期来源：payment_time、order_time或missing。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.order_created_at IS '清洗后的订单下单时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.order_paid_at IS '清洗后的支付时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.order_status IS '订单状态原枚举；DWD保留原值，DWS仅纳入已完成。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.after_sale_statuses IS '订单全部商品行去重后的商品售后状态数组；DWD不执行售后筛选。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.actual_received_amount IS '订单实际收款金额，单位元；订单级字段在多商品行重复，每单只取一次。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.activity_merchant_subsidy_amount IS '订单各商品行活动商家补贴之和，单位元，仅用于审计，不参与当前GSV公式。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.actual_paid_amount IS '订单实际支付金额，单位元；订单级字段每单只取一次，用于审计。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.platform_coupon_amount IS '订单各商品行商品平台券优惠之和，单位元，用于审计。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.refunded_amount IS '订单各商品行商品已退款金额之和，单位元，用于审计筛选结果。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_line_count IS '本订单在最新ODS批次中对应的商品明细行数。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_ids IS '本订单最新批次的全部ODS主键ID数组。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_batch_ids IS '本订单对应的ODS导入批次ID数组。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_file_names IS '本订单对应的ODS来源文件名数组。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_sheet_names IS '本订单对应的ODS来源Sheet名数组。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_row_nos IS '本订单对应的ODS来源文件行号数组。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.source_updated_at IS '本订单参与聚合的ODS记录最晚入库时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_wechat_channels_gsv_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_gsv_stat_date
    ON dwd.dwd_wechat_channels_gsv_order_detail (stat_date);
CREATE INDEX IF NOT EXISTS idx_dwd_wechat_channels_gsv_shop_date
    ON dwd.dwd_wechat_channels_gsv_order_detail (shop_code, stat_date);
