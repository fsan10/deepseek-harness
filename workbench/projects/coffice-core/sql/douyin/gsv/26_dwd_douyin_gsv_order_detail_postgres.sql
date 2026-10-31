CREATE SCHEMA IF NOT EXISTS dwd;

CREATE TABLE IF NOT EXISTS dwd.dwd_douyin_gsv_order_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'douyin',
    platform_name VARCHAR(64) NOT NULL DEFAULT '抖音',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(128) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(32) NOT NULL,
    main_order_no VARCHAR(128),
    sub_order_no VARCHAR(128) NOT NULL,

    stat_date DATE,
    order_submitted_at TIMESTAMP,
    payment_completed_at TIMESTAMP,
    order_status VARCHAR(128),
    after_sale_status VARCHAR(128),

    order_pay_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    discount_total_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_actual_discount_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    merchant_discount_source VARCHAR(32) NOT NULL,

    source_id BIGINT NOT NULL,
    source_batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_row_no INTEGER,
    source_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, sub_order_no),
    CONSTRAINT ck_dwd_douyin_gsv_merchant_discount_source
        CHECK (merchant_discount_source IN ('merchant_actual', 'merchant_text', 'default_zero'))
);

ALTER TABLE dwd.dwd_douyin_gsv_order_detail
    ADD COLUMN IF NOT EXISTS shop_identity_key VARCHAR(161),
    ADD COLUMN IF NOT EXISTS shop_mapping_source VARCHAR(32);

COMMENT ON TABLE dwd.dwd_douyin_gsv_order_detail IS '抖音GSV订单明细表，一条子订单一行；只做本指标需要的字段选择和清洗，不执行订单或售后筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.platform_code IS '平台编码，抖音固定为douyin。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.platform_name IS '平台名称，抖音固定为抖音。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.shop_code IS '标准店铺编码，通过ODS批次ID关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.shop_name IS '标准店铺名称，通过ODS批次ID关联统一批次店铺上下文获得。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.shop_identity_key IS '稳定店铺身份键，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.shop_mapping_source IS '店铺映射来源，继承导入日志的人工选择、影刀选择或历史补录方式。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.main_order_no IS '主订单编号，来源于ODS主订单编号。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.sub_order_no IS '子订单编号，作为DWD订单明细最小粒度标识。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.stat_date IS 'GSV统计日期，优先取支付完成日期，缺失时取订单提交日期。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.order_submitted_at IS '清洗后的订单提交时间。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.payment_completed_at IS '清洗后的支付完成时间。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.order_status IS '订单状态；DWD保留原值，不在本层筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.after_sale_status IS '售后状态；DWD保留原值，不在本层筛选。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.order_pay_amount IS '清洗后的订单应付金额，单位元，保留原始正负号。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.discount_total_amount IS '清洗后的优惠总金额，单位元，按绝对值保存。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.merchant_actual_discount_amount IS '商家承担优惠金额，优先取商家实际承担优惠金额，缺失时解析商家优惠，单位元。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.merchant_discount_source IS '商家优惠金额来源：merchant_actual、merchant_text或default_zero。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.source_id IS '对应ODS原始记录的主键ID。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.source_batch_id IS '对应ODS原始记录的导入批次ID。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.source_file_name IS '对应ODS原始记录的来源文件名。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.source_row_no IS '对应ODS原始记录的来源文件行号。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.source_updated_at IS '对应ODS原始记录的入库时间。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_douyin_gsv_order_detail.updated_at IS 'DWD记录最后更新时间。';

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_gsv_stat_date
    ON dwd.dwd_douyin_gsv_order_detail (stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_gsv_shop_date
    ON dwd.dwd_douyin_gsv_order_detail (shop_code, stat_date);

CREATE INDEX IF NOT EXISTS idx_dwd_douyin_gsv_main_order
    ON dwd.dwd_douyin_gsv_order_detail (main_order_no);
