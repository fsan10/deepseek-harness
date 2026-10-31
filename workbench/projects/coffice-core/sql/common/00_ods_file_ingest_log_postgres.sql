CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_file_ingest_log (
    batch_id BIGSERIAL PRIMARY KEY,

    source_system VARCHAR(32) NOT NULL DEFAULT 'file',
    platform_code VARCHAR(32) NOT NULL,
    platform_name VARCHAR(64),
    shop_code VARCHAR(128),
    shop_name VARCHAR(255),
    shop_identity_key VARCHAR(161),
    shop_mapping_status VARCHAR(32),
    shop_mapping_source VARCHAR(32),
    shop_mapping_message TEXT,
    data_domain VARCHAR(64) NOT NULL,

    source_file_path TEXT NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    file_hash CHAR(64),
    file_size_bytes BIGINT,
    file_encoding VARCHAR(64),
    source_sheet_name VARCHAR(128) NOT NULL DEFAULT 'CSV',

    header_row_no INTEGER NOT NULL DEFAULT 1,
    data_start_row_no INTEGER NOT NULL DEFAULT 3,
    total_rows INTEGER NOT NULL DEFAULT 0,
    parsed_rows INTEGER NOT NULL DEFAULT 0,
    success_rows INTEGER NOT NULL DEFAULT 0,
    duplicate_rows INTEGER NOT NULL DEFAULT 0,
    failed_rows INTEGER NOT NULL DEFAULT 0,

    target_schema VARCHAR(64),
    target_table VARCHAR(128),
    ingest_status VARCHAR(32) NOT NULL DEFAULT 'running',
    error_message TEXT,

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_seconds NUMERIC(18,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ods.ods_file_ingest_log
    ADD COLUMN IF NOT EXISTS shop_identity_key VARCHAR(161),
    ADD COLUMN IF NOT EXISTS shop_mapping_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS shop_mapping_source VARCHAR(32),
    ADD COLUMN IF NOT EXISTS shop_mapping_message TEXT;

COMMENT ON TABLE ods.ods_file_ingest_log IS 'ODS文件导入日志：记录每次文件导入批次、来源、行数、状态和目标表';
COMMENT ON COLUMN ods.ods_file_ingest_log.batch_id IS '导入批次ID，ODS明细表通过该字段追踪来源批次';
COMMENT ON COLUMN ods.ods_file_ingest_log.source_system IS '来源系统，例如 file/api/manual';
COMMENT ON COLUMN ods.ods_file_ingest_log.platform_code IS '平台编码，例如 douyin/jd/tmall/pdd';
COMMENT ON COLUMN ods.ods_file_ingest_log.platform_name IS '平台名称，例如 抖音/京东/天猫';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_code IS '经DIM校验的标准店铺编码；正式导入必须填写。';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_name IS '经DIM校验的标准店铺名称。';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_identity_key IS '稳定店铺身份键，格式为标准平台编码|标准店铺编码。';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_mapping_status IS '批次店铺映射状态，例如mapped、conflict或unmapped。';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_mapping_source IS '店铺映射来源，例如manual_selected、robot_selected或manual_backfill。';
COMMENT ON COLUMN ods.ods_file_ingest_log.shop_mapping_message IS '店铺映射过程、人工确认或冲突原因说明。';
COMMENT ON COLUMN ods.ods_file_ingest_log.data_domain IS '数据域，例如 settlement/order/after_sale/fund/ad/inventory/bank';
COMMENT ON COLUMN ods.ods_file_ingest_log.source_file_path IS '源文件完整路径';
COMMENT ON COLUMN ods.ods_file_ingest_log.source_file_name IS '源文件名';
COMMENT ON COLUMN ods.ods_file_ingest_log.file_hash IS '文件SHA256，用于识别重复文件';
COMMENT ON COLUMN ods.ods_file_ingest_log.file_size_bytes IS '文件大小，单位字节';
COMMENT ON COLUMN ods.ods_file_ingest_log.file_encoding IS '文件编码，Excel可为空';
COMMENT ON COLUMN ods.ods_file_ingest_log.source_sheet_name IS '来源Sheet名；CSV统一写CSV，避免为空';
COMMENT ON COLUMN ods.ods_file_ingest_log.header_row_no IS '表头行号';
COMMENT ON COLUMN ods.ods_file_ingest_log.data_start_row_no IS '数据起始行号';
COMMENT ON COLUMN ods.ods_file_ingest_log.total_rows IS '源文件总行数或Sheet总行数';
COMMENT ON COLUMN ods.ods_file_ingest_log.parsed_rows IS '解析出的非空数据行数';
COMMENT ON COLUMN ods.ods_file_ingest_log.success_rows IS '实际插入成功行数';
COMMENT ON COLUMN ods.ods_file_ingest_log.duplicate_rows IS '因row_hash重复跳过的行数';
COMMENT ON COLUMN ods.ods_file_ingest_log.failed_rows IS '失败行数';
COMMENT ON COLUMN ods.ods_file_ingest_log.target_schema IS '目标schema';
COMMENT ON COLUMN ods.ods_file_ingest_log.target_table IS '目标表名';
COMMENT ON COLUMN ods.ods_file_ingest_log.ingest_status IS '导入状态：running/success/partial_success/failed';
COMMENT ON COLUMN ods.ods_file_ingest_log.error_message IS '错误信息';
COMMENT ON COLUMN ods.ods_file_ingest_log.duration_seconds IS '导入耗时秒数';

CREATE INDEX IF NOT EXISTS idx_ods_file_ingest_log_platform_domain
    ON ods.ods_file_ingest_log (platform_code, data_domain);

CREATE INDEX IF NOT EXISTS idx_ods_file_ingest_log_shop_identity
    ON ods.ods_file_ingest_log (shop_identity_key, batch_id);

CREATE INDEX IF NOT EXISTS idx_ods_file_ingest_log_file_hash
    ON ods.ods_file_ingest_log (file_hash);

CREATE INDEX IF NOT EXISTS idx_ods_file_ingest_log_status
    ON ods.ods_file_ingest_log (ingest_status);

CREATE INDEX IF NOT EXISTS idx_ods_file_ingest_log_started_at
    ON ods.ods_file_ingest_log (started_at);

COMMENT ON COLUMN ods.ods_file_ingest_log.started_at IS '文件导入任务开始时间。';
COMMENT ON COLUMN ods.ods_file_ingest_log.finished_at IS '文件导入任务结束时间。';
COMMENT ON COLUMN ods.ods_file_ingest_log.created_at IS '记录创建时间。';
COMMENT ON COLUMN ods.ods_file_ingest_log.updated_at IS '记录最后更新时间。';
