CREATE SCHEMA IF NOT EXISTS dwd;
CREATE SCHEMA IF NOT EXISTS dws;

DROP TABLE IF EXISTS dwd.dwd_tmall_influencer_sales_order_detail;

CREATE TABLE dwd.dwd_tmall_influencer_sales_order_detail (
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    shop_mapping_source VARCHAR(64) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    stat_date DATE NOT NULL,
    order_submitted_at TIMESTAMP NOT NULL,
    order_status VARCHAR(128),
    product_title TEXT,
    influencer_name_raw VARCHAR(255),
    influencer_marker VARCHAR(32),
    product_quantity NUMERIC(18,2) NOT NULL,
    order_pay_amount NUMERIC(18,2) NOT NULL,
    source_id BIGINT NOT NULL,
    source_batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(255),
    source_row_no INTEGER NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (platform_code, shop_code, sub_order_no),
    CONSTRAINT uq_dwd_tmall_influencer_source UNIQUE (source_id)
);

COMMENT ON TABLE dwd.dwd_tmall_influencer_sales_order_detail IS '天猫达人业绩专属DWD，一行一个标准店铺下最新子订单版本；解析标题达人标记并清洗买家应付货款，但不执行达人、刷单或退款筛选。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.shop_code IS '标准店铺编码，通过source_batch_id关联批次店铺上下文取得。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.shop_name IS '标准店铺名称，来自批次店铺上下文。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.shop_identity_key IS '平台与标准店铺组成的稳定身份键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.shop_mapping_source IS '批次店铺映射来源，用于审计。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.main_order_no IS '天猫主订单编号；用于按主订单买家应付合计大于2000元排除刷单。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.sub_order_no IS '天猫子订单编号；标准店铺下作为DWD最小业务键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.stat_date IS '达人业绩统计自然日，取订单创建时间日期。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.order_submitted_at IS '清洗后的订单创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.order_status IS '子订单状态原枚举；DWD不筛选，DWS仅用交易关闭计算退款。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.product_title IS '来源商品标题，用于识别【xxx专属】或【xxx推荐】。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.influencer_name_raw IS '从达人专属或推荐标题中提取的名称原值；未命中时为空。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.influencer_marker IS '标题命中的达人标记类型，枚举为专属或推荐。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.product_quantity IS '来源购买数量清洗值，仅用于审计，不参与天猫达人GMV。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.order_pay_amount IS '来源子订单买家应付货款；作为达人GMV和退款金额，主订单合计用于刷单判断，单位元。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_id IS '所选最新版本对应的天猫ODS自增主键。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_file_name IS '来源销售明细文件名。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_sheet_name IS '来源工作表名称。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.created_at IS 'DWD记录创建时间。';
COMMENT ON COLUMN dwd.dwd_tmall_influencer_sales_order_detail.updated_at IS 'DWD记录最后刷新时间。';

CREATE INDEX idx_dwd_tmall_influencer_date
    ON dwd.dwd_tmall_influencer_sales_order_detail (stat_date);
CREATE INDEX idx_dwd_tmall_influencer_name
    ON dwd.dwd_tmall_influencer_sales_order_detail (influencer_name_raw);
CREATE INDEX idx_dwd_tmall_influencer_main_order
    ON dwd.dwd_tmall_influencer_sales_order_detail (main_order_no);
CREATE INDEX idx_dwd_tmall_influencer_batch
    ON dwd.dwd_tmall_influencer_sales_order_detail (source_batch_id);

DROP TABLE IF EXISTS dws.dws_tmall_influencer_sales_order;

CREATE TABLE dws.dws_tmall_influencer_sales_order (
    stat_date DATE NOT NULL,
    stat_month DATE NOT NULL,
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64) NOT NULL,
    shop_code VARCHAR(128) NOT NULL,
    shop_name VARCHAR(255) NOT NULL,
    main_order_no VARCHAR(128) NOT NULL,
    sub_order_no VARCHAR(128) NOT NULL,
    order_status VARCHAR(128),
    influencer_id VARCHAR(128) NOT NULL,
    influencer_name VARCHAR(255) NOT NULL,
    influencer_key VARCHAR(193) NOT NULL,
    influencer_marker VARCHAR(32) NOT NULL,
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
    CONSTRAINT uq_dws_tmall_influencer_source UNIQUE (source_id),
    CONSTRAINT ck_dws_tmall_influencer_month
        CHECK (stat_month = DATE_TRUNC('month', stat_date)::DATE)
);

COMMENT ON TABLE dws.dws_tmall_influencer_sales_order IS '天猫达人业绩专属DWS，一行一个标题命中且已在配置库映射稳定ID的非刷单子订单；买家应付货款计GMV，交易关闭的同金额计退款。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.stat_date IS '达人业绩自然日，取订单创建日期。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.stat_month IS '订单创建日期所属自然月首日。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.platform_code IS '标准平台编码，固定为tmall。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.platform_name IS '平台展示名称，固定为天猫。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.shop_code IS '标准店铺编码，来自天猫达人DWD。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.shop_name IS '标准店铺名称，来自天猫达人DWD。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.main_order_no IS '天猫主订单编号。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.sub_order_no IS '天猫子订单编号，DWS最小业务键。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.order_status IS '子订单状态；GMV不筛状态，交易关闭计退款。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.influencer_id IS '按规范达人名称从月度归属配置库取得的稳定达人ID。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.influencer_name IS '规范达人名称；加购！胡可统一为胡可。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.influencer_key IS '跨平台达人去重键，格式为tmall|达人ID。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.influencer_marker IS '标题命中的专属或推荐标记。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.order_pay_amount IS '来源子订单买家应付货款，单位元。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.gmv_amount IS '天猫达人GMV，等于买家应付货款且不按订单状态筛选，单位元。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.refund_amount IS '订单状态为交易关闭时取买家应付货款，否则为0，单位元。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.is_closed_refund IS '子订单状态是否为交易关闭。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.included_sub_order_count IS '纳入指标的子订单计数，每行固定为1。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.source_id IS '来源天猫ODS主键。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.source_batch_id IS '来源ODS导入批次ID。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.source_updated_at IS '来源ODS记录入库时间。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.created_at IS 'DWS记录创建时间。';
COMMENT ON COLUMN dws.dws_tmall_influencer_sales_order.updated_at IS 'DWS记录最后刷新时间。';

CREATE INDEX idx_dws_tmall_influencer_date_shop
    ON dws.dws_tmall_influencer_sales_order (stat_date, shop_code);
CREATE INDEX idx_dws_tmall_influencer_month_id
    ON dws.dws_tmall_influencer_sales_order (stat_month, influencer_id);
