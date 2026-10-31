ALTER TABLE ops.automation_artifact ADD COLUMN IF NOT EXISTS period_type VARCHAR(32) NOT NULL DEFAULT 'unknown';
ALTER TABLE ops.automation_artifact ADD COLUMN IF NOT EXISTS coverage_verified BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN ops.automation_artifact.period_type IS '文件的业务期间粒度：day、date_range、month、unknown；月汇总不等同于逐日报表。';
COMMENT ON COLUMN ops.automation_artifact.coverage_verified IS '是否由统一归档回执确认报表类型及请求期间；历史文件名推断不能设为TRUE。';

CREATE TABLE IF NOT EXISTS ops.automation_download_batch (
    batch_id UUID PRIMARY KEY,
    request_key VARCHAR(100) NOT NULL UNIQUE,
    plan_hash VARCHAR(64) NOT NULL,
    request_context JSONB NOT NULL,
    plan_snapshot JSONB NOT NULL,
    operator VARCHAR(200) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE ops.automation_download_batch IS '用户选择店铺、报表和业务日期后的历史下载批次；冻结计划，执行仍使用现有Run/Step/Artifact。';
COMMENT ON COLUMN ops.automation_download_batch.batch_id IS '补跑批次唯一标识；Run的input_context关联该标识。';
COMMENT ON COLUMN ops.automation_download_batch.request_key IS '客户端提交幂等键；重复点击返回同一批次，不创建重复导出。';
COMMENT ON COLUMN ops.automation_download_batch.plan_hash IS '冻结执行计划SHA256，用于识别并返回相同的未结束批次。';
COMMENT ON COLUMN ops.automation_download_batch.request_context IS '用户选择的Profile、标准报表、业务日期和重新获取选项；禁止秘密。';
COMMENT ON COLUMN ops.automation_download_batch.plan_snapshot IS '本次精确日期下载计划和配置版本快照；不维护公司店铺映射。';
COMMENT ON COLUMN ops.automation_download_batch.operator IS '发起补跑的后台操作人。';
COMMENT ON COLUMN ops.automation_download_batch.created_at IS '批次创建时间，带时区。';
CREATE INDEX IF NOT EXISTS idx_automation_download_batch_plan ON ops.automation_download_batch(plan_hash);
CREATE INDEX IF NOT EXISTS idx_automation_run_download_batch ON ops.automation_run((input_context->>'batch_id'));

CREATE TABLE IF NOT EXISTS ops.automation_download_journal (
    journal_key VARCHAR(100) PRIMARY KEY,
    automation_run_id UUID NOT NULL REFERENCES ops.automation_run(automation_run_id) ON DELETE CASCADE,
    imported_events INTEGER NOT NULL DEFAULT 0,
    step_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    plan_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE ops.automation_download_journal IS '外部CLI/Codex落盘事件导入进度，确保数据库暂时不可用后的幂等同步。';
COMMENT ON COLUMN ops.automation_download_journal.journal_key IS '本地总控运行标识，与事件文件名一致。';
COMMENT ON COLUMN ops.automation_download_journal.automation_run_id IS '同步进入现有执行台账的Run标识。';
COMMENT ON COLUMN ops.automation_download_journal.imported_events IS '已经幂等导入的事件数量。';
COMMENT ON COLUMN ops.automation_download_journal.step_refs IS '事件步骤标识与现有Step UUID的对应关系，不包含凭据或页面会话。';
COMMENT ON COLUMN ops.automation_download_journal.plan_snapshot IS '当次Profile和报表计划快照，用于解释未执行、通道跳过和配置变更。';
COMMENT ON COLUMN ops.automation_download_journal.updated_at IS '最后一次事件同步时间，带时区。';

INSERT INTO ops.automation_job(job_code,job_name,job_type,enabled,execution_lane,schedule_type,schedule_config,timezone,retry_policy,timeout_seconds,description,created_by,updated_by)
VALUES('platform_download_backfill','历史报表补跑','platform_download',TRUE,'interactive','manual','{}'::jsonb,'Asia/Shanghai','{"max_attempts":1}'::jsonb,21600,'用户在报表日历选择店铺、报表和业务日期后的受控历史下载入口。','system','system')
ON CONFLICT(job_code) DO NOTHING;
