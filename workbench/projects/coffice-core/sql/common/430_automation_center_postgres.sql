CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.automation_job (
    job_id BIGSERIAL PRIMARY KEY,
    job_code VARCHAR(64) NOT NULL UNIQUE,
    job_name VARCHAR(120) NOT NULL,
    job_type VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    execution_lane VARCHAR(24) NOT NULL,
    schedule_type VARCHAR(16) NOT NULL DEFAULT 'manual',
    schedule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    retry_policy JSONB NOT NULL DEFAULT '{"max_attempts":1}'::jsonb,
    timeout_seconds INTEGER NOT NULL DEFAULT 21600,
    description TEXT,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_ops_automation_job_type CHECK (job_type IN ('platform_download','full_etl','flow')),
    CONSTRAINT ck_ops_automation_job_lane CHECK (execution_lane IN ('overnight','interactive','etl')),
    CONSTRAINT ck_ops_automation_job_schedule CHECK (schedule_type IN ('manual','daily')),
    CONSTRAINT ck_ops_automation_job_timeout CHECK (timeout_seconds BETWEEN 60 AND 86400),
    CONSTRAINT ck_ops_automation_job_name CHECK (BTRIM(job_name) <> ''),
    CONSTRAINT ck_ops_automation_job_timezone CHECK (BTRIM(timezone) <> '')
);


CREATE TABLE IF NOT EXISTS ops.automation_flow (
    flow_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_code VARCHAR(120) NOT NULL UNIQUE,
    flow_name VARCHAR(160) NOT NULL,
    description TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1,
    execution_lane VARCHAR(24) NOT NULL DEFAULT 'interactive',
    definition JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
    schedule_type VARCHAR(16) NOT NULL DEFAULT 'manual',
    schedule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    retry_policy JSONB NOT NULL DEFAULT '{"max_attempts":1}'::jsonb,
    timeout_seconds INTEGER NOT NULL DEFAULT 21600,
    default_profile_name VARCHAR(200),
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_ops_automation_flow_status CHECK (status IN ('draft','published','archived')),
    CONSTRAINT ck_ops_automation_flow_version CHECK (version > 0),
    CONSTRAINT ck_ops_automation_flow_lane CHECK (execution_lane IN ('overnight','interactive','etl')),
    CONSTRAINT ck_ops_automation_flow_schedule CHECK (schedule_type IN ('manual','daily')),
    CONSTRAINT ck_ops_automation_flow_timeout CHECK (timeout_seconds BETWEEN 60 AND 86400),
    CONSTRAINT ck_ops_automation_flow_name CHECK (BTRIM(flow_name) <> '')
);

CREATE TABLE IF NOT EXISTS ops.automation_flow_version (
    flow_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    flow_id UUID NOT NULL REFERENCES ops.automation_flow(flow_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    flow_code VARCHAR(120) NOT NULL,
    flow_name VARCHAR(160) NOT NULL,
    execution_lane VARCHAR(24) NOT NULL,
    definition JSONB NOT NULL,
    published_by VARCHAR(100),
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_automation_flow_version UNIQUE(flow_id, version),
    CONSTRAINT ck_ops_automation_flow_version_number CHECK (version > 0),
    CONSTRAINT ck_ops_automation_flow_version_lane CHECK (execution_lane IN ('overnight','interactive','etl'))
);

CREATE TABLE IF NOT EXISTS ops.automation_run (
    automation_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id BIGINT NOT NULL REFERENCES ops.automation_job(job_id) ON DELETE RESTRICT,
    flow_id UUID REFERENCES ops.automation_flow(flow_id) ON DELETE SET NULL,
    flow_version_id UUID REFERENCES ops.automation_flow_version(flow_version_id) ON DELETE SET NULL,
    input_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    trigger_type VARCHAR(16) NOT NULL,
    schedule_key VARCHAR(160),
    business_date DATE NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    execution_lane VARCHAR(24) NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    attempt_started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    operator VARCHAR(100),
    error_message TEXT,
    warning_message TEXT,
    result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    ingest_run_id UUID REFERENCES ops.ingest_run(run_id) ON DELETE SET NULL,
    etl_run_id UUID REFERENCES ops.etl_run(etl_run_id) ON DELETE SET NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    parent_run_id UUID REFERENCES ops.automation_run(automation_run_id) ON DELETE SET NULL,
    worker_id UUID,
    heartbeat_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    resource_key VARCHAR(240),
    waiting_since TIMESTAMPTZ,
    resumed_at TIMESTAMPTZ,
    resume_count INTEGER NOT NULL DEFAULT 0,
    resume_reason VARCHAR(120),
    attention_acknowledged_at TIMESTAMPTZ,
    attention_acknowledged_by VARCHAR(100),
    attention_acknowledged_reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_automation_run_trigger CHECK (trigger_type IN ('manual','schedule','retry','test')),
    CONSTRAINT ck_ops_automation_run_status CHECK (status IN ('queued','running','success','success_with_warnings','no_data','needs_human','failed','cancelled','skipped')),
    CONSTRAINT ck_ops_automation_run_lane CHECK (execution_lane IN ('overnight','interactive','etl')),
    CONSTRAINT ck_ops_automation_run_attempt CHECK (attempt_count >= 0),
    CONSTRAINT ck_ops_automation_run_resume CHECK (resume_count >= 0)
);

ALTER TABLE ops.automation_job DROP CONSTRAINT IF EXISTS ck_ops_automation_job_type;
ALTER TABLE ops.automation_job ADD CONSTRAINT ck_ops_automation_job_type CHECK (job_type IN ('platform_download','full_etl','flow'));
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS schedule_type VARCHAR(16) NOT NULL DEFAULT 'manual';
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS schedule_config JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai';
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS retry_policy JSONB NOT NULL DEFAULT '{"max_attempts":1}'::jsonb;
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 21600;
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS default_profile_name VARCHAR(200);
ALTER TABLE ops.automation_flow DROP CONSTRAINT IF EXISTS ck_ops_automation_flow_schedule;
ALTER TABLE ops.automation_flow ADD CONSTRAINT ck_ops_automation_flow_schedule CHECK (schedule_type IN ('manual','daily'));
ALTER TABLE ops.automation_flow DROP CONSTRAINT IF EXISTS ck_ops_automation_flow_timeout;
ALTER TABLE ops.automation_flow ADD CONSTRAINT ck_ops_automation_flow_timeout CHECK (timeout_seconds BETWEEN 60 AND 86400);
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS flow_id UUID REFERENCES ops.automation_flow(flow_id) ON DELETE SET NULL;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS flow_version_id UUID REFERENCES ops.automation_flow_version(flow_version_id) ON DELETE SET NULL;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS resource_key VARCHAR(240);
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMPTZ;
UPDATE ops.automation_run
SET attempt_started_at=started_at
WHERE attempt_started_at IS NULL AND started_at IS NOT NULL
  AND resume_count=0;

ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS waiting_since TIMESTAMPTZ;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS resumed_at TIMESTAMPTZ;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS resume_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS resume_reason VARCHAR(120);
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS attention_acknowledged_at TIMESTAMPTZ;
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS attention_acknowledged_by VARCHAR(100);
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS attention_acknowledged_reason VARCHAR(500);
ALTER TABLE ops.automation_run DROP CONSTRAINT IF EXISTS ck_ops_automation_run_resume;
ALTER TABLE ops.automation_run ADD CONSTRAINT ck_ops_automation_run_resume CHECK (resume_count >= 0);
ALTER TABLE ops.automation_run ADD COLUMN IF NOT EXISTS input_context JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ops.automation_run DROP CONSTRAINT IF EXISTS ck_ops_automation_run_trigger;
ALTER TABLE ops.automation_run ADD CONSTRAINT ck_ops_automation_run_trigger CHECK (trigger_type IN ('manual','schedule','retry','test'));
ALTER TABLE ops.automation_job ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE ops.automation_flow ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ops_automation_run_schedule_key
    ON ops.automation_run(job_id, schedule_key) WHERE schedule_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ops_automation_flow_schedule
    ON ops.automation_flow(enabled, schedule_type, updated_at DESC) WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ops_automation_flow_version_flow
    ON ops.automation_flow_version(flow_id, version DESC);

CREATE TABLE IF NOT EXISTS ops.automation_resource_lock (
    resource_key VARCHAR(240) PRIMARY KEY,
    automation_run_id UUID NOT NULL UNIQUE REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    worker_id UUID NOT NULL,
    lock_state VARCHAR(16) NOT NULL DEFAULT 'running',
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_automation_resource_lock_state CHECK(lock_state IN ('running','paused'))
);

ALTER TABLE ops.automation_resource_lock
    ADD COLUMN IF NOT EXISTS lock_state VARCHAR(16) NOT NULL DEFAULT 'running';
ALTER TABLE ops.automation_resource_lock
    DROP CONSTRAINT IF EXISTS ck_ops_automation_resource_lock_state;
ALTER TABLE ops.automation_resource_lock
    ADD CONSTRAINT ck_ops_automation_resource_lock_state CHECK(lock_state IN ('running','paused'));

CREATE TABLE IF NOT EXISTS ops.automation_notification_policy (
    policy_code VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    event_types JSONB NOT NULL DEFAULT '["failed","needs_human","success_with_warnings"]'::jsonb,
    channel_type VARCHAR(24) NOT NULL DEFAULT 'feishu_relay',
    description VARCHAR(500),
    updated_by VARCHAR(100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_automation_notification_channel CHECK (channel_type IN ('feishu_relay'))
);

CREATE TABLE IF NOT EXISTS ops.automation_notification_outbox (
    notification_id BIGSERIAL PRIMARY KEY,
    automation_run_id UUID NOT NULL REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    event_key VARCHAR(80) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    CONSTRAINT uq_ops_automation_notification_event UNIQUE(automation_run_id,event_key),
    CONSTRAINT ck_ops_automation_notification_status CHECK (status IN ('pending','sent','failed')),
    CONSTRAINT ck_ops_automation_notification_attempt CHECK (attempt_count >= 0)
);

CREATE TABLE IF NOT EXISTS ops.automation_step_run (
    step_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_run_id UUID NOT NULL REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    platform_code VARCHAR(64),
    platform_name VARCHAR(100),
    company_code VARCHAR(64),
    company_name VARCHAR(200),
    shop_code VARCHAR(64),
    shop_name VARCHAR(200),
    profile_name VARCHAR(200),
    step_name VARCHAR(120) NOT NULL,
    module_name VARCHAR(160) NOT NULL,
    execution_lane VARCHAR(24) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    business_date_start DATE,
    business_date_end DATE,
    period_type VARCHAR(32),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    duration_seconds NUMERIC(18,3),
    exit_code INTEGER,
    output_summary TEXT,
    error_message TEXT,
    ingest_run_id UUID REFERENCES ops.ingest_run(run_id) ON DELETE SET NULL,
    etl_run_id UUID REFERENCES ops.etl_run(etl_run_id) ON DELETE SET NULL,
    verification_challenge_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_automation_step_sequence UNIQUE (automation_run_id, sequence_no),
    CONSTRAINT ck_ops_automation_step_sequence CHECK (sequence_no > 0),
    CONSTRAINT ck_ops_automation_step_lane CHECK (execution_lane IN ('overnight','interactive','etl')),
    CONSTRAINT ck_ops_automation_step_status CHECK (status IN ('queued','running','success','success_with_warnings','no_data','needs_human','failed','cancelled','skipped')),
    CONSTRAINT ck_ops_automation_step_attempt CHECK (attempt_count >= 0),
    CONSTRAINT ck_ops_automation_step_period CHECK (period_type IS NULL OR period_type IN ('day','date_range','rolling_30_days','month','unknown')),
    CONSTRAINT ck_ops_automation_step_dates CHECK (business_date_start IS NULL OR business_date_end IS NULL OR business_date_start <= business_date_end)
);


CREATE TABLE IF NOT EXISTS ops.automation_component_run (
    component_run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_component_run_id UUID REFERENCES ops.automation_component_run(component_run_id) ON DELETE SET NULL,
    automation_run_id UUID NOT NULL REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    step_run_id UUID NOT NULL REFERENCES ops.automation_step_run(step_run_id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    component_run_key UUID NOT NULL,
    component_code VARCHAR(120) NOT NULL,
    component_version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    component_name VARCHAR(160) NOT NULL,
    category VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    attempt_no INTEGER NOT NULL DEFAULT 1,
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    resume_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_type VARCHAR(100),
    error_message TEXT,
    page_url TEXT,
    screenshot_path TEXT,
    trace_path TEXT,
    verification_challenge_id UUID,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    duration_seconds NUMERIC(18,3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_automation_component_key UNIQUE (step_run_id, component_run_key),
    CONSTRAINT uq_ops_automation_component_sequence UNIQUE (step_run_id, sequence_no),
    CONSTRAINT ck_ops_automation_component_sequence CHECK (sequence_no > 0),
    CONSTRAINT ck_ops_automation_component_attempt CHECK (attempt_no > 0),
    CONSTRAINT ck_ops_automation_component_status CHECK (status IN ('running','success','failed','needs_human','cancelled','skipped'))
);

ALTER TABLE ops.automation_component_run
    ADD COLUMN IF NOT EXISTS parent_component_run_id UUID
    REFERENCES ops.automation_component_run(component_run_id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS ops.automation_component_event (
    component_event_id BIGSERIAL PRIMARY KEY,
    component_run_id UUID NOT NULL REFERENCES ops.automation_component_run(component_run_id) ON DELETE CASCADE,
    event_type VARCHAR(80) NOT NULL,
    message TEXT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops.automation_artifact (
    artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_run_id UUID NOT NULL REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    step_run_id UUID NOT NULL REFERENCES ops.automation_step_run(step_run_id) ON DELETE CASCADE,
    artifact_type VARCHAR(32) NOT NULL DEFAULT 'report_file',
    file_name VARCHAR(255) NOT NULL,
    relative_path TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    file_hash CHAR(64),
    report_type VARCHAR(64),
    business_date_start DATE,
    business_date_end DATE,
    ingest_file_task_id UUID REFERENCES ops.ingest_file_task(file_task_id) ON DELETE SET NULL,
    batch_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ops_automation_artifact_path UNIQUE (automation_run_id, step_run_id, relative_path),
    CONSTRAINT ck_ops_automation_artifact_type CHECK (artifact_type IN ('report_file','archive','summary')),
    CONSTRAINT ck_ops_automation_artifact_size CHECK (file_size_bytes >= 0),
    CONSTRAINT ck_ops_automation_artifact_dates CHECK (business_date_start IS NULL OR business_date_end IS NULL OR business_date_start <= business_date_end)
);

CREATE TABLE IF NOT EXISTS ops.automation_worker_heartbeat (
    worker_id UUID PRIMARY KEY,
    worker_name VARCHAR(100) NOT NULL,
    process_id INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'starting',
    current_run_id UUID REFERENCES ops.automation_run(automation_run_id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at TIMESTAMPTZ,
    CONSTRAINT ck_ops_automation_worker_status CHECK (status IN ('starting','idle','busy','stopped','failed'))
);

CREATE INDEX IF NOT EXISTS idx_ops_automation_flow_status ON ops.automation_flow(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_automation_run_status ON ops.automation_run(status, queued_at);
CREATE INDEX IF NOT EXISTS idx_ops_automation_run_business_date ON ops.automation_run(business_date DESC, status);
CREATE INDEX IF NOT EXISTS idx_ops_automation_step_run ON ops.automation_step_run(automation_run_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_ops_automation_step_daily ON ops.automation_step_run(platform_name, shop_name, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_automation_component_step ON ops.automation_component_run(step_run_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_ops_automation_component_code ON ops.automation_component_run(component_code, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_automation_component_event_run ON ops.automation_component_event(component_run_id, component_event_id);
CREATE INDEX IF NOT EXISTS idx_ops_automation_artifact_step ON ops.automation_artifact(step_run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ops_automation_worker_seen ON ops.automation_worker_heartbeat(status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_automation_run_waiting ON ops.automation_run(status, waiting_since) WHERE status='needs_human';
CREATE INDEX IF NOT EXISTS idx_ops_automation_run_attention ON ops.automation_run(updated_at DESC)
    WHERE attention_acknowledged_at IS NULL AND status IN ('failed','needs_human','success_with_warnings');
CREATE INDEX IF NOT EXISTS idx_ops_automation_notification_pending ON ops.automation_notification_outbox(status,next_attempt_at,notification_id);

INSERT INTO ops.automation_notification_policy(policy_code,enabled,event_types,channel_type,description,updated_by)
VALUES(
  'default',FALSE,'["failed","needs_human","success_with_warnings"]'::jsonb,'feishu_relay',
  '自动化运行通知；复用验证码转发机器人群聊，按平台范围匹配。默认关闭，避免升级后产生意外消息。','system'
)
ON CONFLICT(policy_code) DO NOTHING;

INSERT INTO ops.automation_flow_version(flow_id,version,flow_code,flow_name,execution_lane,definition,published_by,published_at)
SELECT flow_id,version,flow_code,flow_name,execution_lane,definition,COALESCE(updated_by,created_by,'system'),updated_at
FROM ops.automation_flow
WHERE status='published' AND deleted_at IS NULL
ON CONFLICT(flow_id,version) DO NOTHING;

INSERT INTO ops.automation_job(job_code,job_name,job_type,enabled,execution_lane,schedule_type,schedule_config,timezone,retry_policy,timeout_seconds,description,created_by,updated_by)
VALUES
('platform_download_overnight','平台报表下载 / overnight','platform_download',TRUE,'overnight','daily','{"times":["05:00"]}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'复用 DownloadController 执行凌晨通道；profile 与 step 来自白名单配置。','system','system'),
('platform_download_interactive','平台报表下载 / interactive','platform_download',TRUE,'interactive','daily','{"times":["09:20"]}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'复用 DownloadController 执行人工可交互通道；同日检查点可续跑。','system','system'),
('full_etl','全量 ETL 刷新','full_etl',TRUE,'etl','manual','{}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'通过既有 FileIngestService 创建全量 ETL 运行；默认保留现有 nightly scheduler，避免双重调度，管理员可迁移后再启用。','system','system'),
('flow_overnight','自定义组件 Flow / overnight','flow',TRUE,'overnight','manual','{}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'Flow Studio 发布版本的受控 overnight 执行入口；必须携带 flow_id 与 profile_name。','system','system'),
('flow_interactive','自定义组件 Flow / interactive','flow',TRUE,'interactive','manual','{}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'Flow Studio 发布版本的受控 interactive 执行入口；必须携带 flow_id 与 profile_name。','system','system'),
('flow_etl','自定义组件 Flow / etl','flow',TRUE,'etl','manual','{}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'Flow Studio 发布版本的受控 etl 执行入口；必须携带 flow_id 与 profile_name。','system','system')
ON CONFLICT (job_code) DO UPDATE SET
    job_name=EXCLUDED.job_name,
    job_type=EXCLUDED.job_type,
    execution_lane=EXCLUDED.execution_lane,
    updated_at=NOW();

INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
VALUES('module.automation','自动化工作台','module','automation',NULL,'/automation/',35,TRUE,NOW())
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,route_path=EXCLUDED.route_path,is_active=TRUE,updated_at=NOW();

WITH resources(resource_code,resource_name,resource_type,parent_code,route_path,display_order) AS (
    VALUES
    ('automation.workbench.view','系统运行','page','module.automation','/automation/#runtime',10),
    ('automation.jobs.view','任务调度','page','module.automation','/automation/#schedules',20),
    ('automation.jobs.manage','管理自动化任务','action','automation.jobs.view','/api/automation/jobs',21),
    ('automation.flows.view','流程编排','page','module.automation','/automation/#flow-studio',25),
    ('automation.flows.manage','管理流程编排','action','automation.flows.view','/api/automation/flows',26),
    ('automation.flows.execute','执行流程','action','automation.flows.view','/api/automation/flows/{id}/run',27),
    ('automation.runs.view','运行中心 · 执行记录','page','module.automation','/automation/#runs',30),
    ('automation.runs.execute','立即运行','action','automation.runs.view','/api/automation/jobs/{id}/run',31),
    ('automation.runs.retry','重试执行','action','automation.runs.view','/api/automation/runs/{id}/retry',32),
    ('automation.results.view','报表任务','page','module.automation','/automation/#reports',5)
)
INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT r.resource_code,r.resource_name,r.resource_type,'automation',p.resource_id,r.route_path,r.display_order,TRUE,NOW()
FROM resources r JOIN iam.permission_resource p ON p.resource_code=r.parent_code
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,is_active=TRUE,updated_at=NOW();

WITH actions(resource_code,resource_name,parent_code,route_path,display_order) AS (
    VALUES
    ('automation.jobs.manage','管理自动化任务','automation.jobs.view','/api/automation/jobs',21),
    ('automation.flows.manage','管理流程编排','automation.flows.view','/api/automation/flows',26),
    ('automation.flows.execute','执行流程','automation.flows.view','/api/automation/flows/{id}/run',27),
    ('automation.runs.execute','立即运行','automation.runs.view','/api/automation/jobs/{id}/run',31),
    ('automation.runs.retry','重试执行','automation.runs.view','/api/automation/runs/{id}/retry',32)
)
INSERT INTO iam.permission_resource(resource_code,resource_name,resource_type,module_code,parent_resource_id,route_path,display_order,is_active,updated_at)
SELECT a.resource_code,a.resource_name,'action','automation',p.resource_id,a.route_path,a.display_order,TRUE,NOW()
FROM actions a JOIN iam.permission_resource p ON p.resource_code=a.parent_code
ON CONFLICT(resource_code) DO UPDATE SET resource_name=EXCLUDED.resource_name,parent_resource_id=EXCLUDED.parent_resource_id,route_path=EXCLUDED.route_path,is_active=TRUE,updated_at=NOW();

INSERT INTO iam.role_permission(role_id,resource_id,granted_at)
SELECT role.role_id,resource.resource_id,NOW()
FROM iam.role role CROSS JOIN iam.permission_resource resource
WHERE role.role_code='super_admin' AND resource.module_code='automation' AND resource.is_active
ON CONFLICT(role_id,resource_id) DO NOTHING;


INSERT INTO ops.automation_flow(flow_code,flow_name,description,status,version,execution_lane,definition,created_by,updated_by)
VALUES(
  'jd.order.reference',
  '京东订单日报 · 原子组件参考 Flow',
  'Flow Studio 可执行参考：Cloak → CDP → 登录 → 导出 → 等待 → 下载 → 飞书文件密码 → 解压校验归档 → 关闭 Profile。',
  'published',1,'interactive',
  '{
    "variables":{"date_mode":"business_date"},
    "nodes":[
      {"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"login","component_code":"jd.ensure_login","name":"京东 · 检查登录态","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"open","component_code":"jd.order.open_export","name":"京东订单 · 打开导出页","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"date","component_code":"report.date_range.set","name":"设置业务日期范围","x":860,"y":250,"enabled":true,"timeout_seconds":30,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"export","component_code":"jd.order.create_export","name":"京东订单 · 创建导出","x":600,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"wait","component_code":"report.wait_export_ready","name":"等待导出任务就绪","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"download","component_code":"file.download","name":"下载报表文件","x":80,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"password","component_code":"human.verification.wait","name":"等待京东文件密码","x":80,"y":420,"enabled":true,"timeout_seconds":300,"retry_count":1,"on_error":"needs_human","condition":"","config":{"challenge_type":"archive_password"}},
      {"id":"extract","component_code":"file.archive.extract","name":"解压 / 解密 / 校验 / 归档","x":340,"y":420,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}
    ],
    "edges":[
      {"source":"cloak","target":"cdp"},{"source":"cdp","target":"login"},{"source":"login","target":"open"},{"source":"open","target":"date"},{"source":"date","target":"export"},{"source":"export","target":"wait"},{"source":"wait","target":"download"},{"source":"download","target":"password"},{"source":"password","target":"extract"},{"source":"extract","target":"stop"}
    ]
  }'::jsonb,
  'system','system'
)
ON CONFLICT(flow_code) DO NOTHING;

INSERT INTO ops.automation_flow(flow_code,flow_name,description,status,version,execution_lane,definition,created_by,updated_by)
VALUES
(
  'xhs.order.reference',
  '小红书订单 · 原子组件参考 Flow',
  '无验证码参考 Flow：Cloak → CDP → 工作台 → 订单管理 → 日期 → 查询 → 导出 → 校验 → 归档 → 关闭 Profile。',
  'published',1,'interactive',
  '{
    "variables":{},
    "nodes":[
      {"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":60,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":330,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"home","component_code":"xhs.order.open_home","name":"小红书 · 打开工作台","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"manage","component_code":"xhs.order.open_management","name":"小红书订单 · 打开管理页","x":870,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"date","component_code":"xhs.order.set_date","name":"小红书订单 · 设置日期","x":870,"y":260,"enabled":true,"timeout_seconds":45,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"query","component_code":"xhs.order.query","name":"小红书订单 · 查询","x":600,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"export","component_code":"xhs.order.export","name":"小红书订单 · 导出","x":330,"y":260,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":60,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"archive","component_code":"report.archive","name":"标准归档","x":330,"y":440,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":440,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}
    ],
    "edges":[
      {"source":"cloak","target":"cdp"},{"source":"cdp","target":"home"},{"source":"home","target":"manage"},{"source":"manage","target":"date"},{"source":"date","target":"query"},{"source":"query","target":"export"},{"source":"export","target":"validate"},{"source":"validate","target":"archive"},{"source":"archive","target":"stop"}
    ]
  }'::jsonb,
  'system','system'
),
(
  'xhs.fund.reference',
  '小红书资金 · 原子组件参考 Flow',
  '无验证码参考 Flow：Cloak → CDP → 资金账单 → 日/月模式 → 最新账单 → 下载 → 校验 → 归档 → 关闭 Profile。',
  'published',1,'interactive',
  '{
    "variables":{},
    "nodes":[
      {"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":60,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":330,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"open","component_code":"xhs.report.open","name":"小红书 · 打开资金账单","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{"report_type":"fund"}},
      {"id":"mode","component_code":"xhs.report.mode.select","name":"小红书资金 · 选择日账单","x":870,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},
      {"id":"latest","component_code":"xhs.report.latest","name":"小红书资金 · 定位最新账单","x":870,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"download","component_code":"xhs.report.download","name":"小红书资金 · 下载","x":600,"y":260,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":330,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"archive","component_code":"report.archive","name":"标准归档","x":60,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":330,"y":440,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}
    ],
    "edges":[
      {"source":"cloak","target":"cdp"},{"source":"cdp","target":"open"},{"source":"open","target":"mode"},{"source":"mode","target":"latest"},{"source":"latest","target":"download"},{"source":"download","target":"validate"},{"source":"validate","target":"archive"},{"source":"archive","target":"stop"}
    ]
  }'::jsonb,
  'system','system'
),
(
  'xhs.settlement.reference',
  '小红书结算 · 原子组件参考 Flow',
  '无验证码参考 Flow：Cloak → CDP → 结算账单 → 日/月模式 → 最新账单 → 下载 → 校验 → 归档 → 关闭 Profile。',
  'published',1,'interactive',
  '{
    "variables":{},
    "nodes":[
      {"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":60,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":330,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"open","component_code":"xhs.report.open","name":"小红书 · 打开结算账单","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{"report_type":"settlement"}},
      {"id":"mode","component_code":"xhs.report.mode.select","name":"小红书结算 · 选择日账单","x":870,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},
      {"id":"latest","component_code":"xhs.report.latest","name":"小红书结算 · 定位最新账单","x":870,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"download","component_code":"xhs.report.download","name":"小红书结算 · 下载","x":600,"y":260,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},
      {"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":330,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"archive","component_code":"report.archive","name":"标准归档","x":60,"y":260,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},
      {"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":330,"y":440,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}
    ],
    "edges":[
      {"source":"cloak","target":"cdp"},{"source":"cdp","target":"open"},{"source":"open","target":"mode"},{"source":"mode","target":"latest"},{"source":"latest","target":"download"},{"source":"download","target":"validate"},{"source":"validate","target":"archive"},{"source":"archive","target":"stop"}
    ]
  }'::jsonb,
  'system','system'
)
ON CONFLICT(flow_code) DO NOTHING;


WITH flow_code_rename(old_code,new_code) AS (
    VALUES
      ('douyin.order.workflow.reference','douyin.order.atomic.reference'),
      ('douyin.fund.workflow.reference','douyin.fund.atomic.reference'),
      ('douyin.settlement.workflow.reference','douyin.settlement.atomic.reference'),
      ('qianchuan.promotion.workflow.reference','qianchuan.promotion.atomic.reference'),
      ('jd.settlement.workflow.reference','jd.settlement.atomic.reference'),
      ('jd.fund.workflow.reference','jd.fund.atomic.reference'),
      ('jd.promotion.workflow.reference','jd.promotion.atomic.reference'),
      ('pinduoduo.order.workflow.reference','pinduoduo.order.atomic.reference'),
      ('pinduoduo.settlement.workflow.reference','pinduoduo.settlement.atomic.reference'),
      ('pinduoduo.promotion.workflow.reference','pinduoduo.promotion.atomic.reference'),
      ('kuaishou.order.workflow.reference','kuaishou.order.atomic.reference'),
      ('kuaishou.fund.workflow.reference','kuaishou.fund.atomic.reference'),
      ('kuaishou.settlement.workflow.reference','kuaishou.settlement.atomic.reference'),
      ('tmall.order.workflow.reference','tmall.order.atomic.reference'),
      ('tmall.aggregate_fund.workflow.reference','tmall.aggregate_fund.atomic.reference'),
      ('tmall.alipay.workflow.reference','tmall.alipay.atomic.reference'),
      ('tmall.union.workflow.reference','tmall.union.atomic.reference'),
      ('tmall.wanxiangtai.workflow.reference','tmall.wanxiangtai.atomic.reference')
)
UPDATE ops.automation_flow AS f
SET flow_code=r.new_code, updated_at=NOW()
FROM flow_code_rename AS r
WHERE f.flow_code=r.old_code
  AND NOT EXISTS (
      SELECT 1 FROM ops.automation_flow existing WHERE existing.flow_code=r.new_code
  );

DELETE FROM ops.automation_flow
WHERE flow_code='jd.order.workflow.reference';

WITH atomic_reference_flows(flow_code,flow_name,description,status,definition) AS (
    VALUES
      (
        'douyin.order.atomic.reference',
        '抖音订单 · 原子流程测试',
        '真实原子流程：打开订单 → 筛选 → 查询 → 导出 → 等待 → 短信验证码/下载 → 解压/文件密码 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"douyin.order.open_page","name":"抖音订单 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"filter","component_code":"douyin.order.prepare_filters","name":"抖音订单 · 展开筛选","x":860,"y":80,"enabled":true,"timeout_seconds":45,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"query","component_code":"douyin.order.query","name":"抖音订单 · 查询","x":860,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"douyin.order.create_export","name":"抖音订单 · 创建导出","x":600,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"{{douyin_order_has_data}}","config":{}},{"id":"wait","component_code":"douyin.order.wait_ready","name":"抖音订单 · 等待导出就绪","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"{{douyin_order_has_data}}","config":{}},{"id":"verify","component_code":"douyin.order.download_verify","name":"抖音订单 · 短信验证码 / 下载","x":80,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":0,"on_error":"stop","condition":"{{douyin_order_has_data}}","config":{}},{"id":"extract","component_code":"douyin.order.extract","name":"抖音订单 · 解压 / 文件密码","x":80,"y":420,"enabled":true,"timeout_seconds":300,"retry_count":0,"on_error":"stop","condition":"{{douyin_order_has_data}}","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":340,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"{{douyin_order_has_data}}","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":600,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":860,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":590,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"filter","source_port":"right","target_port":"left"},{"source":"filter","target":"query","source_port":"right","target_port":"left"},{"source":"query","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"verify","source_port":"right","target_port":"left"},{"source":"verify","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'douyin.fund.atomic.reference',
        '抖音资金 · 原子流程测试',
        '真实原子流程：打开资金账单 → 日期 → 生成 → 等待 → 下载 → 标准归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"douyin.bill.open","name":"抖音资金 · 打开账单","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{"report":"资金","mode":"day"}},{"id":"date","component_code":"douyin.bill.set_date","name":"抖音资金 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"generate","component_code":"douyin.bill.generate","name":"抖音资金 · 生成报表","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"douyin.bill.wait_ready","name":"抖音资金 · 等待报表就绪","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"douyin.bill.download","name":"抖音资金 · 下载报表","x":340,"y":250,"enabled":true,"timeout_seconds":240,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":340,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"generate","source_port":"right","target_port":"left"},{"source":"generate","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'douyin.settlement.atomic.reference',
        '抖音结算 · 原子流程测试',
        '真实原子流程：打开结算账单 → 日期 → 生成 → 等待 → 下载 → 标准归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"douyin.bill.open","name":"抖音结算 · 打开账单","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{"report":"结算","mode":"day"}},{"id":"date","component_code":"douyin.bill.set_date","name":"抖音结算 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"generate","component_code":"douyin.bill.generate","name":"抖音结算 · 生成报表","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"douyin.bill.wait_ready","name":"抖音结算 · 等待报表就绪","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"douyin.bill.download","name":"抖音结算 · 下载报表","x":340,"y":250,"enabled":true,"timeout_seconds":240,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":340,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"generate","source_port":"right","target_port":"left"},{"source":"generate","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'qianchuan.promotion.atomic.reference',
        '千川推广费 · 原子流程测试',
        '真实原子流程：打开千川财务 → 日结报表 → 等待最新记录 → 生成 CSV → 标准归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"finance","component_code":"qianchuan.finance.open","name":"千川 · 打开财务页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"daily","component_code":"qianchuan.daily.open","name":"千川 · 打开日结报表","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"qianchuan.daily.wait","name":"千川 · 等待最新日结","x":860,"y":250,"enabled":true,"timeout_seconds":300,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"file","component_code":"qianchuan.daily.materialize","name":"千川 · 生成 CSV 文件","x":600,"y":250,"enabled":true,"timeout_seconds":30,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":340,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":250,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":80,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":340,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"finance","source_port":"right","target_port":"left"},{"source":"finance","target":"daily","source_port":"right","target_port":"left"},{"source":"daily","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"file","source_port":"right","target_port":"left"},{"source":"file","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'jd.order.reference',
        '京东订单日报 · 原子组件参考 Flow',
        '真实原子流程：登录 → 导出页 → 日期 → 创建导出 → 等待 → 下载 → 文件密码 → 解压解密 → 校验 → 归档。',
        'published',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"login","component_code":"jd.ensure_login","name":"京东 · 检查登录态","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"jd.order.open_export","name":"京东订单 · 打开导出页","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"report.date_range.set","name":"设置业务日期范围","x":860,"y":250,"enabled":true,"timeout_seconds":30,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"jd.order.create_export","name":"京东订单 · 创建导出","x":600,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"report.wait_export_ready","name":"等待导出任务就绪","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"file.download","name":"下载订单 ZIP","x":80,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"password","component_code":"human.verification.wait","name":"等待京东文件密码","x":80,"y":420,"enabled":true,"timeout_seconds":300,"retry_count":1,"on_error":"needs_human","condition":"","config":{"challenge_type":"archive_password"}},{"id":"extract","component_code":"file.archive.extract","name":"解压 / 解密归档文件","x":340,"y":420,"enabled":true,"timeout_seconds":180,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":600,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":860,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":860,"y":590,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":590,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":340,"y":590,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"login","source_port":"right","target_port":"left"},{"source":"login","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"password","source_port":"right","target_port":"left"},{"source":"password","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"validate","source_port":"right","target_port":"left"},{"source":"validate","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'jd.settlement.atomic.reference',
        '京东结算 · 原子流程测试',
        '真实原子流程：登录 → 日账单 → 定位最新 → 下载 → 提取 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"login","component_code":"jd.session.ensure_login","name":"京东 · 建立登录页面","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"mode","component_code":"jd.settlement.select_mode","name":"京东结算 · 选择日账单","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"locate","component_code":"jd.settlement.locate","name":"京东结算 · 定位最新账单","x":860,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"jd.settlement.download","name":"京东结算 · 下载明细","x":600,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"extract","component_code":"jd.settlement.extract","name":"京东结算 · 提取报表","x":340,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":340,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"login","source_port":"right","target_port":"left"},{"source":"login","target":"mode","source_port":"right","target_port":"left"},{"source":"mode","target":"locate","source_port":"right","target_port":"left"},{"source":"locate","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'jd.fund.atomic.reference',
        '京东资金 · 原子流程测试',
        '真实原子流程：登录 → 日期 → 创建导出 → 等待下载 → 提取 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"login","component_code":"jd.session.ensure_login","name":"京东 · 建立登录页面","x":600,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"jd.fund.set_date","name":"京东资金 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"jd.fund.create_export","name":"京东资金 · 创建导出","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"jd.fund.wait_download","name":"京东资金 · 等待并下载","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"extract","component_code":"jd.fund.extract","name":"京东资金 · 提取报表","x":340,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":340,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"login","source_port":"right","target_port":"left"},{"source":"login","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'jd.promotion.atomic.reference',
        '京东推广费 · 原子流程测试',
        '京东联盟与京准通分别执行打开、日期、生成、等待、下载、归档；两份成果最后可统一 API 上传。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"union_open","component_code":"jd.promotion.open","name":"京东联盟 · 打开报表","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{"report_key":"union"}},{"id":"union_date","component_code":"jd.promotion.set_date","name":"京东联盟 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"union_export","component_code":"jd.promotion.create_export","name":"京东联盟 · 创建报表","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"union_wait","component_code":"jd.promotion.wait_ready","name":"京东联盟 · 等待报表","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"union_download","component_code":"jd.promotion.download","name":"京东联盟 · 下载报表","x":340,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"union_archive","component_code":"report.archive","name":"京东联盟 · 标准归档","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"tong_open","component_code":"jd.promotion.open","name":"京准通 · 打开报表","x":80,"y":420,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{"report_key":"tong"}},{"id":"tong_date","component_code":"jd.promotion.set_date","name":"京准通 · 设置日期","x":340,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"tong_export","component_code":"jd.promotion.create_export","name":"京准通 · 创建报表","x":600,"y":420,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"tong_wait","component_code":"jd.promotion.wait_ready","name":"京准通 · 等待报表","x":860,"y":420,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"tong_download","component_code":"jd.promotion.download","name":"京准通 · 下载报表","x":860,"y":590,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"tong_archive","component_code":"report.archive","name":"京准通 · 标准归档","x":600,"y":590,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":590,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":80,"y":590,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":80,"y":760,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"union_open","source_port":"right","target_port":"left"},{"source":"union_open","target":"union_date","source_port":"right","target_port":"left"},{"source":"union_date","target":"union_export","source_port":"right","target_port":"left"},{"source":"union_export","target":"union_wait","source_port":"right","target_port":"left"},{"source":"union_wait","target":"union_download","source_port":"right","target_port":"left"},{"source":"union_download","target":"union_archive","source_port":"right","target_port":"left"},{"source":"union_archive","target":"tong_open","source_port":"right","target_port":"left"},{"source":"tong_open","target":"tong_date","source_port":"right","target_port":"left"},{"source":"tong_date","target":"tong_export","source_port":"right","target_port":"left"},{"source":"tong_export","target":"tong_wait","source_port":"right","target_port":"left"},{"source":"tong_wait","target":"tong_download","source_port":"right","target_port":"left"},{"source":"tong_download","target":"tong_archive","source_port":"right","target_port":"left"},{"source":"tong_archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'pinduoduo.order.atomic.reference',
        '拼多多订单 · 原子流程测试',
        '真实原子流程：打开订单 → 日期 → 查询 → 创建导出 → 等待 → 下载 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"pinduoduo.order.open","name":"拼多多订单 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"pinduoduo.order.set_date","name":"拼多多订单 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"query","component_code":"pinduoduo.order.query","name":"拼多多订单 · 查询","x":860,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"pinduoduo.order.create_export","name":"拼多多订单 · 创建导出","x":600,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"pinduoduo.order.wait_ready","name":"拼多多订单 · 等待导出","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"pinduoduo.order.download","name":"拼多多订单 · 下载报表","x":80,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"query","source_port":"right","target_port":"left"},{"source":"query","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'pinduoduo.settlement.atomic.reference',
        '拼多多结算 · 原子流程测试',
        '真实原子流程：对账中心 → 日期 → 导出 → 等待 → 下载 ZIP → 提取 CSV → 校验 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"pinduoduo.settlement.open","name":"拼多多结算 · 打开对账中心","x":600,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"pinduoduo.settlement.set_date","name":"拼多多结算 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"pinduoduo.settlement.create_export","name":"拼多多结算 · 创建导出","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"pinduoduo.settlement.wait_ready","name":"拼多多结算 · 等待导出","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"pinduoduo.settlement.download","name":"拼多多结算 · 下载账单","x":340,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"extract","component_code":"pinduoduo.settlement.extract","name":"拼多多结算 · 提取 CSV","x":80,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":340,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":600,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":860,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":590,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"validate","source_port":"right","target_port":"left"},{"source":"validate","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'pinduoduo.promotion.atomic.reference',
        '拼多多推广费 · 原子流程测试',
        '真实原子流程：推广流水 → 日期 → 现金/支出筛选 → 查询 → 下载 → 校验 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"pinduoduo.promotion.open","name":"拼多多推广费 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"pinduoduo.promotion.set_date","name":"拼多多推广费 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"filters","component_code":"pinduoduo.promotion.apply_filters","name":"拼多多推广费 · 设置筛选","x":860,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"query","component_code":"pinduoduo.promotion.query","name":"拼多多推广费 · 查询","x":600,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"pinduoduo.promotion.download","name":"拼多多推广费 · 下载明细","x":340,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":80,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"filters","source_port":"right","target_port":"left"},{"source":"filters","target":"query","source_port":"right","target_port":"left"},{"source":"query","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"validate","source_port":"right","target_port":"left"},{"source":"validate","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'kuaishou.order.atomic.reference',
        '快手订单 · 原子流程测试',
        '真实原子流程：订单页 → 日期 → 查询 → 创建导出/短信验证码 → 等待 → 文件提取码/下载 → 解密 → 校验 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"kuaishou.order.open_page","name":"快手订单 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"kuaishou.order.set_date","name":"快手订单 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"query","component_code":"kuaishou.order.query","name":"快手订单 · 查询","x":860,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"kuaishou.order.create_export","name":"快手订单 · 创建导出 / 短信验证码","x":600,"y":250,"enabled":true,"timeout_seconds":600,"retry_count":0,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"wait","component_code":"kuaishou.order.wait_ready","name":"快手订单 · 等待导出","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"password","component_code":"kuaishou.order.download_password","name":"快手订单 · 文件提取码 / 下载","x":80,"y":250,"enabled":true,"timeout_seconds":600,"retry_count":0,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"decrypt","component_code":"kuaishou.order.decrypt","name":"快手订单 · 解密 XLSX","x":80,"y":420,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"validate","component_code":"report.validate.schema","name":"标准报表校验","x":340,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":600,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"{{ks_order_has_data}}","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":860,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":860,"y":590,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":590,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"query","source_port":"right","target_port":"left"},{"source":"query","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"password","source_port":"right","target_port":"left"},{"source":"password","target":"decrypt","source_port":"right","target_port":"left"},{"source":"decrypt","target":"validate","source_port":"right","target_port":"left"},{"source":"validate","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'kuaishou.fund.atomic.reference',
        '快手资金 · 原子流程测试',
        '真实原子流程：打开资金账单 → 定位 → 导出 → 等待 → 下载 → 提取 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"kuaishou.fund.open","name":"快手资金 · 打开账单页","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"locate","component_code":"kuaishou.fund.locate_bill","name":"快手资金 · 定位最新账单","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"kuaishou.fund.create_export","name":"快手资金 · 导出账单","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"kuaishou.fund.wait_ready","name":"快手资金 · 等待导出记录","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"kuaishou.fund.download","name":"快手资金 · 下载账单","x":340,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"extract","component_code":"kuaishou.fund.extract","name":"快手资金 · 提取报表","x":80,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"locate","source_port":"right","target_port":"left"},{"source":"locate","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'kuaishou.settlement.atomic.reference',
        '快手结算 · 原子流程测试',
        '真实原子流程：打开结算 → 日期 → 创建导出 → 等待 → 下载 → 提取 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"kuaishou.settlement.open","name":"快手结算 · 打开账单页","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"kuaishou.settlement.set_date","name":"快手结算 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"kuaishou.settlement.create_export","name":"快手结算 · 创建导出","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"kuaishou.settlement.wait_ready","name":"快手结算 · 等待导出","x":600,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"{{ks_settlement_has_data}}","config":{}},{"id":"download","component_code":"kuaishou.settlement.download","name":"快手结算 · 下载账单","x":340,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"{{ks_settlement_has_data}}","config":{}},{"id":"extract","component_code":"kuaishou.settlement.extract","name":"快手结算 · 提取报表","x":80,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"{{ks_settlement_has_data}}","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"{{ks_settlement_has_data}}","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'tmall.order.atomic.reference',
        '天猫订单 · 原子流程测试',
        '真实原子流程：订单页 → 日期 → 查询 → 创建导出 → 等待 → 下载 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"tmall.order.open_page","name":"天猫订单 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"date","component_code":"tmall.order.set_date","name":"天猫订单 · 设置日期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"query","component_code":"tmall.order.search","name":"天猫订单 · 查询","x":860,"y":250,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"export","component_code":"tmall.order.create_export","name":"天猫订单 · 创建导出","x":600,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"wait","component_code":"tmall.order.wait_ready","name":"天猫订单 · 等待导出","x":340,"y":250,"enabled":true,"timeout_seconds":900,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"tmall.order.download","name":"天猫订单 · 下载报表","x":80,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":80,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":600,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":860,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"date","source_port":"right","target_port":"left"},{"source":"date","target":"query","source_port":"right","target_port":"left"},{"source":"query","target":"export","source_port":"right","target_port":"left"},{"source":"export","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'tmall.aggregate_fund.atomic.reference',
        '天猫聚合资金 · 原子流程测试',
        '真实原子流程：登录并打开聚合资金 → 日账单 → 定位 → 下载 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"tmall.aggregate_fund.open","name":"天猫聚合资金 · 打开页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"mode","component_code":"tmall.aggregate_fund.select_mode","name":"天猫聚合资金 · 选择日汇总","x":860,"y":80,"enabled":true,"timeout_seconds":45,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"locate","component_code":"tmall.aggregate_fund.locate","name":"天猫聚合资金 · 定位最新账单","x":860,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"tmall.aggregate_fund.download","name":"天猫聚合资金 · 下载明细","x":600,"y":250,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":340,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":80,"y":250,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":80,"y":420,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":340,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"mode","source_port":"right","target_port":"left"},{"source":"mode","target":"locate","source_port":"right","target_port":"left"},{"source":"locate","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'tmall.alipay.atomic.reference',
        '天猫支付宝资金 · 原子流程测试',
        '真实原子流程：天猫会话 → 账户信息 → 支付宝 → 账单下载 → 日模式 → 等待 → 下载 ZIP → 提取 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"session","component_code":"tmall.session.open","name":"天猫 · 获取业务页面","x":600,"y":80,"enabled":true,"timeout_seconds":120,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"account","component_code":"tmall.alipay.open_account","name":"天猫支付宝资金 · 打开账户信息","x":860,"y":80,"enabled":true,"timeout_seconds":90,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"alipay","component_code":"tmall.alipay.open_page","name":"天猫支付宝资金 · 打开支付宝","x":860,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"bill","component_code":"tmall.alipay.open_bill","name":"天猫支付宝资金 · 打开账单下载","x":600,"y":250,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"mode","component_code":"tmall.alipay.select_mode","name":"天猫支付宝资金 · 选择日账单","x":340,"y":250,"enabled":true,"timeout_seconds":45,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"wait","component_code":"tmall.alipay.wait_ready","name":"天猫支付宝资金 · 等待账单","x":80,"y":250,"enabled":true,"timeout_seconds":300,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"tmall.alipay.download","name":"天猫支付宝资金 · 下载 ZIP","x":80,"y":420,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"extract","component_code":"tmall.alipay.extract","name":"天猫支付宝资金 · 提取明细","x":340,"y":420,"enabled":true,"timeout_seconds":120,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":600,"y":420,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":860,"y":420,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":860,"y":590,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":600,"y":590,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"session","source_port":"right","target_port":"left"},{"source":"session","target":"account","source_port":"right","target_port":"left"},{"source":"account","target":"alipay","source_port":"right","target_port":"left"},{"source":"alipay","target":"bill","source_port":"right","target_port":"left"},{"source":"bill","target":"mode","source_port":"right","target_port":"left"},{"source":"mode","target":"wait","source_port":"right","target_port":"left"},{"source":"wait","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"extract","source_port":"right","target_port":"left"},{"source":"extract","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'tmall.union.atomic.reference',
        '淘宝联盟推广费 · 原子流程测试',
        '真实原子流程：打开阿里妈妈 → 选择昨日 → 下载/复用报表 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"tmall.union.open","name":"淘宝联盟推广费 · 打开报表","x":600,"y":80,"enabled":true,"timeout_seconds":150,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"period","component_code":"tmall.union.select_period","name":"淘宝联盟推广费 · 选择周期","x":860,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"download","component_code":"tmall.union.download","name":"淘宝联盟推广费 · 下载报表","x":860,"y":250,"enabled":true,"timeout_seconds":300,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":600,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":340,"y":250,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":80,"y":250,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":80,"y":420,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"period","source_port":"right","target_port":"left"},{"source":"period","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      ),
      (
        'tmall.wanxiangtai.atomic.reference',
        '万相台推广费 · 原子流程测试',
        '真实原子流程：按日周期打开万相台 → 下载现金明细 → 归档。',
        'draft',
        '{"variables":{},"nodes":[{"id":"cloak","component_code":"cloak.profile.start","name":"启动 / 复用 Cloak Profile","x":80,"y":80,"enabled":true,"timeout_seconds":60,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"cdp","component_code":"browser.connect.cdp","name":"连接 CDP Browser","x":340,"y":80,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"stop","condition":"","config":{}},{"id":"open","component_code":"tmall.wanxiangtai.open","name":"万相台推广费 · 打开报表","x":600,"y":80,"enabled":true,"timeout_seconds":150,"retry_count":0,"on_error":"stop","condition":"","config":{"mode":"day"}},{"id":"download","component_code":"tmall.wanxiangtai.download","name":"万相台推广费 · 下载报表","x":860,"y":80,"enabled":true,"timeout_seconds":180,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"archive","component_code":"report.archive","name":"标准归档","x":860,"y":250,"enabled":true,"timeout_seconds":60,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"api","component_code":"ingest.submit","name":"API 上传 / FileIngest","x":600,"y":250,"enabled":true,"timeout_seconds":1800,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"etl","component_code":"etl.trigger","name":"触发受影响 ETL","x":340,"y":250,"enabled":true,"timeout_seconds":3600,"retry_count":0,"on_error":"stop","condition":"","config":{}},{"id":"stop","component_code":"cloak.profile.stop","name":"关闭 Cloak Profile","x":80,"y":250,"enabled":true,"timeout_seconds":30,"retry_count":1,"on_error":"continue","condition":"","config":{}}],"edges":[{"source":"cloak","target":"cdp","source_port":"right","target_port":"left"},{"source":"cdp","target":"open","source_port":"right","target_port":"left"},{"source":"open","target":"download","source_port":"right","target_port":"left"},{"source":"download","target":"archive","source_port":"right","target_port":"left"},{"source":"archive","target":"api","source_port":"right","target_port":"left"},{"source":"api","target":"etl","source_port":"right","target_port":"left"},{"source":"etl","target":"stop","source_port":"right","target_port":"left"}]}'::jsonb
      )
)
INSERT INTO ops.automation_flow(
    flow_code,flow_name,description,status,version,execution_lane,definition,created_by,updated_by
)
SELECT
    flow_code,flow_name,description,status,1,'interactive',definition,'system','system'
FROM atomic_reference_flows
ON CONFLICT(flow_code) DO UPDATE SET
    flow_name=EXCLUDED.flow_name,
    description=EXCLUDED.description,
    definition=EXCLUDED.definition,
    updated_by='system',
    updated_at=NOW();


UPDATE ops.automation_flow AS f
SET definition = jsonb_set(
        f.definition,
        '{nodes}',
        COALESCE((
            SELECT jsonb_agg(
                CASE
                    WHEN node->>'component_code' ~ '^xhs\.(order|report)\.archive$'
                    THEN node || jsonb_build_object(
                        'component_code','report.archive',
                        'name','标准归档',
                        'config',COALESCE(node->'config','{}'::jsonb)
                    )
                    WHEN node->>'component_code' ~ '^xhs\.(order|report)\.validate$'
                    THEN node || jsonb_build_object(
                        'component_code','report.validate.schema',
                        'name','标准报表校验',
                        'config',COALESCE(node->'config','{}'::jsonb)
                    )
                    ELSE node
                END
                ORDER BY ord
            )
            FROM jsonb_array_elements(COALESCE(f.definition->'nodes','[]'::jsonb)) WITH ORDINALITY AS item(node, ord)
        ), '[]'::jsonb)
    ),
    updated_at = NOW()
WHERE f.deleted_at IS NULL
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(COALESCE(f.definition->'nodes','[]'::jsonb)) AS n(node)
      WHERE node->>'component_code' ~ '^xhs\.(order|report)\.(archive|validate)$'
  );


DO $$
DECLARE
    rec RECORD;
    nodes JSONB;
    edges JSONB;
    max_x INTEGER;
    stop_id TEXT;
    stop_y INTEGER;
    ingest_id TEXT;
    etl_id TEXT;
BEGIN
    FOR rec IN
        SELECT flow_id, definition
        FROM ops.automation_flow
        WHERE deleted_at IS NULL
    LOOP
        nodes := COALESCE(rec.definition->'nodes', '[]'::jsonb);
        edges := COALESCE(rec.definition->'edges', '[]'::jsonb);

        SELECT COALESCE(MAX((node->>'x')::integer), 0)
          INTO max_x
          FROM jsonb_array_elements(nodes) AS item(node);

        SELECT node->>'id', COALESCE((node->>'y')::integer, 120)
          INTO stop_id, stop_y
          FROM jsonb_array_elements(nodes) AS item(node)
         WHERE node->>'component_code'='cloak.profile.stop'
         LIMIT 1;

        SELECT node->>'id'
          INTO ingest_id
          FROM jsonb_array_elements(nodes) AS item(node)
         WHERE node->>'component_code'='ingest.submit'
         LIMIT 1;
        IF ingest_id IS NULL THEN
            ingest_id := 'downstream_ingest';
            nodes := nodes || jsonb_build_array(jsonb_build_object(
                'id', ingest_id,
                'component_code', 'ingest.submit',
                'name', 'API 上传 / FileIngest',
                'x', max_x + 280,
                'y', COALESCE(stop_y, 480),
                'enabled', true,
                'timeout_seconds', 1800,
                'retry_count', 0,
                'on_error', 'stop',
                'condition', '',
                'config', '{}'::jsonb
            ));
        END IF;

        SELECT node->>'id'
          INTO etl_id
          FROM jsonb_array_elements(nodes) AS item(node)
         WHERE node->>'component_code'='etl.trigger'
         LIMIT 1;
        IF etl_id IS NULL THEN
            etl_id := 'downstream_etl';
            nodes := nodes || jsonb_build_array(jsonb_build_object(
                'id', etl_id,
                'component_code', 'etl.trigger',
                'name', '触发受影响 ETL',
                'x', max_x + 560,
                'y', COALESCE(stop_y, 480),
                'enabled', true,
                'timeout_seconds', 3600,
                'retry_count', 0,
                'on_error', 'stop',
                'condition', '',
                'config', '{}'::jsonb
            ));
        END IF;

        IF stop_id IS NOT NULL THEN
            -- Put downstream nodes immediately before stop. If an author
            -- disables them later, FlowRunner contracts those nodes while
            -- preserving the original dependency on stop.
            edges := COALESCE((
                SELECT jsonb_agg(
                    CASE
                        WHEN edge->>'target'=stop_id
                             AND edge->>'source' NOT IN (ingest_id, etl_id)
                        THEN edge || jsonb_build_object('target', ingest_id)
                        ELSE edge
                    END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(edges) WITH ORDINALITY AS item(edge, ord)
            ), '[]'::jsonb);

            IF NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(edges) AS item(edge)
                WHERE edge->>'source'=ingest_id AND edge->>'target'=etl_id
            ) THEN
                edges := edges || jsonb_build_array(jsonb_build_object(
                    'source', ingest_id, 'target', etl_id,
                    'source_port', 'right', 'target_port', 'left'
                ));
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM jsonb_array_elements(edges) AS item(edge)
                WHERE edge->>'source'=etl_id AND edge->>'target'=stop_id
            ) THEN
                edges := edges || jsonb_build_array(jsonb_build_object(
                    'source', etl_id, 'target', stop_id,
                    'source_port', 'right', 'target_port', 'left'
                ));
            END IF;

            nodes := COALESCE((
                SELECT jsonb_agg(
                    CASE
                        WHEN node->>'id'=ingest_id
                            THEN node || jsonb_build_object('x', max_x + 280, 'y', stop_y)
                        WHEN node->>'id'=etl_id
                            THEN node || jsonb_build_object('x', max_x + 560, 'y', stop_y)
                        WHEN node->>'id'=stop_id
                            THEN node || jsonb_build_object('x', max_x + 840, 'y', stop_y)
                        ELSE node
                    END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(nodes) WITH ORDINALITY AS item(node, ord)
            ), '[]'::jsonb);
        END IF;

        UPDATE ops.automation_flow
           SET definition = jsonb_set(
                   jsonb_set(rec.definition, '{nodes}', nodes, true),
                   '{edges}', edges, true
               ),
               updated_at = NOW()
         WHERE flow_id = rec.flow_id;
    END LOOP;
END $$;

COMMENT ON TABLE ops.automation_job IS '自动化控制面白名单任务定义；不保存任意脚本或命令。';
COMMENT ON COLUMN ops.automation_job.job_id IS '任务定义自增主键。';
COMMENT ON COLUMN ops.automation_job.job_code IS '代码 registry 使用的全局唯一白名单任务编码。';
COMMENT ON COLUMN ops.automation_job.job_name IS '工作台展示任务名称。';
COMMENT ON COLUMN ops.automation_job.job_type IS '任务类型：platform_download 或 full_etl。';
COMMENT ON COLUMN ops.automation_job.enabled IS '任务是否允许被调度或手工运行。';
COMMENT ON COLUMN ops.automation_job.execution_lane IS '执行通道：overnight、interactive 或 etl。';
COMMENT ON COLUMN ops.automation_job.schedule_type IS '调度类型：manual 仅手工，daily 每日固定时间。';
COMMENT ON COLUMN ops.automation_job.schedule_config IS '调度配置 JSON；daily 第一版仅允许 times HH:MM 数组。';
COMMENT ON COLUMN ops.automation_job.timezone IS '计划时间所属 IANA 时区。';
COMMENT ON COLUMN ops.automation_job.retry_policy IS '重试策略 JSON；第一版保存最大尝试次数等受控参数。';
COMMENT ON COLUMN ops.automation_job.timeout_seconds IS '单次任务最长执行秒数。';
COMMENT ON COLUMN ops.automation_job.description IS '任务用途与执行边界说明。';
COMMENT ON COLUMN ops.automation_job.created_by IS '任务首次创建人或系统标识。';
COMMENT ON COLUMN ops.automation_job.updated_by IS '最后修改任务的用户或系统标识。';
COMMENT ON COLUMN ops.automation_job.created_at IS '任务创建时间。';
COMMENT ON COLUMN ops.automation_job.updated_at IS '任务最后更新时间。';

COMMENT ON TABLE ops.automation_run IS 'Automation Job 的一次实际排队与执行记录。';
COMMENT ON COLUMN ops.automation_run.automation_run_id IS '自动化运行 UUID。';
COMMENT ON COLUMN ops.automation_run.job_id IS '所属白名单任务定义主键。';
COMMENT ON COLUMN ops.automation_run.trigger_type IS '触发方式：manual、schedule 或 retry。';
COMMENT ON COLUMN ops.automation_run.schedule_key IS '定时触发幂等键，格式包含任务、本地日期与时间。';
COMMENT ON COLUMN ops.automation_run.business_date IS '运行默认业务基准日期；具体报表范围记录在 step。';
COMMENT ON COLUMN ops.automation_run.status IS '运行状态：queued/running/success/success_with_warnings/no_data/needs_human/failed/cancelled/skipped。';
COMMENT ON COLUMN ops.automation_run.execution_lane IS '本次运行通道。';
COMMENT ON COLUMN ops.automation_run.queued_at IS '任务入队时间。';
COMMENT ON COLUMN ops.automation_run.started_at IS 'AutomationWorker 领取时间。';
COMMENT ON COLUMN ops.automation_run.finished_at IS '运行进入终态的时间。';
COMMENT ON COLUMN ops.automation_run.operator IS '手工操作人或调度器标识。';
COMMENT ON COLUMN ops.automation_run.error_message IS '脱敏后的失败摘要。';
COMMENT ON COLUMN ops.automation_run.warning_message IS '成功但需关注的非失败摘要。';
COMMENT ON COLUMN ops.automation_run.result_summary IS '非敏感结构化执行汇总。';
COMMENT ON COLUMN ops.automation_run.ingest_run_id IS '本次下载关联的主要既有采集会话 UUID。';
COMMENT ON COLUMN ops.automation_run.etl_run_id IS '本次运行关联的既有 ETL 运行 UUID。';
COMMENT ON COLUMN ops.automation_run.attempt_count IS 'AutomationWorker 领取并执行次数。';
COMMENT ON COLUMN ops.automation_run.parent_run_id IS '重试来源 Automation Run UUID。';
COMMENT ON COLUMN ops.automation_run.worker_id IS '当前或最后领取本任务的 AutomationWorker UUID。';
COMMENT ON COLUMN ops.automation_run.heartbeat_at IS '执行中 Worker 最近写入的任务心跳时间。';
COMMENT ON COLUMN ops.automation_run.cancel_requested_at IS '用户请求取消的时间；Worker 在安全边界停止。';
COMMENT ON COLUMN ops.automation_run.created_at IS '运行记录创建时间。';
COMMENT ON COLUMN ops.automation_run.updated_at IS '运行记录最后更新时间。';

COMMENT ON TABLE ops.automation_step_run IS '平台、店铺、报表或 ETL 级自动化步骤运行记录。';
COMMENT ON COLUMN ops.automation_step_run.step_run_id IS '步骤运行 UUID。';
COMMENT ON COLUMN ops.automation_step_run.automation_run_id IS '所属自动化运行 UUID。';
COMMENT ON COLUMN ops.automation_step_run.sequence_no IS '运行内严格递增展示顺序。';
COMMENT ON COLUMN ops.automation_step_run.platform_code IS '能从 DIM 解析时的平台标准编码。';
COMMENT ON COLUMN ops.automation_step_run.platform_name IS '执行时的平台名称快照。';
COMMENT ON COLUMN ops.automation_step_run.company_code IS '能从 DIM 解析时的公司标准编码。';
COMMENT ON COLUMN ops.automation_step_run.company_name IS '执行时的公司名称快照。';
COMMENT ON COLUMN ops.automation_step_run.shop_code IS '能从 DIM 解析时的店铺标准编码。';
COMMENT ON COLUMN ops.automation_step_run.shop_name IS '执行时的店铺名称快照。';
COMMENT ON COLUMN ops.automation_step_run.profile_name IS 'Cloak Login profile 名称；不保存 CDP 地址。';
COMMENT ON COLUMN ops.automation_step_run.step_name IS '配置中的报表步骤名称。';
COMMENT ON COLUMN ops.automation_step_run.module_name IS 'registry 校验后的模块标识，不接受网页输入。';
COMMENT ON COLUMN ops.automation_step_run.execution_lane IS '步骤实际执行通道。';
COMMENT ON COLUMN ops.automation_step_run.status IS '步骤状态，needs_human 与 no_data 均为一等状态。';
COMMENT ON COLUMN ops.automation_step_run.business_date_start IS '报表真实业务开始日期，与执行日期分离。';
COMMENT ON COLUMN ops.automation_step_run.business_date_end IS '报表真实业务结束日期，与执行日期分离。';
COMMENT ON COLUMN ops.automation_step_run.period_type IS '业务期间类型：day/date_range/rolling_30_days/month/unknown。';
COMMENT ON COLUMN ops.automation_step_run.attempt_count IS '本步骤实际启动次数。';
COMMENT ON COLUMN ops.automation_step_run.started_at IS '步骤启动时间。';
COMMENT ON COLUMN ops.automation_step_run.finished_at IS '步骤结束时间。';
COMMENT ON COLUMN ops.automation_step_run.duration_seconds IS '步骤执行耗时，单位秒。';
COMMENT ON COLUMN ops.automation_step_run.exit_code IS '下载子进程退出码：0成功、1失败、2等待人工、130中断。';
COMMENT ON COLUMN ops.automation_step_run.output_summary IS '脱敏并截断的非敏感结果摘要。';
COMMENT ON COLUMN ops.automation_step_run.error_message IS '脱敏后的错误摘要。';
COMMENT ON COLUMN ops.automation_step_run.ingest_run_id IS '本步骤成果关联的既有采集会话 UUID。';
COMMENT ON COLUMN ops.automation_step_run.etl_run_id IS '本步骤关联的既有 ETL 运行 UUID。';
COMMENT ON COLUMN ops.automation_step_run.verification_challenge_id IS '能匹配时的验证码或文件密码 Challenge UUID；不保存答案。';
COMMENT ON COLUMN ops.automation_step_run.created_at IS '步骤记录创建时间。';
COMMENT ON COLUMN ops.automation_step_run.updated_at IS '步骤记录最后更新时间。';

COMMENT ON TABLE ops.automation_artifact IS '下载任务实际产生的文件元数据；二进制继续保存在归档目录。';
COMMENT ON COLUMN ops.automation_artifact.artifact_id IS '文件成果 UUID。';
COMMENT ON COLUMN ops.automation_artifact.automation_run_id IS '所属自动化运行 UUID。';
COMMENT ON COLUMN ops.automation_artifact.step_run_id IS '产生该文件的步骤运行 UUID。';
COMMENT ON COLUMN ops.automation_artifact.artifact_type IS '成果类型：report_file、archive 或 summary。';
COMMENT ON COLUMN ops.automation_artifact.file_name IS '归档后的文件名。';
COMMENT ON COLUMN ops.automation_artifact.relative_path IS '相对于配置归档根目录的路径。';
COMMENT ON COLUMN ops.automation_artifact.file_size_bytes IS '文件大小，单位字节。';
COMMENT ON COLUMN ops.automation_artifact.file_hash IS '可选 SHA256，用于审计和 ingest 幂等。';
COMMENT ON COLUMN ops.automation_artifact.report_type IS '通过现有文件命名识别出的 ingest 报表类型。';
COMMENT ON COLUMN ops.automation_artifact.business_date_start IS '该文件覆盖的业务开始日期。';
COMMENT ON COLUMN ops.automation_artifact.business_date_end IS '该文件覆盖的业务结束日期。';
COMMENT ON COLUMN ops.automation_artifact.ingest_file_task_id IS '自动提交 FileIngest 后关联的文件任务 UUID。';
COMMENT ON COLUMN ops.automation_artifact.batch_id IS '成功进入 ODS 后关联的主批次 ID。';
COMMENT ON COLUMN ops.automation_artifact.created_at IS '成果识别并登记的时间。';

COMMENT ON TABLE ops.automation_worker_heartbeat IS '独立 AutomationWorker 进程心跳。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.worker_id IS 'Worker 进程启动 UUID。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.worker_name IS 'Worker 实例名称。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.process_id IS '操作系统进程 ID，仅用于运行诊断。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.status IS 'Worker 状态：starting/idle/busy/stopped/failed。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.current_run_id IS '当前正在执行的 Automation Run UUID。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.started_at IS 'Worker 启动时间。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.last_seen_at IS '最近心跳时间。';
COMMENT ON COLUMN ops.automation_worker_heartbeat.stopped_at IS 'Worker 停止或失败时间。';

COMMENT ON TABLE ops.operation_log IS '数据导入、ETL、费用映射及 Automation 控制面操作审计日志。';


COMMENT ON TABLE ops.automation_flow IS '可视化 Flow Studio 保存的受控组件编排；发布版本只允许 registry 白名单组件。';
COMMENT ON TABLE ops.automation_component_run IS '报表步骤内部的原子组件运行记录，用于组件级定位、重试设计与 AI 修复上下文。';
COMMENT ON TABLE ops.automation_component_event IS '组件内部动作与观察事件；禁止保存验证码、密码、Cookie、Token 等秘密。';

COMMENT ON COLUMN ops.automation_run.flow_id IS 'Flow Studio 运行关联的发布 Flow UUID；传统任务为空。';
COMMENT ON COLUMN ops.automation_run.input_context IS '受控 Flow 运行输入，如 profile_name、业务日期范围；不得保存密码、验证码、Cookie、Token。';

COMMENT ON COLUMN ops.automation_component_run.parent_component_run_id IS '嵌套组件父运行 UUID；报表 Flow 容器下挂业务原子组件。';


COMMENT ON TABLE ops.automation_flow_version IS 'Flow 每次发布形成的不可变执行快照；Automation Run 绑定具体版本，避免历史记录随当前草稿漂移。';
COMMENT ON COLUMN ops.automation_run.flow_version_id IS 'Flow Run 实际执行的发布版本快照 UUID；历史旧数据无法可靠追溯时保持为空。';
COMMENT ON COLUMN ops.automation_run.resource_key IS '运行资源互斥键；Flow 默认按 Cloak Profile 串行，系统任务默认按 job_code 串行。';
COMMENT ON TABLE ops.automation_resource_lock IS 'AutomationWorker 领取运行时持有的数据库资源锁，防止相同 Browser Profile 或关键任务并发冲突。';
COMMENT ON COLUMN ops.automation_flow.default_profile_name IS 'Flow 定时运行使用的 Cloak Login Profile；手工运行仍可覆盖。';


COMMENT ON COLUMN ops.automation_run.waiting_since IS 'Run 进入 needs_human 暂停态的时间；等待期间不占用 Worker 与资源锁。';
COMMENT ON COLUMN ops.automation_run.resumed_at IS 'Run 最近一次从 needs_human 恢复排队的时间。';
COMMENT ON COLUMN ops.automation_run.resume_count IS '同一 Run 从等待人工恢复的次数。';
COMMENT ON TABLE ops.automation_notification_policy IS '自动化运行通知策略；当前 feishu_relay 复用 AI 管理中的验证码转发机器人。';
COMMENT ON TABLE ops.automation_notification_outbox IS '自动化运行事件可靠通知 Outbox；由飞书服务异步投递，不阻塞 Worker 完成任务。';
