CREATE SCHEMA IF NOT EXISTS fund;

CREATE TABLE IF NOT EXISTS fund.import_record (
    id BIGSERIAL PRIMARY KEY,
    batch_id VARCHAR(32) NOT NULL UNIQUE,
    file_name VARCHAR(500) NOT NULL,
    file_size BIGINT NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_sha256 CHAR(64) NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    dwd_record_count INTEGER NOT NULL DEFAULT 0,
    total_debit NUMERIC(18,2) NOT NULL DEFAULT 0,
    total_credit NUMERIC(18,2) NOT NULL DEFAULT 0,
    date_from DATE,
    date_to DATE,
    status VARCHAR(20) NOT NULL DEFAULT 'processing',
    error_message TEXT,
    operator VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45),
    is_submitted BOOLEAN NOT NULL DEFAULT FALSE,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_fund_import_record_status CHECK (status IN ('processing','success','failed'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fund_import_record_success_sha
    ON fund.import_record (file_sha256) WHERE status = 'success';

CREATE TABLE IF NOT EXISTS fund.operation_log (
    id BIGSERIAL PRIMARY KEY,
    log_no VARCHAR(20) NOT NULL UNIQUE,
    operation_type VARCHAR(30) NOT NULL,
    operator VARCHAR(100) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id BIGINT,
    target_description VARCHAR(500) NOT NULL DEFAULT '',
    change_detail JSONB,
    change_amount NUMERIC(18,2),
    ip_address VARCHAR(45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fund_operation_log_created ON fund.operation_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fund_operation_log_type ON fund.operation_log (operation_type, created_at DESC);

COMMENT ON TABLE fund.import_record IS '银行流水文件导入批次与处理状态；按成功文件SHA256防重复导入。';
COMMENT ON COLUMN fund.import_record.id IS '导入记录代理主键。';
COMMENT ON COLUMN fund.import_record.batch_id IS '导入批次号，格式IMPYYYYMMDDNNN。';
COMMENT ON COLUMN fund.import_record.file_name IS '用户上传的原始Excel文件名。';
COMMENT ON COLUMN fund.import_record.file_size IS '原始文件字节数。';
COMMENT ON COLUMN fund.import_record.file_path IS '服务器保存的原始文件相对路径。';
COMMENT ON COLUMN fund.import_record.file_sha256 IS '原始文件SHA-256摘要，用于幂等校验。';
COMMENT ON COLUMN fund.import_record.record_count IS '成功写入ODS的银行原始流水行数。';
COMMENT ON COLUMN fund.import_record.dwd_record_count IS '成功写入DWD的拆分明细行数。';
COMMENT ON COLUMN fund.import_record.total_debit IS 'ODS借方合计，单位人民币元。';
COMMENT ON COLUMN fund.import_record.total_credit IS 'ODS贷方合计，单位人民币元。';
COMMENT ON COLUMN fund.import_record.date_from IS '本批次最早交易日期。';
COMMENT ON COLUMN fund.import_record.date_to IS '本批次最晚交易日期。';
COMMENT ON COLUMN fund.import_record.status IS '导入状态：processing处理中、success成功、failed失败。';
COMMENT ON COLUMN fund.import_record.error_message IS '失败错误摘要；成功时为NULL。';
COMMENT ON COLUMN fund.import_record.operator IS '执行导入的操作人。';
COMMENT ON COLUMN fund.import_record.ip_address IS '执行导入的客户端IP。';
COMMENT ON COLUMN fund.import_record.is_submitted IS 'DWD是否经校验后确认可供后续看板加工。';
COMMENT ON COLUMN fund.import_record.submitted_at IS '提交确认时间，带时区。';
COMMENT ON COLUMN fund.import_record.created_at IS '导入发起时间，带时区。';
COMMENT ON TABLE fund.operation_log IS '资金流水系统全量操作审计日志。';
COMMENT ON COLUMN fund.operation_log.id IS '操作日志代理主键。';
COMMENT ON COLUMN fund.operation_log.log_no IS '日志编号，格式LOG加六位递增序号。';
COMMENT ON COLUMN fund.operation_log.operation_type IS '操作类型：import、split、adjust、submit及维度维护等。';
COMMENT ON COLUMN fund.operation_log.operator IS '操作人。';
COMMENT ON COLUMN fund.operation_log.target_type IS '操作对象类型。';
COMMENT ON COLUMN fund.operation_log.target_id IS '操作对象ID；批量操作允许为空。';
COMMENT ON COLUMN fund.operation_log.target_description IS '操作对象中文描述。';
COMMENT ON COLUMN fund.operation_log.change_detail IS '变更前后JSON明细。';
COMMENT ON COLUMN fund.operation_log.change_amount IS '本次操作金额影响，单位人民币元，可为空。';
COMMENT ON COLUMN fund.operation_log.ip_address IS '客户端IP地址。';
COMMENT ON COLUMN fund.operation_log.created_at IS '操作发生时间，带时区。';

