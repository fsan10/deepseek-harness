/*
 * 兼容历史 ETL 运行记录中的 deferred / success_with_warnings 状态。
 * 当前调度策略将空平台视为合法 0 值，不再因为缺少其它平台而延后刷新。
 */

ALTER TABLE ops.etl_run
    DROP CONSTRAINT IF EXISTS ck_ops_etl_run_status;

ALTER TABLE ops.etl_run
    ADD CONSTRAINT ck_ops_etl_run_status CHECK (
        status IN (
            'queued',
            'running',
            'success',
            'success_with_warnings',
            'partial_failed',
            'failed',
            'no_change'
        )
    );

ALTER TABLE ops.etl_task
    DROP CONSTRAINT IF EXISTS ck_ops_etl_task_status;

ALTER TABLE ops.etl_task
    ADD CONSTRAINT ck_ops_etl_task_status CHECK (
        status IN ('queued', 'running', 'success', 'failed', 'skipped', 'deferred')
    );

COMMENT ON COLUMN ops.etl_run.status IS
    '运行状态：queued排队、running执行、success成功、success_with_warnings成功但有来源未就绪提醒、partial_failed部分失败、failed失败、no_change无变化。';

COMMENT ON COLUMN ops.etl_task.status IS
    '任务状态：queued排队、running执行、success成功、failed失败、skipped因失败依赖跳过、deferred因来源未就绪延后。';
