ALTER TABLE ops.etl_run ADD COLUMN IF NOT EXISTS worker_id UUID;
ALTER TABLE ops.etl_run ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN ops.etl_run.worker_id IS '本次执行尝试所属ops.worker_heartbeat.worker_id；历史运行可为空，重试领取时重新绑定。';
COMMENT ON COLUMN ops.etl_run.heartbeat_at IS '执行者最近一次续期时间；每10秒更新，结合Worker状态及执行锁识别中断，不以任务总耗时判断。';

CREATE INDEX IF NOT EXISTS idx_ops_etl_run_running_heartbeat
    ON ops.etl_run (heartbeat_at) WHERE status='running';
