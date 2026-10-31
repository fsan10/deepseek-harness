CREATE SCHEMA IF NOT EXISTS ai;
COMMENT ON SCHEMA ai IS 'AI管理、只读数据分析、飞书接入和审计对象的独立schema；不存放ODS原始数据。';

CREATE TABLE IF NOT EXISTS ai.provider_config (
    provider_config_id BIGSERIAL PRIMARY KEY,
    config_code VARCHAR(64) NOT NULL UNIQUE,
    config_name VARCHAR(100) NOT NULL,
    provider_code VARCHAR(32) NOT NULL DEFAULT 'deepseek',
    api_base_url VARCHAR(500) NOT NULL DEFAULT 'https://api.deepseek.com',
    api_key_ciphertext BYTEA,
    api_key_nonce BYTEA,
    model_name VARCHAR(128) NOT NULL DEFAULT 'deepseek-v4-flash',
    temperature NUMERIC(3,2) NOT NULL DEFAULT 0.20,
    request_timeout_seconds INTEGER NOT NULL DEFAULT 120,
    thinking_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    last_test_status VARCHAR(16) NOT NULL DEFAULT 'untested',
    last_tested_at TIMESTAMPTZ,
    last_test_error VARCHAR(500),
    created_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_ai_provider_code CHECK (provider_code = 'deepseek'),
    CONSTRAINT ck_ai_provider_config_code CHECK (config_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_ai_provider_temperature CHECK (temperature BETWEEN 0 AND 2),
    CONSTRAINT ck_ai_provider_request_timeout CHECK (request_timeout_seconds BETWEEN 5 AND 600),
    CONSTRAINT ck_ai_provider_secret_pair CHECK ((api_key_ciphertext IS NULL) = (api_key_nonce IS NULL)),
    CONSTRAINT ck_ai_provider_test_status CHECK (last_test_status IN ('untested','success','failed'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_provider_default ON ai.provider_config ((1)) WHERE is_default AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_ai_provider_active ON ai.provider_config(is_active, deleted_at);
COMMENT ON TABLE ai.provider_config IS 'AI模型供应商配置；一期仅支持DeepSeek，密钥使用服务端AES-GCM加密。';
COMMENT ON COLUMN ai.provider_config.provider_config_id IS '模型配置主键。';
COMMENT ON COLUMN ai.provider_config.config_code IS '模型配置唯一英文编码。';
COMMENT ON COLUMN ai.provider_config.config_name IS '模型配置显示名称。';
COMMENT ON COLUMN ai.provider_config.provider_code IS '供应商编码，一期固定deepseek。';
COMMENT ON COLUMN ai.provider_config.api_base_url IS 'DeepSeek API基础地址，不包含具体接口路径。';
COMMENT ON COLUMN ai.provider_config.api_key_ciphertext IS 'API Key经AES-GCM认证加密后的密文，禁止返回前端。';
COMMENT ON COLUMN ai.provider_config.api_key_nonce IS 'API Key AES-GCM随机nonce，不能单独解密。';
COMMENT ON COLUMN ai.provider_config.model_name IS '可配置模型标识，初始为官方稳定deepseek-v4-flash。';
COMMENT ON COLUMN ai.provider_config.temperature IS '模型采样温度，范围0到2。';
COMMENT ON COLUMN ai.provider_config.request_timeout_seconds IS '模型请求超时秒数。';
COMMENT ON COLUMN ai.provider_config.thinking_enabled IS '是否开启DeepSeek思考模式。';
COMMENT ON COLUMN ai.provider_config.is_active IS '配置是否允许被AI服务使用。';
COMMENT ON COLUMN ai.provider_config.is_default IS '是否为默认配置；未删除记录全局唯一。';
COMMENT ON COLUMN ai.provider_config.last_test_status IS '最近连接测试状态：untested、success或failed。';
COMMENT ON COLUMN ai.provider_config.last_tested_at IS '最近连接测试时间。';
COMMENT ON COLUMN ai.provider_config.last_test_error IS '脱敏后的最近测试错误摘要。';
COMMENT ON COLUMN ai.provider_config.created_by IS '创建配置的IAM用户主键。';
COMMENT ON COLUMN ai.provider_config.updated_by IS '最后更新配置的IAM用户主键。';
COMMENT ON COLUMN ai.provider_config.created_at IS '配置创建审计时间。';
COMMENT ON COLUMN ai.provider_config.updated_at IS '配置最后更新审计时间。';
COMMENT ON COLUMN ai.provider_config.deleted_at IS '软删除时间，非空表示已删除。';

CREATE TABLE IF NOT EXISTS ai.data_source (
    data_source_id BIGSERIAL PRIMARY KEY,
    source_code VARCHAR(64) NOT NULL UNIQUE,
    source_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'postgresql',
    host VARCHAR(255) NOT NULL,
    port INTEGER NOT NULL DEFAULT 5432,
    database_name VARCHAR(128) NOT NULL,
    readonly_username VARCHAR(128) NOT NULL,
    password_ciphertext BYTEA NOT NULL,
    password_nonce BYTEA NOT NULL,
    ssl_mode VARCHAR(16) NOT NULL DEFAULT 'prefer',
    connect_timeout_seconds INTEGER NOT NULL DEFAULT 10,
    statement_timeout_ms INTEGER NOT NULL DEFAULT 15000,
    lock_timeout_ms INTEGER NOT NULL DEFAULT 2000,
    idle_transaction_timeout_ms INTEGER NOT NULL DEFAULT 15000,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    description VARCHAR(1000) NOT NULL DEFAULT '',
    last_test_status VARCHAR(16) NOT NULL DEFAULT 'untested',
    last_tested_at TIMESTAMPTZ,
    last_test_error VARCHAR(500),
    created_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT ck_ai_source_code CHECK (source_code ~ '^[a-z][a-z0-9_]{1,63}$'),
    CONSTRAINT ck_ai_source_type CHECK (source_type = 'postgresql'),
    CONSTRAINT ck_ai_source_port CHECK (port BETWEEN 1 AND 65535),
    CONSTRAINT ck_ai_source_ssl CHECK (ssl_mode IN ('disable','allow','prefer','require','verify-ca','verify-full')),
    CONSTRAINT ck_ai_source_timeouts CHECK (connect_timeout_seconds BETWEEN 1 AND 60 AND statement_timeout_ms BETWEEN 100 AND 300000 AND lock_timeout_ms BETWEEN 100 AND 30000 AND idle_transaction_timeout_ms BETWEEN 1000 AND 300000),
    CONSTRAINT ck_ai_source_test_status CHECK (last_test_status IN ('untested','success','failed'))
);
CREATE INDEX IF NOT EXISTS ix_ai_source_active ON ai.data_source(is_active, deleted_at);
COMMENT ON TABLE ai.data_source IS 'AI只读数据源配置；查询必须使用数据库专用只读账号。';
COMMENT ON COLUMN ai.data_source.data_source_id IS '数据源主键。';
COMMENT ON COLUMN ai.data_source.source_code IS '数据源唯一英文编码。';
COMMENT ON COLUMN ai.data_source.source_name IS '数据源显示名称。';
COMMENT ON COLUMN ai.data_source.source_type IS '数据源类型，一期固定postgresql。';
COMMENT ON COLUMN ai.data_source.host IS 'PostgreSQL主机名或IP地址。';
COMMENT ON COLUMN ai.data_source.port IS 'PostgreSQL端口。';
COMMENT ON COLUMN ai.data_source.database_name IS '允许连接的数据库名称。';
COMMENT ON COLUMN ai.data_source.readonly_username IS '数据库专用只读用户名，禁止使用应用高权限账号。';
COMMENT ON COLUMN ai.data_source.password_ciphertext IS '只读账号密码的AES-GCM密文，禁止返回前端。';
COMMENT ON COLUMN ai.data_source.password_nonce IS '只读账号密码AES-GCM随机nonce。';
COMMENT ON COLUMN ai.data_source.ssl_mode IS 'PostgreSQL sslmode枚举。';
COMMENT ON COLUMN ai.data_source.connect_timeout_seconds IS '数据库连接超时秒数。';
COMMENT ON COLUMN ai.data_source.statement_timeout_ms IS '每条AI查询statement_timeout毫秒数。';
COMMENT ON COLUMN ai.data_source.lock_timeout_ms IS '每条AI查询lock_timeout毫秒数。';
COMMENT ON COLUMN ai.data_source.idle_transaction_timeout_ms IS '只读事务空闲超时毫秒数。';
COMMENT ON COLUMN ai.data_source.is_active IS '数据源是否启用。';
COMMENT ON COLUMN ai.data_source.description IS '数据源用途说明。';
COMMENT ON COLUMN ai.data_source.last_test_status IS '最近连接测试状态。';
COMMENT ON COLUMN ai.data_source.last_tested_at IS '最近连接测试时间。';
COMMENT ON COLUMN ai.data_source.last_test_error IS '脱敏后的最近连接错误摘要。';
COMMENT ON COLUMN ai.data_source.created_by IS '创建数据源的IAM用户主键。';
COMMENT ON COLUMN ai.data_source.updated_by IS '最后更新数据源的IAM用户主键。';
COMMENT ON COLUMN ai.data_source.created_at IS '数据源创建审计时间。';
COMMENT ON COLUMN ai.data_source.updated_at IS '数据源最后更新审计时间。';
COMMENT ON COLUMN ai.data_source.deleted_at IS '软删除时间。';

CREATE TABLE IF NOT EXISTS ai.data_catalog (
    catalog_id BIGSERIAL PRIMARY KEY,
    data_source_id BIGINT NOT NULL REFERENCES ai.data_source(data_source_id) ON DELETE CASCADE,
    database_name VARCHAR(128) NOT NULL,
    schema_name VARCHAR(128) NOT NULL,
    object_name VARCHAR(128) NOT NULL,
    object_type VARCHAR(16) NOT NULL,
    table_comment TEXT,
    candidate_description TEXT,
    business_name VARCHAR(200),
    business_meaning TEXT,
    data_grain VARCHAR(500),
    business_key_description VARCHAR(500),
    date_field_description VARCHAR(500),
    amount_field_description VARCHAR(500),
    status_field_description VARCHAR(1000),
    important_filter_rules TEXT,
    recommended_joins JSONB NOT NULL DEFAULT '[]'::jsonb,
    data_origin VARCHAR(500),
    refresh_frequency VARCHAR(200),
    data_owner VARCHAR(200),
    contains_sensitive_fields BOOLEAN NOT NULL DEFAULT FALSE,
    ai_usage_notes TEXT,
    metadata_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    approximate_row_count BIGINT,
    data_date_start DATE,
    data_date_end DATE,
    source_updated_at TIMESTAMPTZ,
    scan_hash CHAR(64),
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    CONSTRAINT uq_ai_catalog_object UNIQUE (data_source_id, database_name, schema_name, object_name),
    CONSTRAINT ck_ai_catalog_type CHECK (object_type IN ('table','view','materialized_view','foreign_table')),
    CONSTRAINT ck_ai_catalog_status CHECK (metadata_status IN ('pending','confirmed','disabled')),
    CONSTRAINT ck_ai_catalog_rows CHECK (approximate_row_count IS NULL OR approximate_row_count >= 0),
    CONSTRAINT ck_ai_catalog_dates CHECK (data_date_start IS NULL OR data_date_end IS NULL OR data_date_start <= data_date_end)
);
CREATE INDEX IF NOT EXISTS ix_ai_catalog_search ON ai.data_catalog(data_source_id, schema_name, metadata_status, deleted_at);
COMMENT ON TABLE ai.data_catalog IS 'AI数据目录的表和视图级元数据；候选说明不得自动视为已确认口径。';
COMMENT ON COLUMN ai.data_catalog.catalog_id IS '数据目录对象主键。';
COMMENT ON COLUMN ai.data_catalog.data_source_id IS '所属AI只读数据源主键。';
COMMENT ON COLUMN ai.data_catalog.database_name IS '对象所属数据库名称。';
COMMENT ON COLUMN ai.data_catalog.schema_name IS '对象所属schema名称。';
COMMENT ON COLUMN ai.data_catalog.object_name IS '表或视图名称。';
COMMENT ON COLUMN ai.data_catalog.object_type IS '对象类型：table、view、materialized_view或foreign_table。';
COMMENT ON COLUMN ai.data_catalog.table_comment IS '从PostgreSQL COMMENT ON TABLE读取的原始注释。';
COMMENT ON COLUMN ai.data_catalog.candidate_description IS '缺少注释时根据结构生成的候选说明，必须人工确认。';
COMMENT ON COLUMN ai.data_catalog.business_name IS '人工维护的中文业务名称。';
COMMENT ON COLUMN ai.data_catalog.business_meaning IS '人工确认的业务含义。';
COMMENT ON COLUMN ai.data_catalog.data_grain IS '数据最小粒度说明。';
COMMENT ON COLUMN ai.data_catalog.business_key_description IS '主键或业务唯一键说明。';
COMMENT ON COLUMN ai.data_catalog.date_field_description IS '日期字段及业务含义。';
COMMENT ON COLUMN ai.data_catalog.amount_field_description IS '金额字段、单位和计算口径。';
COMMENT ON COLUMN ai.data_catalog.status_field_description IS '状态字段及枚举说明。';
COMMENT ON COLUMN ai.data_catalog.important_filter_rules IS '重要筛选规则，未确认时不得擅自推断。';
COMMENT ON COLUMN ai.data_catalog.recommended_joins IS '推荐关联表和候选关联关系JSON数组。';
COMMENT ON COLUMN ai.data_catalog.data_origin IS '数据来源说明。';
COMMENT ON COLUMN ai.data_catalog.refresh_frequency IS '数据刷新频率说明。';
COMMENT ON COLUMN ai.data_catalog.data_owner IS '数据负责人。';
COMMENT ON COLUMN ai.data_catalog.contains_sensitive_fields IS '是否包含敏感字段。';
COMMENT ON COLUMN ai.data_catalog.ai_usage_notes IS 'AI使用注意事项和限制。';
COMMENT ON COLUMN ai.data_catalog.metadata_status IS '元数据状态：pending待确认、confirmed已确认、disabled已停用。';
COMMENT ON COLUMN ai.data_catalog.approximate_row_count IS '来自PostgreSQL统计信息的近似行数。';
COMMENT ON COLUMN ai.data_catalog.data_date_start IS '人工或受控探查确认的数据起始日期。';
COMMENT ON COLUMN ai.data_catalog.data_date_end IS '人工或受控探查确认的数据结束日期。';
COMMENT ON COLUMN ai.data_catalog.source_updated_at IS '源对象可识别的最近更新时间或刷新时间。';
COMMENT ON COLUMN ai.data_catalog.scan_hash IS '结构扫描结果SHA-256，用于增量同步判断。';
COMMENT ON COLUMN ai.data_catalog.scanned_at IS '最近元数据扫描时间。';
COMMENT ON COLUMN ai.data_catalog.updated_by IS '最后人工维护的IAM用户主键。';
COMMENT ON COLUMN ai.data_catalog.updated_at IS '目录记录最后更新时间。';
COMMENT ON COLUMN ai.data_catalog.deleted_at IS '源对象消失或手工删除后的软删除时间。';

CREATE TABLE IF NOT EXISTS ai.catalog_column (
    catalog_column_id BIGSERIAL PRIMARY KEY,
    catalog_id BIGINT NOT NULL REFERENCES ai.data_catalog(catalog_id) ON DELETE CASCADE,
    column_name VARCHAR(128) NOT NULL,
    ordinal_position INTEGER NOT NULL,
    data_type VARCHAR(255) NOT NULL,
    is_nullable BOOLEAN NOT NULL,
    column_default TEXT,
    column_comment TEXT,
    candidate_description TEXT,
    business_name VARCHAR(200),
    business_meaning TEXT,
    is_primary_key BOOLEAN NOT NULL DEFAULT FALSE,
    is_unique BOOLEAN NOT NULL DEFAULT FALSE,
    foreign_key_reference JSONB,
    index_definitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_sensitive BOOLEAN NOT NULL DEFAULT FALSE,
    mask_rule VARCHAR(32) NOT NULL DEFAULT 'none',
    metadata_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by BIGINT REFERENCES iam.user_account(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ai_catalog_column UNIQUE (catalog_id, column_name),
    CONSTRAINT ck_ai_catalog_column_ordinal CHECK (ordinal_position > 0),
    CONSTRAINT ck_ai_catalog_column_mask CHECK (mask_rule IN ('none','full','partial','hash','email','phone')),
    CONSTRAINT ck_ai_catalog_column_status CHECK (metadata_status IN ('pending','confirmed','disabled'))
);
CREATE INDEX IF NOT EXISTS ix_ai_catalog_column_status ON ai.catalog_column(catalog_id, metadata_status, is_sensitive);
COMMENT ON TABLE ai.catalog_column IS 'AI数据目录字段级元数据、敏感标记和脱敏规则。';
COMMENT ON COLUMN ai.catalog_column.catalog_column_id IS '目录字段主键。';
COMMENT ON COLUMN ai.catalog_column.catalog_id IS '所属表或视图目录主键。';
COMMENT ON COLUMN ai.catalog_column.column_name IS '数据库字段名。';
COMMENT ON COLUMN ai.catalog_column.ordinal_position IS '字段在对象中的顺序。';
COMMENT ON COLUMN ai.catalog_column.data_type IS 'PostgreSQL格式化字段类型。';
COMMENT ON COLUMN ai.catalog_column.is_nullable IS '字段是否允许NULL。';
COMMENT ON COLUMN ai.catalog_column.column_default IS '数据库字段默认表达式，仅用于元数据展示。';
COMMENT ON COLUMN ai.catalog_column.column_comment IS '从COMMENT ON COLUMN读取的原始注释。';
COMMENT ON COLUMN ai.catalog_column.candidate_description IS '缺少注释时生成的候选字段说明，必须人工确认。';
COMMENT ON COLUMN ai.catalog_column.business_name IS '人工维护的字段中文业务名称。';
COMMENT ON COLUMN ai.catalog_column.business_meaning IS '人工确认的字段业务含义、单位或枚举。';
COMMENT ON COLUMN ai.catalog_column.is_primary_key IS '字段是否属于主键。';
COMMENT ON COLUMN ai.catalog_column.is_unique IS '字段是否受单字段唯一约束。';
COMMENT ON COLUMN ai.catalog_column.foreign_key_reference IS '外键目标schema、表和字段JSON。';
COMMENT ON COLUMN ai.catalog_column.index_definitions IS '包含该字段的常用索引定义JSON数组。';
COMMENT ON COLUMN ai.catalog_column.is_sensitive IS '字段是否为敏感字段。';
COMMENT ON COLUMN ai.catalog_column.mask_rule IS '查询结果脱敏规则。';
COMMENT ON COLUMN ai.catalog_column.metadata_status IS '字段元数据状态：pending、confirmed或disabled。';
COMMENT ON COLUMN ai.catalog_column.scanned_at IS '字段最近扫描时间。';
COMMENT ON COLUMN ai.catalog_column.updated_by IS '最后人工维护的IAM用户主键。';
COMMENT ON COLUMN ai.catalog_column.updated_at IS '字段目录最后更新时间。';
