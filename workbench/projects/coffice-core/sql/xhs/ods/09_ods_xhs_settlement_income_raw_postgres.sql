CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_xhs_settlement_income_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "订单号" VARCHAR(128),
    "售后单号" VARCHAR(128),
    "下单时间" VARCHAR(64),
    "完成时间" VARCHAR(64),
    "结算时间" VARCHAR(64),
    "交易类型" VARCHAR(128),
    "动账金额" VARCHAR(64),
    "结算账户" VARCHAR(128),
    "计佣基数" VARCHAR(64),
    "商品实付/实退" VARCHAR(64),
    "运费实付/实退" VARCHAR(64),
    "商家优惠总额" VARCHAR(64),
    "平台优惠补贴" VARCHAR(64),
    "政府券优惠补贴" VARCHAR(64),
    "平台佣金" VARCHAR(64),
    "买手佣金" VARCHAR(64),
    "花呗分期手续费" VARCHAR(64),

    CONSTRAINT uk_ods_xhs_settlement_income_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_xhs_settlement_income_raw SET source_sheet_name = 'CSV' WHERE source_sheet_name IS NULL OR source_sheet_name = '';
ALTER TABLE ods.ods_xhs_settlement_income_raw ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';
ALTER TABLE ods.ods_xhs_settlement_income_raw ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_xhs_income_batch_id ON ods.ods_xhs_settlement_income_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_xhs_income_order_no ON ods.ods_xhs_settlement_income_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_income_after_sale_no ON ods.ods_xhs_settlement_income_raw ("售后单号");
CREATE INDEX IF NOT EXISTS idx_ods_xhs_income_source_file ON ods.ods_xhs_settlement_income_raw (source_file_name);

COMMENT ON TABLE ods.ods_xhs_settlement_income_raw IS 'ODS小红书结算收入/订单结算原始表';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.source_sheet_name IS '来源工作表';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."售后单号" IS '来源文件字段“售后单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."下单时间" IS '来源文件字段“下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."完成时间" IS '来源文件字段“完成时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."结算时间" IS '来源文件字段“结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."交易类型" IS '来源文件字段“交易类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."动账金额" IS '来源文件字段“动账金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."结算账户" IS '来源文件字段“结算账户”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."计佣基数" IS '来源文件字段“计佣基数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."商品实付/实退" IS '来源文件字段“商品实付/实退”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."运费实付/实退" IS '来源文件字段“运费实付/实退”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."商家优惠总额" IS '来源文件字段“商家优惠总额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."平台优惠补贴" IS '来源文件字段“平台优惠补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."政府券优惠补贴" IS '来源文件字段“政府券优惠补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."平台佣金" IS '来源文件字段“平台佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."买手佣金" IS '来源文件字段“买手佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_xhs_settlement_income_raw."花呗分期手续费" IS '来源文件字段“花呗分期手续费”，保留平台导出的原始值。';
