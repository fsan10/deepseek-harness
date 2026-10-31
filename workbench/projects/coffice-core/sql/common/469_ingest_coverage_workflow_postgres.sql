ALTER TABLE ops.ingest_run ADD COLUMN IF NOT EXISTS import_mode TEXT NOT NULL DEFAULT 'fill_gaps'
    CHECK (import_mode IN ('fill_gaps','replace_range','refresh_only'));
ALTER TABLE ops.ingest_run ADD COLUMN IF NOT EXISTS coverage_preflight JSONB;
ALTER TABLE ops.ingest_run ADD COLUMN IF NOT EXISTS coverage_result JSONB;
ALTER TABLE ops.ingest_file_task ADD COLUMN IF NOT EXISTS coverage JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE ops.etl_run ADD COLUMN IF NOT EXISTS parent_etl_run_id UUID REFERENCES ops.etl_run(etl_run_id) ON DELETE SET NULL;
COMMENT ON COLUMN ops.ingest_run.import_mode IS '采信意图：fill_gaps默认补缺且冲突阻断；replace_range人工确认范围替换；refresh_only复用已有ODS重新加工';
COMMENT ON COLUMN ops.ingest_run.coverage_preflight IS '提交前的逐日内容比对、文件摘要、采信版本与确认令牌；提交及激活时重新校验';
COMMENT ON COLUMN ops.ingest_run.coverage_result IS '来源采信结果：补缺、一致、差异、确认空日、批次与刷新范围；不等同于指标刷新成功';
COMMENT ON COLUMN ops.ingest_file_task.coverage IS '查询范围与证明：start/end、完整导出声明、人工确认空日、原因或绑定文件的自动化回执ID';
COMMENT ON COLUMN ops.etl_run.parent_etl_run_id IS '重试来源运行；新运行拥有新冻结快照并重建相关上下游，旧运行及报错保留';
COMMENT ON COLUMN ops.ingest_run.source IS '会话来源：manual为网页或终端API的人工上传，api为自动化API，robot为历史自动化调用';
