CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_alipay_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "账务流水号" TEXT,
    "业务流水号" TEXT,
    "商户订单号" TEXT,
    "商品名称" TEXT,
    "发生时间" TEXT,
    "对方账号" TEXT,
    "收入金额（+元）" TEXT,
    "支出金额（-元）" TEXT,
    "账户余额（元）" TEXT,
    "交易渠道" TEXT,
    "业务类型" TEXT,
    "备注" TEXT,

    CONSTRAINT uk_ods_tmall_alipay_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_tmall_alipay_fund_batch
    ON ods.ods_tmall_alipay_fund_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_alipay_fund_time
    ON ods.ods_tmall_alipay_fund_raw ("发生时间");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_alipay_fund_flow
    ON ods.ods_tmall_alipay_fund_raw ("账务流水号");

COMMENT ON TABLE ods.ods_tmall_alipay_fund_raw IS '天猫支付宝账户资金明细ODS，一行对应支付宝导出的一条账务流水。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.batch_id IS '导入批次ID，可关联ods.ods_file_ingest_log。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.source_sheet_name IS 'CSV来源固定为CSV。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.row_hash IS '包含文件、行号和原始字段的SHA256，用于导入幂等。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw.ingest_time IS 'ODS入库时间，带时区。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."账务流水号" IS '支付宝账务流水号，当前文件内唯一。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."业务流水号" IS '支付宝业务流水号，同一业务可能拆分为多条账务流水。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."商户订单号" IS '支付宝商户订单号。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."商品名称" IS '交易商品名称，费用和转账流水可能为空。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."发生时间" IS '账务资金发生时间。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."对方账号" IS '交易对方账号原文。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."收入金额（+元）" IS '平台导出的非负收入金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."支出金额（-元）" IS '平台导出的非正支出金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."账户余额（元）" IS '该账务流水后的支付宝账户余额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."交易渠道" IS '交易渠道，当前为支付宝。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."业务类型" IS '支付宝业务类型，例如交易付款、交易退款、交易分账、转账、其它、提现。';
COMMENT ON COLUMN ods.ods_tmall_alipay_fund_raw."备注" IS '支付宝备注原文，可能包含订单号、扣款用途、付款方、邮箱和批次号。';

