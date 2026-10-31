DROP TABLE IF EXISTS ods.ods_tmall_order_raw_next;

CREATE TABLE ods.ods_tmall_order_raw_next (
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

    CONSTRAINT uk_ods_tmall_order_raw_next_row_hash UNIQUE (row_hash)
);

CREATE INDEX idx_ods_tmall_order_raw_next_sub_order_no
    ON ods.ods_tmall_order_raw_next ("子订单编号");
CREATE INDEX idx_ods_tmall_order_raw_next_main_order_no
    ON ods.ods_tmall_order_raw_next ("主订单编号");
CREATE INDEX idx_ods_tmall_order_raw_next_source_file
    ON ods.ods_tmall_order_raw_next (source_file_name);
CREATE INDEX idx_ods_tmall_order_raw_next_batch_id
    ON ods.ods_tmall_order_raw_next (batch_id);

COMMENT ON TABLE ods.ods_tmall_order_raw_next IS '天猫宝贝销售明细ODS迁移暂存表；历史覆盖验收通过后原子切换为ods.ods_tmall_order_raw。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.id IS '暂存ODS自增主键。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.batch_id IS '新格式文件导入批次ID；切换后通过导入日志解析标准店铺。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.source_file_name IS '来源销售明细文件名。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.source_sheet_name IS '来源工作表名称或CSV。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.row_hash IS '保留字段与文件、工作表、行号共同计算的SHA256。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next.ingest_time IS '记录写入迁移暂存表的审计时间。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."子订单编号" IS '天猫子订单编号。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."主订单编号" IS '天猫主订单编号。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."商品标题" IS '平台商品标题。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."购买数量" IS '来源购买数量文本。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."商品属性" IS '来源商品规格属性。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."订单状态" IS '来源订单状态原枚举。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."商家编码" IS '来源商家编码。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."买家应付货款" IS '来源子订单买家应付货款文本，单位元。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."买家实付金额" IS '来源子订单买家实付金额文本，单位元。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."退款状态" IS '来源退款状态原枚举；天猫GSV排除退款成功。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."退款金额" IS '来源退款金额文本，单位元，仅用于审计。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."订单创建时间" IS '来源订单创建时间。';
COMMENT ON COLUMN ods.ods_tmall_order_raw_next."订单付款时间" IS '来源订单付款时间。';
