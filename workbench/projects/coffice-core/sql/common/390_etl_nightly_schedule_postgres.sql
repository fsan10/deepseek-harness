-- ETL 夜间全量刷新配置。仅控制调度器是否创建 nightly ETL 任务，不改变手工刷新入口。
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.etl_nightly_schedule (
    config_id SMALLINT PRIMARY KEY DEFAULT 1,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    run_time TIME NOT NULL DEFAULT TIME '02:00',
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
    updated_by VARCHAR(100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_etl_nightly_schedule_singleton CHECK (config_id = 1),
    CONSTRAINT ck_ops_etl_nightly_schedule_timezone CHECK (BTRIM(timezone) <> '')
);

INSERT INTO ops.etl_nightly_schedule(config_id, enabled, run_time, timezone)
VALUES (1, TRUE, TIME '02:00', 'Asia/Shanghai')
ON CONFLICT (config_id) DO NOTHING;

COMMENT ON TABLE ops.etl_nightly_schedule IS 'ETL夜间全量刷新调度配置；单例记录控制是否启用及本地刷新时间。';
COMMENT ON COLUMN ops.etl_nightly_schedule.config_id IS '固定为1的单例配置主键。';
COMMENT ON COLUMN ops.etl_nightly_schedule.enabled IS '是否允许夜间调度器自动创建全量ETL任务。';
COMMENT ON COLUMN ops.etl_nightly_schedule.run_time IS '按timezone解释的每日刷新时间，精确到分钟。';
COMMENT ON COLUMN ops.etl_nightly_schedule.timezone IS '刷新时间所属IANA时区，例如Asia/Shanghai。';
COMMENT ON COLUMN ops.etl_nightly_schedule.updated_by IS '最后修改配置的用户或系统标识。';
COMMENT ON COLUMN ops.etl_nightly_schedule.updated_at IS '配置最后修改时间。';
