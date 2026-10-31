CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_ks_settlement_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "商家ID" VARCHAR(128),
    "订单号" VARCHAR(128),
    "商品ID" VARCHAR(128),
    "商品名称" TEXT,
    "商品数量" VARCHAR(64),
    "订单创建时间" VARCHAR(64),
    "订单实付(元)" VARCHAR(64),
    "政府补贴" VARCHAR(64),
    "支付营销补贴" VARCHAR(64),
    "平台补贴" VARCHAR(64),
    "商家补贴(元)" VARCHAR(64),
    "达人补贴" VARCHAR(64),
    "达人补贴明细" TEXT,
    "合计收入(元)" VARCHAR(64),
    "订单退款(元)" VARCHAR(64),
    "支付营销回退（元）" VARCHAR(64),
    "技术服务费(元)" VARCHAR(64),
    "预售增收技术服务费（元）" VARCHAR(64),
    "达人ID" VARCHAR(128),
    "MCN机构ID" VARCHAR(128),
    "达人佣金(元)" VARCHAR(64),
    "团长id" VARCHAR(128),
    "团长佣金(元)" VARCHAR(64),
    "佣金模式" VARCHAR(128),
    "快赚客ID" VARCHAR(128),
    "快赚客佣金(元)" VARCHAR(64),
    "服务商ID" VARCHAR(128),
    "服务商佣金(元)" VARCHAR(64),
    "分账基数" VARCHAR(64),
    "其他收费" VARCHAR(64),
    "其他收费明细" TEXT,
    "合计支出(元)" VARCHAR(64),
    "实际结算金额(元)" VARCHAR(64),
    "实际结算时间" VARCHAR(64),
    "结算规则" TEXT,
    "资金渠道" VARCHAR(128),
    "账户名称" VARCHAR(255),
    "结算商户号" VARCHAR(128),
    "备注" TEXT,
    "消费金信息" TEXT,
    "运费" VARCHAR(64),

    CONSTRAINT uk_ods_ks_settlement_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_ks_settlement_raw
SET source_sheet_name = 'CSV'
WHERE source_sheet_name IS NULL OR source_sheet_name = '';

ALTER TABLE ods.ods_ks_settlement_raw
    ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';

ALTER TABLE ods.ods_ks_settlement_raw
    ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_ks_settlement_batch_id ON ods.ods_ks_settlement_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_ks_settlement_order_no ON ods.ods_ks_settlement_raw ("订单号");
CREATE INDEX IF NOT EXISTS idx_ods_ks_settlement_product_id ON ods.ods_ks_settlement_raw ("商品ID");
CREATE INDEX IF NOT EXISTS idx_ods_ks_settlement_kol_id ON ods.ods_ks_settlement_raw ("达人ID");
CREATE INDEX IF NOT EXISTS idx_ods_ks_settlement_source_file ON ods.ods_ks_settlement_raw (source_file_name);

COMMENT ON TABLE ods.ods_ks_settlement_raw IS 'ODS快手结算单原始表';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.source_sheet_name IS '来源工作表';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_ks_settlement_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."商家ID" IS '来源文件字段“商家ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."商品数量" IS '来源文件字段“商品数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."订单创建时间" IS '来源文件字段“订单创建时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."订单实付(元)" IS '来源文件字段“订单实付(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."政府补贴" IS '来源文件字段“政府补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."支付营销补贴" IS '来源文件字段“支付营销补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."平台补贴" IS '来源文件字段“平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."商家补贴(元)" IS '来源文件字段“商家补贴(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."达人补贴" IS '来源文件字段“达人补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."达人补贴明细" IS '来源文件字段“达人补贴明细”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."合计收入(元)" IS '来源文件字段“合计收入(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."订单退款(元)" IS '来源文件字段“订单退款(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."支付营销回退（元）" IS '来源文件字段“支付营销回退（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."技术服务费(元)" IS '来源文件字段“技术服务费(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."预售增收技术服务费（元）" IS '来源文件字段“预售增收技术服务费（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."达人ID" IS '来源文件字段“达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."MCN机构ID" IS '来源文件字段“MCN机构ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."达人佣金(元)" IS '来源文件字段“达人佣金(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."团长id" IS '来源文件字段“团长id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."团长佣金(元)" IS '来源文件字段“团长佣金(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."佣金模式" IS '来源文件字段“佣金模式”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."快赚客ID" IS '来源文件字段“快赚客ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."快赚客佣金(元)" IS '来源文件字段“快赚客佣金(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."服务商ID" IS '来源文件字段“服务商ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."服务商佣金(元)" IS '来源文件字段“服务商佣金(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."分账基数" IS '来源文件字段“分账基数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."其他收费" IS '来源文件字段“其他收费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."其他收费明细" IS '来源文件字段“其他收费明细”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."合计支出(元)" IS '来源文件字段“合计支出(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."实际结算金额(元)" IS '来源文件字段“实际结算金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."实际结算时间" IS '来源文件字段“实际结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."结算规则" IS '来源文件字段“结算规则”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."资金渠道" IS '来源文件字段“资金渠道”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."账户名称" IS '来源文件字段“账户名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."结算商户号" IS '来源文件字段“结算商户号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."消费金信息" IS '来源文件字段“消费金信息”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_ks_settlement_raw."运费" IS '来源文件字段“运费”，保留平台导出的原始值。';
