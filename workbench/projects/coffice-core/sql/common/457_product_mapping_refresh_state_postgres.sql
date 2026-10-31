CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.product_mapping_refresh_state (
    state_key TEXT PRIMARY KEY CHECK (state_key = 'product_mapping'),
    requested_revision BIGINT NOT NULL DEFAULT 1,
    completed_revision BIGINT NOT NULL DEFAULT 0,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    last_reason TEXT NOT NULL DEFAULT 'initial_build',
    last_error TEXT,
    CHECK (requested_revision >= completed_revision)
);
COMMENT ON TABLE ops.product_mapping_refresh_state IS '商品编码映射派生结果的持久化刷新请求；配置事务内递增，成功发布后确认，服务重启继续处理。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.state_key IS '固定任务标识product_mapping；仅一条状态记录。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.requested_revision IS '已提交配置变更请求版本；由配置表语句级触发器递增。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.completed_revision IS '最近一次成功重算商品DWS及发布页面ADS所覆盖的请求版本。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.requested_at IS '最近请求时间，带时区。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.completed_at IS '最近成功发布时间，带时区；首次发布前为空。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.last_reason IS '最近变更的配置表及操作或初始化原因。';
COMMENT ON COLUMN ops.product_mapping_refresh_state.last_error IS '后台刷新失败摘要；成功发布清空，不包含连接凭据。';
INSERT INTO ops.product_mapping_refresh_state(state_key) VALUES ('product_mapping')
ON CONFLICT (state_key) DO NOTHING;

CREATE OR REPLACE FUNCTION ops.request_product_mapping_refresh()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- Same domain lock as the ETL: configuration cannot change midway through
    -- product allocation and snapshot publication. Readers never take this lock.
    PERFORM pg_advisory_xact_lock(hashtext('mock_coffice_product_mapping_refresh'));
    UPDATE ops.product_mapping_refresh_state
       SET requested_revision = requested_revision + 1,
           requested_at = clock_timestamp(),
           last_reason = TG_TABLE_NAME || '.' || LOWER(TG_OP), last_error = NULL
     WHERE state_key = 'product_mapping';
    RETURN NULL;
END;
$$;
COMMENT ON FUNCTION ops.request_product_mapping_refresh() IS '配置写入前取得商品刷新互斥锁，并在同一事务持久化刷新请求；回滚不会遗留请求。';

DROP TRIGGER IF EXISTS request_product_mapping_refresh ON dim.dim_company_product_code_mapping;
CREATE TRIGGER request_product_mapping_refresh BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON dim.dim_company_product_code_mapping FOR EACH STATEMENT EXECUTE FUNCTION ops.request_product_mapping_refresh();
DROP TRIGGER IF EXISTS request_product_mapping_refresh ON dim.dim_influencer_product;
CREATE TRIGGER request_product_mapping_refresh BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON dim.dim_influencer_product FOR EACH STATEMENT EXECUTE FUNCTION ops.request_product_mapping_refresh();
DROP TRIGGER IF EXISTS request_product_mapping_refresh ON dim.dim_influencer_product_category;
CREATE TRIGGER request_product_mapping_refresh BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON dim.dim_influencer_product_category FOR EACH STATEMENT EXECUTE FUNCTION ops.request_product_mapping_refresh();
DROP TRIGGER IF EXISTS request_product_mapping_refresh ON dim.dim_company_product_code_normalization_rule;
CREATE TRIGGER request_product_mapping_refresh BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON dim.dim_company_product_code_normalization_rule FOR EACH STATEMENT EXECUTE FUNCTION ops.request_product_mapping_refresh();
