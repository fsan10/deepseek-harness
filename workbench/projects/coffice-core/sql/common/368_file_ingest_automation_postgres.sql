CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.ingest_run (
    run_id UUID PRIMARY KEY,
    source VARCHAR(16) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    expected_file_count INTEGER NOT NULL DEFAULT 0,
    success_file_count INTEGER NOT NULL DEFAULT 0,
    duplicate_file_count INTEGER NOT NULL DEFAULT 0,
    failed_file_count INTEGER NOT NULL DEFAULT 0,
    auto_refresh BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    operator VARCHAR(100) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_ingest_run_idempotency UNIQUE (source, idempotency_key),
    CONSTRAINT ck_ops_ingest_run_source CHECK (source IN ('robot', 'manual')),
    CONSTRAINT ck_ops_ingest_run_status CHECK (
        status IN ('draft', 'ready', 'processing', 'success', 'no_change', 'failed')
    ),
    CONSTRAINT ck_ops_ingest_run_counts CHECK (
        expected_file_count >= 0 AND success_file_count >= 0
        AND duplicate_file_count >= 0 AND failed_file_count >= 0
    )
);

CREATE TABLE IF NOT EXISTS ops.ingest_file_task (
    file_task_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES ops.ingest_run(run_id) ON DELETE CASCADE,
    client_file_id VARCHAR(128) NOT NULL,
    source_file_name VARCHAR(255) NOT NULL,
    report_type VARCHAR(64) NOT NULL,
    requested_platform_name VARCHAR(64),
    requested_company_name VARCHAR(255),
    requested_shop_code VARCHAR(128),
    requested_shop_name VARCHAR(255),
    resolved_platform_code VARCHAR(32) NOT NULL,
    resolved_platform_name VARCHAR(64) NOT NULL,
    resolved_company_code VARCHAR(32) NOT NULL,
    resolved_company_name VARCHAR(255) NOT NULL,
    resolved_shop_code VARCHAR(128) NOT NULL,
    resolved_shop_name VARCHAR(255) NOT NULL,
    shop_identity_key VARCHAR(161) NOT NULL,
    file_hash CHAR(64) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    storage_path TEXT NOT NULL,
    batch_id BIGINT,
    status VARCHAR(32) NOT NULL DEFAULT 'uploaded',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_ingest_file_client UNIQUE (run_id, client_file_id),
    CONSTRAINT ck_ops_ingest_file_status CHECK (
        status IN ('uploaded', 'processing', 'success', 'duplicate', 'failed')
    ),
    CONSTRAINT ck_ops_ingest_file_size CHECK (file_size_bytes > 0),
    CONSTRAINT ck_ops_ingest_file_attempt CHECK (attempt_count >= 0)
);

CREATE TABLE IF NOT EXISTS ops.etl_run (
    etl_run_id UUID PRIMARY KEY,
    ingest_run_id UUID REFERENCES ops.ingest_run(run_id) ON DELETE SET NULL,
    trigger_type VARCHAR(32) NOT NULL,
    scope VARCHAR(16) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    requested_etls JSONB NOT NULL DEFAULT '[]'::JSONB,
    operator VARCHAR(100) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_etl_run_trigger CHECK (
        trigger_type IN ('ingest_complete', 'nightly', 'bank_submit', 'fee_mapping', 'manual')
    ),
    CONSTRAINT ck_ops_etl_run_scope CHECK (scope IN ('affected', 'all', 'selected')),
    CONSTRAINT ck_ops_etl_run_status CHECK (
        status IN ('queued', 'running', 'success', 'partial_failed', 'failed', 'no_change')
    )
);

CREATE TABLE IF NOT EXISTS ops.etl_task (
    etl_task_id UUID PRIMARY KEY,
    etl_run_id UUID NOT NULL REFERENCES ops.etl_run(etl_run_id) ON DELETE CASCADE,
    etl_key VARCHAR(96) NOT NULL,
    etl_label VARCHAR(255) NOT NULL,
    sequence_no INTEGER NOT NULL,
    dependencies JSONB NOT NULL DEFAULT '[]'::JSONB,
    command_args JSONB NOT NULL DEFAULT '[]'::JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    exit_code INTEGER,
    output_summary TEXT,
    error_message TEXT,
    result_metrics JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_etl_task_run_key UNIQUE (etl_run_id, etl_key),
    CONSTRAINT ck_ops_etl_task_status CHECK (
        status IN ('queued', 'running', 'success', 'failed', 'skipped')
    ),
    CONSTRAINT ck_ops_etl_task_attempt CHECK (attempt_count >= 0)
);

CREATE TABLE IF NOT EXISTS ops.operation_log (
    operation_id BIGSERIAL PRIMARY KEY,
    operation_type VARCHAR(64) NOT NULL,
    target_type VARCHAR(64) NOT NULL,
    target_key VARCHAR(128),
    operator VARCHAR(100) NOT NULL,
    ip_address VARCHAR(45),
    description VARCHAR(500) NOT NULL,
    change_detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.refresh_watermark (
    watermark_key VARCHAR(64) PRIMARY KEY,
    etl_run_id UUID REFERENCES ops.etl_run(etl_run_id) ON DELETE SET NULL,
    last_success_at TIMESTAMPTZ NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.worker_heartbeat (
    worker_id UUID PRIMARY KEY,
    worker_name VARCHAR(100) NOT NULL,
    process_id INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'starting',
    current_task VARCHAR(255),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at TIMESTAMPTZ,
    CONSTRAINT ck_ops_worker_heartbeat_status CHECK (
        status IN ('starting', 'idle', 'busy', 'stopped', 'failed')
    )
);

ALTER TABLE ods.ods_file_ingest_log
    ADD COLUMN IF NOT EXISTS ingest_run_id UUID,
    ADD COLUMN IF NOT EXISTS ingest_file_task_id UUID,
    ADD COLUMN IF NOT EXISTS report_type VARCHAR(64),
    ADD COLUMN IF NOT EXISTS automation_source VARCHAR(16);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ods_ingest_log_run'
          AND conrelid = 'ods.ods_file_ingest_log'::regclass
    ) THEN
        ALTER TABLE ods.ods_file_ingest_log
            ADD CONSTRAINT fk_ods_ingest_log_run
            FOREIGN KEY (ingest_run_id) REFERENCES ops.ingest_run(run_id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_ods_ingest_log_file_task'
          AND conrelid = 'ods.ods_file_ingest_log'::regclass
    ) THEN
        ALTER TABLE ods.ods_file_ingest_log
            ADD CONSTRAINT fk_ods_ingest_log_file_task
            FOREIGN KEY (ingest_file_task_id) REFERENCES ops.ingest_file_task(file_task_id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ops_ingest_run_status ON ops.ingest_run(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ops_ingest_file_status ON ops.ingest_file_task(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ops_ingest_file_hash ON ops.ingest_file_task(file_hash);
CREATE INDEX IF NOT EXISTS idx_ops_etl_run_status ON ops.etl_run(status, created_at);
CREATE INDEX IF NOT EXISTS idx_ops_etl_task_status ON ops.etl_task(status, sequence_no);
CREATE INDEX IF NOT EXISTS idx_ops_operation_log_created ON ops.operation_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_worker_heartbeat_seen ON ops.worker_heartbeat(status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_ods_ingest_log_automation_run ON ods.ods_file_ingest_log(ingest_run_id, ingest_file_task_id);

COMMENT ON TABLE ops.ingest_run IS '电商文件采集会话；网页或影刀的一批预期文件在全部就绪后统一导入和刷新。';
COMMENT ON COLUMN ops.ingest_run.run_id IS '应用生成的采集会话UUID。';
COMMENT ON COLUMN ops.ingest_run.source IS '会话来源：robot影刀或manual网页人工。';
COMMENT ON COLUMN ops.ingest_run.idempotency_key IS '调用方幂等键，同一来源不可重复。';
COMMENT ON COLUMN ops.ingest_run.expected_file_count IS '本会话预期文件数量。';
COMMENT ON COLUMN ops.ingest_run.success_file_count IS '新文件成功导入数量。';
COMMENT ON COLUMN ops.ingest_run.duplicate_file_count IS '命中历史成功SHA256而未重复导入的数量。';
COMMENT ON COLUMN ops.ingest_run.failed_file_count IS '导入失败文件数量。';
COMMENT ON COLUMN ops.ingest_run.auto_refresh IS '文件全部成功后是否自动创建受影响ETL任务。';
COMMENT ON COLUMN ops.ingest_run.status IS '会话状态：draft/ready/processing/success/no_change/failed。';
COMMENT ON COLUMN ops.ingest_run.operator IS '创建会话的操作人或机器人名称。';
COMMENT ON COLUMN ops.ingest_run.error_message IS '会话失败或完整性校验错误。';
COMMENT ON COLUMN ops.ingest_run.created_at IS '会话创建时间。';
COMMENT ON COLUMN ops.ingest_run.completed_at IS '会话完成时间。';
COMMENT ON COLUMN ops.ingest_run.updated_at IS '会话最后更新时间。';

COMMENT ON TABLE ops.ingest_file_task IS '采集会话文件任务；只保存实际上传文件名，不保存改名前文件名。';
COMMENT ON COLUMN ops.ingest_file_task.file_task_id IS '应用生成的文件任务UUID。';
COMMENT ON COLUMN ops.ingest_file_task.run_id IS '所属采集会话UUID。';
COMMENT ON COLUMN ops.ingest_file_task.client_file_id IS '调用方提供的会话内唯一文件标识。';
COMMENT ON COLUMN ops.ingest_file_task.source_file_name IS '实际上传并进入导入记录的文件名。';
COMMENT ON COLUMN ops.ingest_file_task.report_type IS '内部稳定报表类型，决定Loader和下游ETL。';
COMMENT ON COLUMN ops.ingest_file_task.requested_platform_name IS '调用方传入的平台名称快照。';
COMMENT ON COLUMN ops.ingest_file_task.requested_company_name IS '调用方传入的公司全称快照。';
COMMENT ON COLUMN ops.ingest_file_task.requested_shop_code IS '调用方传入的标准店铺编码。';
COMMENT ON COLUMN ops.ingest_file_task.requested_shop_name IS '调用方传入的店铺名称快照。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_platform_code IS '通过注册表和DIM解析的平台编码。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_platform_name IS '通过注册表和DIM解析的平台名称。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_company_code IS '通过DIM解析的公司编码。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_company_name IS '通过DIM解析的公司全称。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_shop_code IS '通过DIM解析的标准店铺编码。';
COMMENT ON COLUMN ops.ingest_file_task.resolved_shop_name IS '通过DIM解析的标准店铺名称。';
COMMENT ON COLUMN ops.ingest_file_task.shop_identity_key IS '平台与店铺组成的稳定店铺身份键。';
COMMENT ON COLUMN ops.ingest_file_task.file_hash IS '上传文件SHA256，用于文件级幂等。';
COMMENT ON COLUMN ops.ingest_file_task.file_size_bytes IS '上传文件大小，单位字节。';
COMMENT ON COLUMN ops.ingest_file_task.storage_path IS '服务器文件存储根目录下的相对路径。';
COMMENT ON COLUMN ops.ingest_file_task.batch_id IS '成功或重复文件对应的ODS导入批次ID。';
COMMENT ON COLUMN ops.ingest_file_task.status IS '文件任务状态：uploaded/processing/success/duplicate/failed。';
COMMENT ON COLUMN ops.ingest_file_task.attempt_count IS 'Loader实际执行次数。';
COMMENT ON COLUMN ops.ingest_file_task.error_message IS '文件校验或Loader失败原因。';
COMMENT ON COLUMN ops.ingest_file_task.created_at IS '文件上传时间。';
COMMENT ON COLUMN ops.ingest_file_task.started_at IS 'Loader开始时间。';
COMMENT ON COLUMN ops.ingest_file_task.finished_at IS 'Loader结束时间。';
COMMENT ON COLUMN ops.ingest_file_task.updated_at IS '文件任务最后更新时间。';

COMMENT ON TABLE ops.etl_run IS '一次受影响、夜间全量、银行提交、费用映射或人工触发的ETL运行。';
COMMENT ON COLUMN ops.etl_run.etl_run_id IS '应用生成的ETL运行UUID。';
COMMENT ON COLUMN ops.etl_run.ingest_run_id IS '可选的来源采集会话。';
COMMENT ON COLUMN ops.etl_run.trigger_type IS '触发类型：ingest_complete/nightly/bank_submit/fee_mapping/manual。';
COMMENT ON COLUMN ops.etl_run.scope IS '刷新范围：affected/all/selected。';
COMMENT ON COLUMN ops.etl_run.status IS '运行状态：queued/running/success/partial_failed/failed/no_change。';
COMMENT ON COLUMN ops.etl_run.requested_etls IS '创建时解析出的ETL键有序列表。';
COMMENT ON COLUMN ops.etl_run.operator IS '任务创建人或系统标识。';
COMMENT ON COLUMN ops.etl_run.error_message IS '运行级失败摘要。';
COMMENT ON COLUMN ops.etl_run.created_at IS '任务创建时间。';
COMMENT ON COLUMN ops.etl_run.started_at IS '任务开始时间。';
COMMENT ON COLUMN ops.etl_run.completed_at IS '任务完成时间。';
COMMENT ON COLUMN ops.etl_run.updated_at IS '任务最后更新时间。';

COMMENT ON TABLE ops.etl_task IS 'ETL运行中的白名单任务节点，按sequence_no串行执行。';
COMMENT ON COLUMN ops.etl_task.etl_task_id IS '应用生成的ETL任务UUID。';
COMMENT ON COLUMN ops.etl_task.etl_run_id IS '所属ETL运行UUID。';
COMMENT ON COLUMN ops.etl_task.etl_key IS 'ETL注册表稳定键。';
COMMENT ON COLUMN ops.etl_task.etl_label IS 'ETL中文展示名称。';
COMMENT ON COLUMN ops.etl_task.sequence_no IS '同一运行内执行顺序。';
COMMENT ON COLUMN ops.etl_task.dependencies IS '必须先成功的ETL键列表。';
COMMENT ON COLUMN ops.etl_task.command_args IS '注册表生成的非敏感命令参数。';
COMMENT ON COLUMN ops.etl_task.status IS '任务状态：queued/running/success/failed/skipped。';
COMMENT ON COLUMN ops.etl_task.attempt_count IS '任务执行次数。';
COMMENT ON COLUMN ops.etl_task.exit_code IS '子进程退出码。';
COMMENT ON COLUMN ops.etl_task.output_summary IS '标准输出摘要，超长内容截断。';
COMMENT ON COLUMN ops.etl_task.error_message IS '标准错误或异常摘要。';
COMMENT ON COLUMN ops.etl_task.result_metrics IS '可解析的行数、日期范围和指标值JSON。';
COMMENT ON COLUMN ops.etl_task.created_at IS '任务创建时间。';
COMMENT ON COLUMN ops.etl_task.started_at IS '任务开始时间。';
COMMENT ON COLUMN ops.etl_task.finished_at IS '任务结束时间。';
COMMENT ON COLUMN ops.etl_task.updated_at IS '任务最后更新时间。';

COMMENT ON TABLE ops.operation_log IS '数据导入、ETL及费用映射操作审计日志。';
COMMENT ON COLUMN ops.operation_log.operation_id IS '操作日志自增主键。';
COMMENT ON COLUMN ops.operation_log.operation_type IS '操作类型，如upload、complete、retry或fee_mapping_update。';
COMMENT ON COLUMN ops.operation_log.target_type IS '操作对象类型。';
COMMENT ON COLUMN ops.operation_log.target_key IS '对象业务键或UUID文本。';
COMMENT ON COLUMN ops.operation_log.operator IS '操作人或机器人名称。';
COMMENT ON COLUMN ops.operation_log.ip_address IS '客户端IP地址。';
COMMENT ON COLUMN ops.operation_log.description IS '操作摘要。';
COMMENT ON COLUMN ops.operation_log.change_detail IS '变更前后值或任务参数JSON。';
COMMENT ON COLUMN ops.operation_log.created_at IS '操作发生时间。';

COMMENT ON TABLE ops.refresh_watermark IS '自动化链路最后成功刷新水位。';
COMMENT ON COLUMN ops.refresh_watermark.watermark_key IS '水位类型，如affected、nightly或bank_summary。';
COMMENT ON COLUMN ops.refresh_watermark.etl_run_id IS '最后成功ETL运行UUID。';
COMMENT ON COLUMN ops.refresh_watermark.last_success_at IS '最后成功完成时间。';
COMMENT ON COLUMN ops.refresh_watermark.summary IS '最后成功运行摘要。';
COMMENT ON COLUMN ops.refresh_watermark.updated_at IS '水位记录更新时间。';

COMMENT ON TABLE ops.worker_heartbeat IS '数据导入Worker运行心跳；用于网页判断任务是否会继续执行。';
COMMENT ON COLUMN ops.worker_heartbeat.worker_id IS 'Worker进程启动时生成的UUID。';
COMMENT ON COLUMN ops.worker_heartbeat.worker_name IS 'Worker实例名称，例如embedded-web或standalone。';
COMMENT ON COLUMN ops.worker_heartbeat.process_id IS '操作系统进程ID，仅用于运行诊断。';
COMMENT ON COLUMN ops.worker_heartbeat.status IS 'Worker状态：starting/idle/busy/stopped/failed。';
COMMENT ON COLUMN ops.worker_heartbeat.current_task IS '当前处理的采集会话或ETL运行标识。';
COMMENT ON COLUMN ops.worker_heartbeat.started_at IS 'Worker启动时间。';
COMMENT ON COLUMN ops.worker_heartbeat.last_seen_at IS '最后心跳时间；超过15秒视为离线。';
COMMENT ON COLUMN ops.worker_heartbeat.stopped_at IS 'Worker正常停止或失败退出时间。';

COMMENT ON COLUMN ods.ods_file_ingest_log.ingest_run_id IS '自动化采集会话UUID；历史或CLI导入为空。';
COMMENT ON COLUMN ods.ods_file_ingest_log.ingest_file_task_id IS '自动化文件任务UUID；历史或CLI导入为空。';
COMMENT ON COLUMN ods.ods_file_ingest_log.report_type IS '自动化注册表内部报表类型。';
COMMENT ON COLUMN ods.ods_file_ingest_log.automation_source IS '自动化来源robot或manual；传统CLI导入为空。';
