CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.ingest_file_task_batch (
    file_task_id UUID NOT NULL REFERENCES ops.ingest_file_task(file_task_id) ON DELETE CASCADE,
    batch_id BIGINT NOT NULL REFERENCES ods.ods_file_ingest_log(batch_id) ON DELETE RESTRICT,
    target_table VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (file_task_id, batch_id),
    CONSTRAINT uq_ops_ingest_file_task_target UNIQUE (file_task_id, target_table)
);

ALTER TABLE ods.ods_xhs_settlement_expense_raw
    ADD COLUMN IF NOT EXISTS "佣金金额" VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_ops_ingest_file_task_batch_batch
    ON ops.ingest_file_task_batch(batch_id);

COMMENT ON TABLE ops.ingest_file_task_batch IS '采集文件任务与ODS导入批次的关联；多工作表报表可关联多个目标表批次。';
COMMENT ON COLUMN ops.ingest_file_task_batch.file_task_id IS '上传文件任务ID，关联ops.ingest_file_task。';
COMMENT ON COLUMN ops.ingest_file_task_batch.batch_id IS 'ODS导入批次ID，关联ods.ods_file_ingest_log。';
COMMENT ON COLUMN ops.ingest_file_task_batch.target_table IS '该批次写入的ODS目标表名，不含schema。';
COMMENT ON COLUMN ops.ingest_file_task_batch.created_at IS '任务与批次关联创建时间。';
COMMENT ON COLUMN ods.ods_xhs_settlement_expense_raw."佣金金额" IS '来源工作表“其他服务款”的佣金金额，保留小红书导出原始值。';
