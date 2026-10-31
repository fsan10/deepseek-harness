CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_jd_settlement_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单编号" VARCHAR(128),
    "单据编号" VARCHAR(128),
    "单据类型" VARCHAR(128),
    "商品编号" VARCHAR(128),
    "商户订单号" VARCHAR(128),
    "商品名称" TEXT,
    "费用发生时间" VARCHAR(64),
    "费用计费时间" VARCHAR(64),
    "费用结算时间" VARCHAR(64),
    "费用项" VARCHAR(128),
    "金额" VARCHAR(64),
    "币种" VARCHAR(32),
    "商家应收/应付" VARCHAR(64),
    "钱包结算备注" TEXT,
    "店铺号" VARCHAR(128),
    "京东门店编号" VARCHAR(128),
    "品牌门店编号" VARCHAR(128),
    "门店名称" VARCHAR(255),
    "备注" TEXT,
    "收支方向" VARCHAR(64),
    "账单日期" VARCHAR(64),
    "商品数量" VARCHAR(64),

    CONSTRAINT uk_ods_jd_settlement_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_jd_settlement_raw
SET source_sheet_name = 'CSV'
WHERE source_sheet_name IS NULL OR source_sheet_name = '';

ALTER TABLE ods.ods_jd_settlement_raw
    ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';

ALTER TABLE ods.ods_jd_settlement_raw
    ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_jd_settlement_batch_id ON ods.ods_jd_settlement_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_jd_settlement_order_no ON ods.ods_jd_settlement_raw ("订单编号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_settlement_doc_no ON ods.ods_jd_settlement_raw ("单据编号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_settlement_product_id ON ods.ods_jd_settlement_raw ("商品编号");
CREATE INDEX IF NOT EXISTS idx_ods_jd_settlement_source_file ON ods.ods_jd_settlement_raw (source_file_name);

COMMENT ON TABLE ods.ods_jd_settlement_raw IS 'ODS京东结算单原始表';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.source_sheet_name IS '来源工作表；CSV固定写CSV';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.row_hash IS '行级SHA256，用于幂等去重';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."账单日期" IS '账单日期；按天导出文件如无此列，由导入脚本补充';

COMMENT ON COLUMN ods.ods_jd_settlement_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."订单编号" IS '来源文件字段“订单编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."单据编号" IS '来源文件字段“单据编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."单据类型" IS '来源文件字段“单据类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."商品编号" IS '来源文件字段“商品编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."商户订单号" IS '来源文件字段“商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."费用发生时间" IS '来源文件字段“费用发生时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."费用计费时间" IS '来源文件字段“费用计费时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."费用结算时间" IS '来源文件字段“费用结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."费用项" IS '来源文件字段“费用项”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."金额" IS '来源文件字段“金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."币种" IS '来源文件字段“币种”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."商家应收/应付" IS '来源文件字段“商家应收/应付”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."钱包结算备注" IS '来源文件字段“钱包结算备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."店铺号" IS '来源文件字段“店铺号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."京东门店编号" IS '来源文件字段“京东门店编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."品牌门店编号" IS '来源文件字段“品牌门店编号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."门店名称" IS '来源文件字段“门店名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."收支方向" IS '来源文件字段“收支方向”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_jd_settlement_raw."商品数量" IS '来源文件字段“商品数量”，保留平台导出的原始值。';
