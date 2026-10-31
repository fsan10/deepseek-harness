CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_tmall_aggregate_fund_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT,
    source_file_name VARCHAR(255),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'sheet1',
    source_row_no INTEGER NOT NULL,
    row_hash CHAR(64) NOT NULL,
    ingest_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    "商家昵称" TEXT,
    "入帐日期" TEXT,
    "入帐时间" TEXT,
    "支付流水号" TEXT,
    "主订单id" TEXT,
    "子订单id" TEXT,
    "入帐类型" TEXT,
    "收入金额(元)" TEXT,
    "支出金额(元)" TEXT,
    "业务描述" TEXT,
    "备注" TEXT,
    "收/付渠道" TEXT,
    "数据创建时间" TEXT,
    "数据修改时间" TEXT,

    CONSTRAINT uk_ods_tmall_aggregate_fund_row_hash UNIQUE (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_ods_tmall_aggregate_fund_batch
    ON ods.ods_tmall_aggregate_fund_raw (batch_id);
CREATE INDEX IF NOT EXISTS idx_ods_tmall_aggregate_fund_date
    ON ods.ods_tmall_aggregate_fund_raw ("入帐日期");
CREATE INDEX IF NOT EXISTS idx_ods_tmall_aggregate_fund_flow
    ON ods.ods_tmall_aggregate_fund_raw ("支付流水号");

COMMENT ON TABLE ods.ods_tmall_aggregate_fund_raw IS '天猫聚合账户资金明细ODS，一行对应平台导出的一条聚合结算渠道资金流水。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.id IS '数据库自增主键。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.batch_id IS '导入批次ID，可关联ods.ods_file_ingest_log。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.source_file_name IS '来源文件名。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.source_sheet_name IS '来源工作表名称。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.source_row_no IS '来源文件原始行号。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.row_hash IS '包含文件、工作表、行号和原始字段的SHA256，用于导入幂等。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw.ingest_time IS 'ODS入库时间，带时区。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."商家昵称" IS '平台导出的商家昵称。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."入帐日期" IS '平台导出的资金入帐日期，格式YYYYMMDD。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."入帐时间" IS '平台导出的资金入帐时间。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."支付流水号" IS '聚合账户支付流水号，当前文件内唯一。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."主订单id" IS '平台主订单ID。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."子订单id" IS '平台子订单ID，部分资金流水为空。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."入帐类型" IS '聚合账户业务类型，例如交易收款、扣款、扣款退回、交易退款(售后)、提现。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."收入金额(元)" IS '平台导出的非负收入金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."支出金额(元)" IS '平台导出的非负支出金额，单位元。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."业务描述" IS '平台业务描述原文，可能包含服务费编码。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."备注" IS '平台资金备注原文，通常包含订单ID和扣款或退款动作。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."收/付渠道" IS '资金收付渠道，当前为聚合结算渠道。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."数据创建时间" IS '平台记录创建时间。';
COMMENT ON COLUMN ods.ods_tmall_aggregate_fund_raw."数据修改时间" IS '平台记录最后修改时间。';

