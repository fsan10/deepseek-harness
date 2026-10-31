CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_douyin_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "动账时间" VARCHAR(64),
    "动帐流水号" VARCHAR(128),
    "动账方向" VARCHAR(64),
    "动账金额" VARCHAR(64),
    "动账账户" VARCHAR(128),
    "动账场景" VARCHAR(128),
    "计费类型" VARCHAR(128),
    "子订单号" VARCHAR(128),
    "订单号" VARCHAR(128),
    "售后编号" VARCHAR(128),
    "下单时间" VARCHAR(64),
    "商品ID" VARCHAR(128),
    "商品名称" TEXT,
    "达人ID" VARCHAR(128),
    "达人名称" VARCHAR(255),
    "订单类型" VARCHAR(128),
    "订单实付应结" VARCHAR(64),
    "运费实付" VARCHAR(64),
    "实际平台补贴_运费" VARCHAR(64),
    "实际平台补贴" VARCHAR(64),
    "其他平台补贴" VARCHAR(64),
    "以旧换新抵扣" VARCHAR(64),
    "政府补贴平台垫资" VARCHAR(64),
    "实际达人补贴" VARCHAR(64),
    "实际抖音支付补贴" VARCHAR(64),
    "实际抖音月付营销补贴" VARCHAR(64),
    "银行补贴" VARCHAR(64),
    "订单退款" VARCHAR(64),
    "平台服务费" VARCHAR(64),
    "佣金" VARCHAR(64),
    "服务商佣金" VARCHAR(64),
    "渠道分成" VARCHAR(64),
    "招商服务费" VARCHAR(64),
    "站外推广费" VARCHAR(64),
    "其他分成" VARCHAR(64),
    "是否免佣" TEXT,
    "免佣金额" VARCHAR(64),
    "商户主体名称" VARCHAR(255),
    "备注" TEXT,

    CONSTRAINT uk_ods_douyin_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_flow_no
    ON ods.ods_douyin_fund_raw ("动帐流水号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_order_no
    ON ods.ods_douyin_fund_raw ("订单号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_sub_order_no
    ON ods.ods_douyin_fund_raw ("子订单号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_product_id
    ON ods.ods_douyin_fund_raw ("商品ID");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_source_file
    ON ods.ods_douyin_fund_raw (source_file_name);

CREATE INDEX IF NOT EXISTS idx_ods_douyin_fund_batch_id
    ON ods.ods_douyin_fund_raw (batch_id);

COMMENT ON TABLE ods.ods_douyin_fund_raw IS 'ODS抖音资金流水原始表，按源文件表头原样保存。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.batch_id IS '导入批次ID，可关联ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.source_sheet_name IS '来源Sheet名，CSV固定为CSV';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_douyin_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动账时间" IS '来源文件字段“动账时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动帐流水号" IS '来源文件字段“动帐流水号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动账方向" IS '来源文件字段“动账方向”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动账金额" IS '来源文件字段“动账金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动账账户" IS '来源文件字段“动账账户”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."动账场景" IS '来源文件字段“动账场景”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."计费类型" IS '来源文件字段“计费类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."子订单号" IS '来源文件字段“子订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."售后编号" IS '来源文件字段“售后编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."下单时间" IS '来源文件字段“下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."达人ID" IS '来源文件字段“达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."达人名称" IS '来源文件字段“达人名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."订单类型" IS '来源文件字段“订单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."订单实付应结" IS '来源文件字段“订单实付应结”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."运费实付" IS '来源文件字段“运费实付”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."实际平台补贴_运费" IS '来源文件字段“实际平台补贴_运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."实际平台补贴" IS '来源文件字段“实际平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."其他平台补贴" IS '来源文件字段“其他平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."以旧换新抵扣" IS '来源文件字段“以旧换新抵扣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."政府补贴平台垫资" IS '来源文件字段“政府补贴平台垫资”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."实际达人补贴" IS '来源文件字段“实际达人补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."实际抖音支付补贴" IS '来源文件字段“实际抖音支付补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."实际抖音月付营销补贴" IS '来源文件字段“实际抖音月付营销补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."银行补贴" IS '来源文件字段“银行补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."订单退款" IS '来源文件字段“订单退款”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."平台服务费" IS '来源文件字段“平台服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."佣金" IS '来源文件字段“佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."服务商佣金" IS '来源文件字段“服务商佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."渠道分成" IS '来源文件字段“渠道分成”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."招商服务费" IS '来源文件字段“招商服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."站外推广费" IS '来源文件字段“站外推广费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."其他分成" IS '来源文件字段“其他分成”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."是否免佣" IS '来源文件字段“是否免佣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."免佣金额" IS '来源文件字段“免佣金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."商户主体名称" IS '来源文件字段“商户主体名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_fund_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
