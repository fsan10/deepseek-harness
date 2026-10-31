CREATE SCHEMA IF NOT EXISTS dwd;

DROP TABLE IF EXISTS dwd.dwd_tmall_gsv_order_detail;

CREATE TABLE dwd.dwd_tmall_gsv_order_detail (
    platform_code VARCHAR(32) NOT NULL DEFAULT 'tmall',
    platform_name VARCHAR(64) NOT NULL DEFAULT '天猫',
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_code_source VARCHAR(32) NOT NULL DEFAULT 'batch_context',
    shop_identity_key VARCHAR(161) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    product_title TEXT,
    stat_date DATE,
    stat_date_source VARCHAR(32) NOT NULL,
    order_created_at TIMESTAMP,
    order_paid_at TIMESTAMP,
    order_status VARCHAR(128),
    refund_status VARCHAR(128),
    refund_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    buyer_paid_amount NUMERIC(18,2) NOT NULL DEFAULT 0,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128),
    source_row_no INTEGER,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dwd_tmall_gsv_source UNIQUE (source_id),
    CONSTRAINT ck_dwd_tmall_gsv_stat_date_source
        CHECK (stat_date_source IN ('payment_time', 'creation_time', 'missing')),
    CONSTRAINT ck_dwd_tmall_gsv_shop_code_source
        CHECK (shop_code_source = 'batch_context')
);

COMMENT ON TABLE dwd.dwd_tmall_gsv_order_detail IS '天猫GSV专属DWD，一行一个标准店铺下最新子订单版本；只清洗字段、解析日期金额和关联批次店铺，不执行订单、退款状态或商品标题筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.shop_code IS '标准店铺编码，通过source_batch_id关联统一批次店铺上下文取得。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.shop_name IS '标准店铺名称，来自统一批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.shop_code_source IS '店铺编码来源，固定为batch_context。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.shop_identity_key IS '平台与店铺组成的稳定身份键，来自统一批次上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.main_order_no IS '天猫主订单编号；DWS用于统计纳入GSV的唯一主订单数。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.sub_order_no IS '天猫子订单编号；标准店铺下作为DWD最小业务键。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.product_title IS '商品标题原值；DWD不筛选，DWS排除标题包含购物金的子订单。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.stat_date IS 'GSV统计日期，订单付款时间优先、订单创建时间兜底。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.stat_date_source IS '统计日期来源：payment_time付款时间、creation_time创建时间兜底或missing。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.order_created_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.order_paid_at IS '清洗后的订单付款时间。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.order_status IS '子订单状态原枚举；DWD不筛选，DWS排除交易关闭。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.refund_status IS '退款状态原枚举，来源ODS退款状态；DWD不筛选，DWS排除退款成功。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.refund_amount IS '清洗后的退款金额，来源ODS退款金额；无退款申请按0处理，单位元，仅用于筛选审计。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.buyer_paid_amount IS '清洗后的子订单买家实付金额；空值按0处理，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_id IS '所选最新版本对应的ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_file_name IS '来源销售明细文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_sheet_name IS '来源工作表名称。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_gsv_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX idx_dwd_tmall_gsv_stat_date
    ON dwd.dwd_tmall_gsv_order_detail (stat_date);
CREATE INDEX idx_dwd_tmall_gsv_shop_date
    ON dwd.dwd_tmall_gsv_order_detail (shop_code, stat_date);
CREATE INDEX idx_dwd_tmall_gsv_main_order
    ON dwd.dwd_tmall_gsv_order_detail (main_order_no);
CREATE INDEX idx_dwd_tmall_gsv_source_batch
    ON dwd.dwd_tmall_gsv_order_detail (source_batch_id);
