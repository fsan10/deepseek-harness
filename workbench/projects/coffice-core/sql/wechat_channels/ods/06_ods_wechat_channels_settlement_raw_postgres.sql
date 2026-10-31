CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_wechat_channels_settlement_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "流水单号" VARCHAR(128),
    "记账时间" VARCHAR(64),
    "动帐类型" VARCHAR(128),
    "收支类型" VARCHAR(64),
    "收支金额" VARCHAR(64),
    "账户余额" VARCHAR(64),
    "关联订单号" VARCHAR(128),
    "关联售后单号" VARCHAR(128),
    "关联提现单号" VARCHAR(128),
    "关联保单号" VARCHAR(128),
    "关联礼物单号" VARCHAR(128),
    "详情" TEXT,

    CONSTRAINT uk_ods_wechat_channels_settlement_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_wechat_channels_settlement_raw
SET source_sheet_name = 'CSV'
WHERE source_sheet_name IS NULL OR source_sheet_name = '';

ALTER TABLE ods.ods_wechat_channels_settlement_raw
    ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';

ALTER TABLE ods.ods_wechat_channels_settlement_raw
    ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_settlement_batch_id ON ods.ods_wechat_channels_settlement_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_settlement_flow_no ON ods.ods_wechat_channels_settlement_raw ("流水单号");
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_settlement_order_no ON ods.ods_wechat_channels_settlement_raw ("关联订单号");
CREATE INDEX IF NOT EXISTS idx_ods_wechat_channels_settlement_source_file ON ods.ods_wechat_channels_settlement_raw (source_file_name);

COMMENT ON TABLE ods.ods_wechat_channels_settlement_raw IS 'ODS视频号动账流水原始表';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.source_sheet_name IS '来源工作表';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."流水单号" IS '来源文件字段“流水单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."记账时间" IS '来源文件字段“记账时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."动帐类型" IS '来源文件字段“动帐类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."收支类型" IS '来源文件字段“收支类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."收支金额" IS '来源文件字段“收支金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."账户余额" IS '来源文件字段“账户余额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."关联订单号" IS '来源文件字段“关联订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."关联售后单号" IS '来源文件字段“关联售后单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."关联提现单号" IS '来源文件字段“关联提现单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."关联保单号" IS '来源文件字段“关联保单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."关联礼物单号" IS '来源文件字段“关联礼物单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_wechat_channels_settlement_raw."详情" IS '来源文件字段“详情”，保留平台导出的原始值。';
