-- Retain legacy robot history and distinguish new API submissions.
ALTER TABLE ops.ingest_run DROP CONSTRAINT IF EXISTS ck_ops_ingest_run_source;
ALTER TABLE ops.ingest_run ADD CONSTRAINT ck_ops_ingest_run_source
    CHECK (source IN ('api', 'robot', 'manual'));
COMMENT ON COLUMN ops.ingest_run.source IS '会话来源：api为API上传，robot为历史影刀上传，manual为网页人工上传。';
COMMENT ON COLUMN ods.ods_file_ingest_log.automation_source IS '自动化来源api、robot或manual；传统CLI导入为空。';
