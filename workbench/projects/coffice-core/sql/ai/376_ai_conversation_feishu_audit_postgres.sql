CREATE TABLE IF NOT EXISTS ai.conversation (
    conversation_id BIGSERIAL PRIMARY KEY,
    conversation_uuid UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    user_id BIGINT REFERENCES iam.user_account(user_id),
    channel VARCHAR(16) NOT NULL CHECK (channel IN ('web','feishu')),
    title VARCHAR(200) NOT NULL DEFAULT '新对话',
    provider_config_id BIGINT REFERENCES ai.provider_config(provider_config_id),
    prompt_template_id BIGINT REFERENCES ai.prompt_template(prompt_template_id),
    prompt_template_version_id BIGINT REFERENCES ai.prompt_template_version(prompt_template_version_id),
    external_chat_id VARCHAR(160),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived','deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retention_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ai_conversation_user ON ai.conversation (user_id, updated_at DESC) WHERE status <> 'deleted';
COMMENT ON TABLE ai.conversation IS '网页与飞书共用的AI会话；网页按IAM用户隔离，飞书按外部会话隔离。';
COMMENT ON COLUMN ai.conversation.conversation_id IS '会话内部主键。';
COMMENT ON COLUMN ai.conversation.conversation_uuid IS '对外不可枚举的会话UUID。';
COMMENT ON COLUMN ai.conversation.user_id IS '网页端IAM用户主键；飞书和系统任务为空。';
COMMENT ON COLUMN ai.conversation.channel IS '会话来源渠道：web或feishu。';
COMMENT ON COLUMN ai.conversation.title IS '会话标题。';
COMMENT ON COLUMN ai.conversation.provider_config_id IS '创建或最近提问使用的模型配置。';
COMMENT ON COLUMN ai.conversation.prompt_template_id IS '会话选用提示词模板。';
COMMENT ON COLUMN ai.conversation.prompt_template_version_id IS '会话固定使用的模板版本。';
COMMENT ON COLUMN ai.conversation.external_chat_id IS '飞书群或私聊标识，网页端为空。';
COMMENT ON COLUMN ai.conversation.status IS '状态：active、archived或deleted。';
COMMENT ON COLUMN ai.conversation.created_at IS '创建时间。';
COMMENT ON COLUMN ai.conversation.updated_at IS '最后活动时间。';
COMMENT ON COLUMN ai.conversation.retention_until IS '会话内容建议保留截止时间。';

CREATE TABLE IF NOT EXISTS ai.message (
    message_id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES ai.conversation(conversation_id),
    role VARCHAR(16) NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'completed' CHECK (status IN ('pending','streaming','completed','failed','cancelled')),
    source_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    calculation_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms INTEGER,
    error_category VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_message_conversation ON ai.message (conversation_id, message_id);
COMMENT ON TABLE ai.message IS 'AI会话消息和回答依据摘要，不保存凭据。';
COMMENT ON COLUMN ai.message.message_id IS '消息主键。';
COMMENT ON COLUMN ai.message.conversation_id IS '所属会话主键。';
COMMENT ON COLUMN ai.message.role IS '消息角色。';
COMMENT ON COLUMN ai.message.content IS '消息正文；数据库内容仅作为数据而非系统指令。';
COMMENT ON COLUMN ai.message.status IS '生成状态。';
COMMENT ON COLUMN ai.message.source_summary IS '可向用户展示的数据来源、SQL哈希和耗时摘要。';
COMMENT ON COLUMN ai.message.calculation_scope IS '时间范围、筛选条件和计算口径JSON。';
COMMENT ON COLUMN ai.message.token_usage IS '模型Token用量JSON。';
COMMENT ON COLUMN ai.message.latency_ms IS '端到端耗时毫秒。';
COMMENT ON COLUMN ai.message.error_category IS '脱敏后的错误分类。';
COMMENT ON COLUMN ai.message.created_at IS '消息创建时间。';

CREATE TABLE IF NOT EXISTS ai.tool_execution (
    tool_execution_id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES ai.conversation(conversation_id),
    message_id BIGINT REFERENCES ai.message(message_id),
    tool_name VARCHAR(64) NOT NULL,
    argument_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(16) NOT NULL CHECK (status IN ('started','success','failed','cancelled','rejected')),
    result_row_count INTEGER,
    latency_ms INTEGER,
    error_category VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ai_tool_conversation ON ai.tool_execution (conversation_id, started_at DESC);
COMMENT ON TABLE ai.tool_execution IS '模型受控工具调用执行链路审计。';
COMMENT ON COLUMN ai.tool_execution.tool_execution_id IS '工具执行主键。';
COMMENT ON COLUMN ai.tool_execution.conversation_id IS '所属会话主键。';
COMMENT ON COLUMN ai.tool_execution.message_id IS '触发工具调用的消息。';
COMMENT ON COLUMN ai.tool_execution.tool_name IS '受控工具名称。';
COMMENT ON COLUMN ai.tool_execution.argument_summary IS '脱敏参数摘要，不含查询结果和凭据。';
COMMENT ON COLUMN ai.tool_execution.status IS '执行状态。';
COMMENT ON COLUMN ai.tool_execution.result_row_count IS '返回结果行数。';
COMMENT ON COLUMN ai.tool_execution.latency_ms IS '工具耗时毫秒。';
COMMENT ON COLUMN ai.tool_execution.error_category IS '脱敏错误分类。';
COMMENT ON COLUMN ai.tool_execution.started_at IS '开始时间。';
COMMENT ON COLUMN ai.tool_execution.finished_at IS '结束时间。';

CREATE TABLE IF NOT EXISTS ai.query_audit (
    query_audit_id BIGSERIAL PRIMARY KEY,
    tool_execution_id BIGINT REFERENCES ai.tool_execution(tool_execution_id),
    user_id BIGINT REFERENCES iam.user_account(user_id),
    department_id BIGINT REFERENCES iam.department(department_id),
    channel VARCHAR(16) NOT NULL,
    data_source_id BIGINT NOT NULL REFERENCES ai.data_source(data_source_id),
    accessed_objects JSONB NOT NULL DEFAULT '[]'::jsonb,
    accessed_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
    sql_hash CHAR(64) NOT NULL,
    elapsed_ms INTEGER,
    returned_rows INTEGER NOT NULL DEFAULT 0,
    was_masked BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('success','failed','cancelled','rejected')),
    error_category VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retention_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ai_query_audit_filter ON ai.query_audit (created_at DESC, user_id, status, channel);
COMMENT ON TABLE ai.query_audit IS '只读查询审计，仅存SQL哈希和对象信息，不存密码及完整SQL。';
COMMENT ON COLUMN ai.query_audit.query_audit_id IS '查询审计主键。';
COMMENT ON COLUMN ai.query_audit.tool_execution_id IS '对应工具执行主键。';
COMMENT ON COLUMN ai.query_audit.user_id IS '网页调用IAM用户；飞书和系统任务为空。';
COMMENT ON COLUMN ai.query_audit.department_id IS '调用时用户部门。';
COMMENT ON COLUMN ai.query_audit.channel IS '调用渠道。';
COMMENT ON COLUMN ai.query_audit.data_source_id IS '查询数据源。';
COMMENT ON COLUMN ai.query_audit.accessed_objects IS '实际访问的数据库对象规范键。';
COMMENT ON COLUMN ai.query_audit.accessed_columns IS '实际访问字段规范键。';
COMMENT ON COLUMN ai.query_audit.sql_hash IS '规范SQL的SHA-256摘要。';
COMMENT ON COLUMN ai.query_audit.elapsed_ms IS '执行耗时毫秒。';
COMMENT ON COLUMN ai.query_audit.returned_rows IS '返回行数。';
COMMENT ON COLUMN ai.query_audit.was_masked IS '结果是否应用了脱敏。';
COMMENT ON COLUMN ai.query_audit.status IS '查询状态。';
COMMENT ON COLUMN ai.query_audit.error_category IS '脱敏错误分类。';
COMMENT ON COLUMN ai.query_audit.created_at IS '审计创建时间。';
COMMENT ON COLUMN ai.query_audit.retention_until IS '建议保留截止时间。';

CREATE TABLE IF NOT EXISTS ai.feishu_app (
    feishu_app_id BIGSERIAL PRIMARY KEY,
    config_code VARCHAR(64) NOT NULL UNIQUE,
    config_name VARCHAR(120) NOT NULL,
    app_id VARCHAR(160) NOT NULL,
    app_secret_ciphertext TEXT NOT NULL,
    app_secret_nonce VARCHAR(80) NOT NULL,
    connection_mode VARCHAR(16) NOT NULL DEFAULT 'long_connection' CHECK (connection_mode IN ('long_connection','webhook')),
    verification_token_ciphertext TEXT,
    verification_token_nonce VARCHAR(80),
    encrypt_key_ciphertext TEXT,
    encrypt_key_nonce VARCHAR(80),
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    group_require_mention BOOLEAN NOT NULL DEFAULT TRUE,
    allow_private_chat BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_chat_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    default_prompt_template_id BIGINT REFERENCES ai.prompt_template(prompt_template_id),
    last_test_status VARCHAR(16),
    last_tested_at TIMESTAMPTZ,
    last_error_summary VARCHAR(500),
    created_by BIGINT REFERENCES iam.user_account(user_id),
    updated_by BIGINT REFERENCES iam.user_account(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);
COMMENT ON TABLE ai.feishu_app IS '飞书应用配置；长期凭据均以AES-GCM密文保存，不保存tenant_access_token。';
COMMENT ON COLUMN ai.feishu_app.feishu_app_id IS '飞书配置主键。';
COMMENT ON COLUMN ai.feishu_app.config_code IS '配置唯一编码。';
COMMENT ON COLUMN ai.feishu_app.config_name IS '配置名称。';
COMMENT ON COLUMN ai.feishu_app.app_id IS '飞书应用App ID，非秘密字段。';
COMMENT ON COLUMN ai.feishu_app.app_secret_ciphertext IS 'AES-GCM加密后的App Secret。';
COMMENT ON COLUMN ai.feishu_app.app_secret_nonce IS 'App Secret加密随机数。';
COMMENT ON COLUMN ai.feishu_app.connection_mode IS '连接模式：长连接或Webhook。';
COMMENT ON COLUMN ai.feishu_app.verification_token_ciphertext IS 'Webhook Verification Token密文。';
COMMENT ON COLUMN ai.feishu_app.verification_token_nonce IS 'Verification Token加密随机数。';
COMMENT ON COLUMN ai.feishu_app.encrypt_key_ciphertext IS 'Webhook Encrypt Key密文。';
COMMENT ON COLUMN ai.feishu_app.encrypt_key_nonce IS 'Encrypt Key加密随机数。';
COMMENT ON COLUMN ai.feishu_app.is_enabled IS '是否启用。';
COMMENT ON COLUMN ai.feishu_app.group_require_mention IS '群聊是否仅响应@机器人消息。';
COMMENT ON COLUMN ai.feishu_app.allow_private_chat IS '是否响应私聊。';
COMMENT ON COLUMN ai.feishu_app.allowed_chat_ids IS '可选群聊白名单JSON数组，仅决定是否响应。';
COMMENT ON COLUMN ai.feishu_app.default_prompt_template_id IS '飞书端默认提示词模板。';
COMMENT ON COLUMN ai.feishu_app.last_test_status IS '最近连接测试状态。';
COMMENT ON COLUMN ai.feishu_app.last_tested_at IS '最近连接测试时间。';
COMMENT ON COLUMN ai.feishu_app.last_error_summary IS '最近脱敏错误摘要。';
COMMENT ON COLUMN ai.feishu_app.created_by IS '创建IAM用户。';
COMMENT ON COLUMN ai.feishu_app.updated_by IS '最后更新IAM用户。';
COMMENT ON COLUMN ai.feishu_app.created_at IS '创建时间。';
COMMENT ON COLUMN ai.feishu_app.updated_at IS '更新时间。';
COMMENT ON COLUMN ai.feishu_app.deleted_at IS '软删除时间。';

CREATE TABLE IF NOT EXISTS ai.feishu_event_dedup (
    event_id VARCHAR(180) PRIMARY KEY,
    feishu_app_id BIGINT NOT NULL REFERENCES ai.feishu_app(feishu_app_id),
    event_type VARCHAR(120),
    chat_id VARCHAR(180),
    message_id VARCHAR(180),
    open_id VARCHAR(180),
    processing_status VARCHAR(16) NOT NULL DEFAULT 'received' CHECK (processing_status IN ('received','processing','success','failed','ignored')),
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    error_category VARCHAR(64),
    retention_until TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '30 days')
);
CREATE INDEX IF NOT EXISTS idx_ai_feishu_event_retention ON ai.feishu_event_dedup (retention_until);
COMMENT ON TABLE ai.feishu_event_dedup IS '飞书事件幂等去重和异步处理状态。';
COMMENT ON COLUMN ai.feishu_event_dedup.event_id IS '飞书事件唯一ID。';
COMMENT ON COLUMN ai.feishu_event_dedup.feishu_app_id IS '接收事件的飞书应用。';
COMMENT ON COLUMN ai.feishu_event_dedup.event_type IS '飞书事件类型。';
COMMENT ON COLUMN ai.feishu_event_dedup.chat_id IS '群聊或私聊ID。';
COMMENT ON COLUMN ai.feishu_event_dedup.message_id IS '飞书消息ID。';
COMMENT ON COLUMN ai.feishu_event_dedup.open_id IS '发件人open_id。';
COMMENT ON COLUMN ai.feishu_event_dedup.processing_status IS '处理状态。';
COMMENT ON COLUMN ai.feishu_event_dedup.received_at IS '首次接收时间。';
COMMENT ON COLUMN ai.feishu_event_dedup.completed_at IS '处理完成时间。';
COMMENT ON COLUMN ai.feishu_event_dedup.error_category IS '脱敏错误分类。';
COMMENT ON COLUMN ai.feishu_event_dedup.retention_until IS '去重记录保留截止时间。';
