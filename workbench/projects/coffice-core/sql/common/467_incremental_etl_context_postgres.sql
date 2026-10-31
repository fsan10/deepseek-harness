ALTER TABLE ops.etl_run ADD COLUMN IF NOT EXISTS refresh_context JSONB;
COMMENT ON COLUMN ops.etl_run.refresh_context IS
    'ETL本次冻结刷新上下文：version=1，mode为incremental/full，trigger_type为触发来源，months为平台与受影响自然月首日，shops为标准店铺，batch_ids为本次新增ODS批次，batch_cutoff为来源快照批次上界，excluded_batch_ids排除冻结时尚未成功的较早批次；全量仅允许人工创建。';
