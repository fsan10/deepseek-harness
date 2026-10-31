CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_douyin_settlement_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "结算时间" VARCHAR(64),
    "订单号" VARCHAR(128),
    "子订单号" VARCHAR(128),
    "结算金额" VARCHAR(64),
    "结算账户" VARCHAR(128),
    "结算单类型" VARCHAR(128),
    "有结算前退款" VARCHAR(64),
    "下单时间" VARCHAR(64),
    "商品ID" VARCHAR(128),
    "商品名称" TEXT,
    "商品数量" VARCHAR(64),
    "达人ID" VARCHAR(128),
    "达人名称" VARCHAR(255),
    "业务类型" VARCHAR(128),
    "订单类型" VARCHAR(128),
    "订单总价" VARCHAR(64),
    "商品总价" VARCHAR(64),
    "运费" VARCHAR(64),
    "店铺券" VARCHAR(64),
    "政府补贴商家垫资" VARCHAR(64),
    "结算前退款金额" VARCHAR(64),
    "平台补贴" VARCHAR(64),
    "其他平台补贴" VARCHAR(64),
    "政府补贴平台垫资" VARCHAR(64),
    "达人补贴" VARCHAR(64),
    "抖音支付补贴" VARCHAR(64),
    "抖音月付营销补贴" VARCHAR(64),
    "银行补贴" VARCHAR(64),
    "以旧换新抵扣" VARCHAR(64),
    "平台补贴运费" VARCHAR(64),
    "用户实付" VARCHAR(64),
    "收入合计" VARCHAR(64),
    "平台服务费" VARCHAR(64),
    "达人佣金" VARCHAR(64),
    "服务商佣金" VARCHAR(64),
    "渠道分成" VARCHAR(64),
    "招商服务费" VARCHAR(64),
    "站外推广费" VARCHAR(64),
    "其他分成" VARCHAR(64),
    "其他分成说明" TEXT,
    "支出合计" VARCHAR(64),
    "是否免佣" VARCHAR(64),
    "免佣金额" VARCHAR(64),
    "商户主体名称" VARCHAR(255),
    "备注" TEXT,

    CONSTRAINT uk_ods_douyin_settlement_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_douyin_settlement_raw
SET source_sheet_name = 'CSV'
WHERE source_sheet_name IS NULL OR source_sheet_name = '';

ALTER TABLE ods.ods_douyin_settlement_raw
    ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';

ALTER TABLE ods.ods_douyin_settlement_raw
    ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_order_no
    ON ods.ods_douyin_settlement_raw ("订单号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_sub_order_no
    ON ods.ods_douyin_settlement_raw ("子订单号");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_product_id
    ON ods.ods_douyin_settlement_raw ("商品ID");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_kol_id
    ON ods.ods_douyin_settlement_raw ("达人ID");

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_source_file
    ON ods.ods_douyin_settlement_raw (source_file_name);

CREATE INDEX IF NOT EXISTS idx_ods_douyin_settlement_batch_id
    ON ods.ods_douyin_settlement_raw (batch_id);

COMMENT ON TABLE ods.ods_douyin_settlement_raw IS 'ODS抖音结算单原始表：第1行表头，第2行字段说明跳过，第3行起为数据';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.batch_id IS '导入批次ID，可与 ods_file_ingest_log.batch_id 关联';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.source_file_name IS '来源文件名';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.source_sheet_name IS 'Excel工作表名；CSV固定写CSV，避免为空';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.source_row_no IS '来源文件行号，按原始文件从1开始';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_douyin_settlement_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."结算时间" IS '来源文件字段“结算时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."订单号" IS '来源文件字段“订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."子订单号" IS '来源文件字段“子订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."结算金额" IS '来源文件字段“结算金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."结算账户" IS '来源文件字段“结算账户”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."结算单类型" IS '来源文件字段“结算单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."有结算前退款" IS '来源文件字段“有结算前退款”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."下单时间" IS '来源文件字段“下单时间”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."商品ID" IS '来源文件字段“商品ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."商品数量" IS '来源文件字段“商品数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."达人ID" IS '来源文件字段“达人ID”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."达人名称" IS '来源文件字段“达人名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."业务类型" IS '来源文件字段“业务类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."订单类型" IS '来源文件字段“订单类型”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."订单总价" IS '来源文件字段“订单总价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."商品总价" IS '来源文件字段“商品总价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."运费" IS '来源文件字段“运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."店铺券" IS '来源文件字段“店铺券”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."政府补贴商家垫资" IS '来源文件字段“政府补贴商家垫资”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."结算前退款金额" IS '来源文件字段“结算前退款金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."平台补贴" IS '来源文件字段“平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."其他平台补贴" IS '来源文件字段“其他平台补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."政府补贴平台垫资" IS '来源文件字段“政府补贴平台垫资”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."达人补贴" IS '来源文件字段“达人补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."抖音支付补贴" IS '来源文件字段“抖音支付补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."抖音月付营销补贴" IS '来源文件字段“抖音月付营销补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."银行补贴" IS '来源文件字段“银行补贴”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."以旧换新抵扣" IS '来源文件字段“以旧换新抵扣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."平台补贴运费" IS '来源文件字段“平台补贴运费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."用户实付" IS '来源文件字段“用户实付”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."收入合计" IS '来源文件字段“收入合计”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."平台服务费" IS '来源文件字段“平台服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."达人佣金" IS '来源文件字段“达人佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."服务商佣金" IS '来源文件字段“服务商佣金”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."渠道分成" IS '来源文件字段“渠道分成”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."招商服务费" IS '来源文件字段“招商服务费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."站外推广费" IS '来源文件字段“站外推广费”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."其他分成" IS '来源文件字段“其他分成”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."其他分成说明" IS '来源文件字段“其他分成说明”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."支出合计" IS '来源文件字段“支出合计”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."是否免佣" IS '来源文件字段“是否免佣”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."免佣金额" IS '来源文件字段“免佣金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."商户主体名称" IS '来源文件字段“商户主体名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_douyin_settlement_raw."备注" IS '来源文件字段“备注”，保留平台导出的原始值。';
