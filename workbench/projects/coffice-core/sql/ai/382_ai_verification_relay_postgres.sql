CREATE TABLE IF NOT EXISTS ai.verification_relay_config (
    verification_relay_config_id BIGSERIAL PRIMARY KEY,
    config_code VARCHAR(64) NOT NULL UNIQUE,
    config_name VARCHAR(120) NOT NULL,
    feishu_app_id BIGINT NOT NULL REFERENCES ai.feishu_app(feishu_app_id),
    chat_id VARCHAR(180) NOT NULL,
    mention_open_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    platform_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeout_seconds INTEGER NOT NULL DEFAULT 300 CHECK (timeout_seconds BETWEEN 30 AND 900),
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_test_status VARCHAR(16),
    last_tested_at TIMESTAMPTZ,
    last_error_summary VARCHAR(500),
    created_by BIGINT REFERENCES iam.user_account(user_id),
    updated_by BIGINT REFERENCES iam.user_account(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_verification_relay_enabled
    ON ai.verification_relay_config (is_enabled, feishu_app_id);
COMMENT ON TABLE ai.verification_relay_config IS '自动化验证码转发机器人配置；按平台范围选择独立飞书应用和群聊。';
COMMENT ON COLUMN ai.verification_relay_config.verification_relay_config_id IS '验证码转发配置主键。';
COMMENT ON COLUMN ai.verification_relay_config.config_code IS '验证码转发配置唯一编码。';
COMMENT ON COLUMN ai.verification_relay_config.config_name IS '验证码转发配置名称。';
COMMENT ON COLUMN ai.verification_relay_config.feishu_app_id IS '使用的飞书应用配置主键，不与每日报告配置混用。';
COMMENT ON COLUMN ai.verification_relay_config.chat_id IS '接收验证码请求的飞书群聊 ID，必须为 oc_ 开头。';
COMMENT ON COLUMN ai.verification_relay_config.mention_open_ids IS '需要被提醒的负责人飞书 open_id JSON 数组。';
COMMENT ON COLUMN ai.verification_relay_config.platform_scopes IS '适用平台中文名 JSON 数组；空数组表示所有平台。';
COMMENT ON COLUMN ai.verification_relay_config.timeout_seconds IS '验证码请求等待时长，单位秒，范围 30 到 900。';
COMMENT ON COLUMN ai.verification_relay_config.is_enabled IS '是否允许自动化任务使用该转发配置。';
COMMENT ON COLUMN ai.verification_relay_config.last_test_status IS '最近测试状态：success 或 failed。';
COMMENT ON COLUMN ai.verification_relay_config.last_tested_at IS '最近测试时间。';
COMMENT ON COLUMN ai.verification_relay_config.last_error_summary IS '最近脱敏错误摘要。';
COMMENT ON COLUMN ai.verification_relay_config.created_by IS '创建配置的 IAM 用户。';
COMMENT ON COLUMN ai.verification_relay_config.updated_by IS '最后修改配置的 IAM 用户。';
COMMENT ON COLUMN ai.verification_relay_config.created_at IS '创建时间。';
COMMENT ON COLUMN ai.verification_relay_config.updated_at IS '最后修改时间。';

CREATE TABLE IF NOT EXISTS ai.verification_challenge (
    challenge_uuid UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    verification_relay_config_id BIGINT NOT NULL REFERENCES ai.verification_relay_config(verification_relay_config_id),
    platform_name VARCHAR(64) NOT NULL,
    company_name VARCHAR(200) NOT NULL,
    shop_name VARCHAR(200) NOT NULL,
    purpose VARCHAR(120) NOT NULL,
    page_url TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','answered','expired','cancelled')),
    answer_ciphertext TEXT,
    answer_nonce VARCHAR(80),
    answered_by VARCHAR(180),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ NOT NULL,
    answered_at TIMESTAMPTZ,
    retention_until TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '7 days')
);
CREATE INDEX IF NOT EXISTS idx_ai_verification_challenge_poll
    ON ai.verification_challenge (verification_relay_config_id, status, expires_at, created_at DESC);
COMMENT ON TABLE ai.verification_challenge IS '自动化验证码请求状态；答案仅以AES-GCM密文短期保存。';
COMMENT ON COLUMN ai.verification_challenge.challenge_uuid IS '自动化任务轮询使用的不可枚举请求 UUID。';
COMMENT ON COLUMN ai.verification_challenge.verification_relay_config_id IS '发起请求的验证码转发配置。';
COMMENT ON COLUMN ai.verification_challenge.platform_name IS '需要验证码的平台中文名。';
COMMENT ON COLUMN ai.verification_challenge.company_name IS '需要验证码的公司名称。';
COMMENT ON COLUMN ai.verification_challenge.shop_name IS '需要验证码的店铺名称。';
COMMENT ON COLUMN ai.verification_challenge.purpose IS '自动化验证用途，例如登录验证码、订单文件提取码或压缩包解压密码。';
COMMENT ON COLUMN ai.verification_challenge.page_url IS '发起验证码时的页面地址，供负责人识别任务。';
COMMENT ON COLUMN ai.verification_challenge.status IS '请求状态：pending、answered、expired 或 cancelled。';
COMMENT ON COLUMN ai.verification_challenge.answer_ciphertext IS '负责人回复的验证码密文，不保存明文。';
COMMENT ON COLUMN ai.verification_challenge.answer_nonce IS '验证码密文的AES-GCM随机数。';
COMMENT ON COLUMN ai.verification_challenge.answered_by IS '回复验证码的飞书 open_id。';
COMMENT ON COLUMN ai.verification_challenge.created_at IS '请求创建时间。';
COMMENT ON COLUMN ai.verification_challenge.expires_at IS '请求过期时间。';
COMMENT ON COLUMN ai.verification_challenge.answered_at IS '验证码被接收的时间。';
COMMENT ON COLUMN ai.verification_challenge.retention_until IS '请求与密文的建议清理截止时间。';
