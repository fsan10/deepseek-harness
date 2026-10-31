CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_settlement_expense_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "账期" VARCHAR(64),
    "资金方向" VARCHAR(128),
    "账单大类" VARCHAR(128),
    "业务大类" VARCHAR(128),
    "业务小类" VARCHAR(128),
    "支出项目" VARCHAR(128),
    "扣费日期" VARCHAR(64),
    "扣费交易金额" VARCHAR(64),
    "扣费金额" VARCHAR(64),
    "佣金率" VARCHAR(64),
    "订单日期" VARCHAR(64),
    "交易主订单号" VARCHAR(128),
    "交易子订单号" VARCHAR(128),
    "商品名称" TEXT,
    "数量" VARCHAR(64),
    "单价" VARCHAR(64),
    "支付宝商户订单号(新增)" VARCHAR(128),
    "报名id(新增)" VARCHAR(128),
    "收/付渠道描述" VARCHAR(128),
    "扣费金额(元)" VARCHAR(64),
    "退款金额(元)" VARCHAR(64),
    "确认收货日期" VARCHAR(64),
    "交易主单号" VARCHAR(128),
    "订单金额" VARCHAR(64),
    "扣费基数" VARCHAR(64),
    "本月付款" VARCHAR(64),
    "费率" VARCHAR(64),
    "支付渠道商户订单号" VARCHAR(128),
    "支付宝商户订单号" VARCHAR(128),
    "报名id" VARCHAR(128),
    "退款金额（元）" VARCHAR(64),
    "扣款交易金额" VARCHAR(64),
    "扣费交易金额（元）" VARCHAR(64),
    "支出金额（元）" VARCHAR(64),
    "扣费金额（元）" VARCHAR(64),
    "单价（元）(新增)" VARCHAR(64),
    "数量(新增)" VARCHAR(64),
    "商品名称(新增)" TEXT,
    "交易主订单号_2" VARCHAR(128),
    "订单日期_2" VARCHAR(64),
    "佣金率_2" VARCHAR(64),
    "交易子订单号_2" VARCHAR(128),

    CONSTRAINT uk_ods_tmall_settlement_expense_row_hash UNIQUE (row_hash)
);

UPDATE ods.ods_tmall_settlement_expense_raw SET source_sheet_name = 'CSV' WHERE source_sheet_name IS NULL OR source_sheet_name = '';
ALTER TABLE ods.ods_tmall_settlement_expense_raw ALTER COLUMN source_sheet_name SET DEFAULT 'CSV';
ALTER TABLE ods.ods_tmall_settlement_expense_raw ALTER COLUMN source_sheet_name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ods_tmall_expense_batch_id ON ods.ods_tmall_settlement_expense_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_expense_main_order ON ods.ods_tmall_settlement_expense_raw ("交易主订单号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_expense_sub_order ON ods.ods_tmall_settlement_expense_raw ("交易子订单号");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_expense_source_file ON ods.ods_tmall_settlement_expense_raw (source_file_name);

COMMENT ON TABLE ods.ods_tmall_settlement_expense_raw IS 'ODS天猫结算支出原始表，采用服务费文件字段超集';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.batch_id IS '导入批次ID，关联 ods_file_ingest_log.batch_id';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.source_file_name IS '来源文件名，用于区分具体服务费文件';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.source_sheet_name IS '来源工作表；CSV固定写CSV';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.source_row_no IS '来源文件行号';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.row_hash IS '行级SHA256，用于幂等去重';

COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw.ingest_time IS '该记录写入ODS的时间。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."账期" IS '来源文件字段“账期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."资金方向" IS '来源文件字段“资金方向”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."账单大类" IS '来源文件字段“账单大类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."业务大类" IS '来源文件字段“业务大类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."业务小类" IS '来源文件字段“业务小类”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."支出项目" IS '来源文件字段“支出项目”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费日期" IS '来源文件字段“扣费日期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费交易金额" IS '来源文件字段“扣费交易金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费金额" IS '来源文件字段“扣费金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."佣金率" IS '来源文件字段“佣金率”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."订单日期" IS '来源文件字段“订单日期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."交易主订单号" IS '来源文件字段“交易主订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."交易子订单号" IS '来源文件字段“交易子订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."商品名称" IS '来源文件字段“商品名称”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."数量" IS '来源文件字段“数量”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."单价" IS '来源文件字段“单价”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."支付宝商户订单号(新增)" IS '来源文件字段“支付宝商户订单号(新增)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."报名id(新增)" IS '来源文件字段“报名id(新增)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."收/付渠道描述" IS '来源文件字段“收/付渠道描述”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费金额(元)" IS '来源文件字段“扣费金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."退款金额(元)" IS '来源文件字段“退款金额(元)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."确认收货日期" IS '来源文件字段“确认收货日期”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."交易主单号" IS '来源文件字段“交易主单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."订单金额" IS '来源文件字段“订单金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费基数" IS '来源文件字段“扣费基数”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."本月付款" IS '来源文件字段“本月付款”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."费率" IS '来源文件字段“费率”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."支付渠道商户订单号" IS '来源文件字段“支付渠道商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."支付宝商户订单号" IS '来源文件字段“支付宝商户订单号”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."报名id" IS '来源文件字段“报名id”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."退款金额（元）" IS '来源文件字段“退款金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣款交易金额" IS '来源文件字段“扣款交易金额”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费交易金额（元）" IS '来源文件字段“扣费交易金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."支出金额（元）" IS '来源文件字段“支出金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."扣费金额（元）" IS '来源文件字段“扣费金额（元）”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."单价（元）(新增)" IS '来源文件字段“单价（元）(新增)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."数量(新增)" IS '来源文件字段“数量(新增)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."商品名称(新增)" IS '来源文件字段“商品名称(新增)”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."交易主订单号_2" IS '来源文件字段“交易主订单号_2”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."订单日期_2" IS '来源文件字段“订单日期_2”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."佣金率_2" IS '来源文件字段“佣金率_2”，保留平台导出的原始值。';
COMMENT ON COLUMN ods.ods_tmall_settlement_expense_raw."交易子订单号_2" IS '来源文件字段“交易子订单号_2”，保留平台导出的原始值。';
