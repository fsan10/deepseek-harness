CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_order_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "子订单编号" TEXT,
    "主订单编号" TEXT,
    "商品标题" TEXT,
    "购买数量" TEXT,
    "商品属性" TEXT,
    "订单状态" TEXT,
    "商家编码" TEXT,
    "买家应付货款" TEXT,
    "买家实付金额" TEXT,
    "退款状态" TEXT,
    "退款金额" TEXT,
    "订单创建时间" TEXT,
    "订单付款时间" TEXT,

    CONSTRAINT uk_ods_tmall_order_row_hash UNIQUE (row_hash)
);

ALTER TABLE ods.ods_tmall_order_raw
    ADD COLUMN IF NOT EXISTS "退款状态" TEXT;
ALTER TABLE ods.ods_tmall_order_raw
    ADD COLUMN IF NOT EXISTS "退款金额" TEXT;

CREATE INDEX IF NOT EXISTS idx_ods_tmall_order_sub_order_no
    ON ods.ods_tmall_order_raw ("子订单编号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_order_main_order_no
    ON ods.ods_tmall_order_raw ("主订单编号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_order_source_file
    ON ods.ods_tmall_order_raw (source_file_name);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_order_batch_id
    ON ods.ods_tmall_order_raw (batch_id);

COMMENT ON TABLE ods.ods_tmall_order_raw IS '天猫宝贝销售明细ODS，一行一个来源子订单版本；保存当前GSV、运营、产品和达人指标需要的13个业务字段及导入审计字段。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.id IS 'ODS自增主键，仅用于单行追溯。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.batch_id IS '导入批次ID，必须关联ods.ods_file_ingest_log取得标准平台和店铺上下文。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.source_file_name IS '来源销售明细文件名。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.source_sheet_name IS '来源工作表名称；CSV固定为CSV。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.source_row_no IS '来源文件原始行号，从表头下一行开始计数。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.row_hash IS '保留字段与文件、工作表、原始行号共同计算的SHA256，用于文件行幂等。';
COMMENT ON COLUMN ods.ods_tmall_order_raw.ingest_time IS '该来源版本写入ODS的审计时间。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."子订单编号" IS '天猫子订单编号；标准店铺加子订单编号构成DWD最新版本业务键。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."主订单编号" IS '天猫主订单编号；用于成交订单去重和大于2000元刷单整单排除。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."商品标题" IS '平台商品标题；用于识别达人专属/推荐商品、MOCK推荐官和赠品勿拍辅助行。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."购买数量" IS '来源购买数量文本；正GMV有效商品行用于计算成交件数。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."商品属性" IS '来源商品规格属性；产品分摊用于识别“赠”字后的赠品编码组件。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."订单状态" IS '来源订单状态原枚举；DWD不筛选，DWS使用交易关闭计算退款或排除GSV。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."商家编码" IS '来源商家编码；支持加号组合编码并映射公司统一产品及分类。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."买家应付货款" IS '来源子订单买家应付货款文本；运营、产品和达人GMV及退款采用该金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."买家实付金额" IS '来源子订单买家实付金额文本；天猫GSV采用该金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."退款状态" IS '平台导出的退款状态原枚举；当前为没有申请退款或退款成功，天猫GSV在DWS排除退款成功。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."退款金额" IS '平台导出的退款金额原值；无申请时为无退款申请，其他值为元金额，仅用于GSV退款筛选审计。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."订单创建时间" IS '来源订单创建时间；运营、达人和补零指标取其自然日。';
COMMENT ON COLUMN ods.ods_tmall_order_raw."订单付款时间" IS '来源订单付款时间；GSV日期优先使用，缺失时以订单创建时间兜底。';
