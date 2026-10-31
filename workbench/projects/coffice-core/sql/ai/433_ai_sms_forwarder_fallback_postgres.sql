CREATE TABLE IF NOT EXISTS ai.sms_forwarder_config (
    sms_forwarder_config_id BIGSERIAL PRIMARY KEY,
    config_code VARCHAR(64) NOT NULL UNIQUE,
    config_name VARCHAR(120) NOT NULL,
    verification_relay_config_id BIGINT NOT NULL UNIQUE REFERENCES ai.verification_relay_config(verification_relay_config_id),
    webhook_ciphertext TEXT NOT NULL,
    webhook_nonce VARCHAR(80) NOT NULL,
    signing_secret_ciphertext TEXT,
    signing_secret_nonce VARCHAR(80),
    trusted_senders JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_test_status VARCHAR(16),
    last_tested_at TIMESTAMPTZ,
    last_error_summary VARCHAR(200),
    created_by BIGINT REFERENCES iam.user_account(user_id),
    updated_by BIGINT REFERENCES iam.user_account(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE ai.sms_forwarder_config IS '短信转发群自定义机器人配置；沿用关联验证码配置的接收应用与群聊。';
COMMENT ON COLUMN ai.sms_forwarder_config.sms_forwarder_config_id IS '短信转发机器人配置主键。';
COMMENT ON COLUMN ai.sms_forwarder_config.config_code IS '配置唯一编码，小写字母数字及下划线。';
COMMENT ON COLUMN ai.sms_forwarder_config.config_name IS '后台显示名称，不用于发送者身份校验。';
COMMENT ON COLUMN ai.sms_forwarder_config.verification_relay_config_id IS '既有验证码接收配置主键；接收应用和群聊不在此重复维护。';
COMMENT ON COLUMN ai.sms_forwarder_config.webhook_ciphertext IS '自定义机器人 Webhook 地址的 AES-GCM 密文，后台只写不读。';
COMMENT ON COLUMN ai.sms_forwarder_config.webhook_nonce IS 'Webhook 密文的 AES-GCM 随机数，base64 编码。';
COMMENT ON COLUMN ai.sms_forwarder_config.signing_secret_ciphertext IS '可选自定义机器人签名密钥的 AES-GCM 密文。';
COMMENT ON COLUMN ai.sms_forwarder_config.signing_secret_nonce IS '签名密钥密文的 AES-GCM 随机数，base64 编码。';
COMMENT ON COLUMN ai.sms_forwarder_config.trusted_senders IS '接收测试确认的发送者身份数组，每项为 id_type 和 id；禁止按机器人名称匹配。';
COMMENT ON COLUMN ai.sms_forwarder_config.is_enabled IS '是否启用自动接收；启用前必须通过发送与历史读取测试。';
COMMENT ON COLUMN ai.sms_forwarder_config.last_test_status IS '最近接收测试状态，success 或 failed。';
COMMENT ON COLUMN ai.sms_forwarder_config.last_tested_at IS '最近接收测试时间。';
COMMENT ON COLUMN ai.sms_forwarder_config.last_error_summary IS '最近非敏感错误分类，不含短信、地址、签名或验证码。';
COMMENT ON COLUMN ai.sms_forwarder_config.created_by IS '创建配置的 IAM 用户主键。';
COMMENT ON COLUMN ai.sms_forwarder_config.updated_by IS '最后修改配置的 IAM 用户主键。';
COMMENT ON COLUMN ai.sms_forwarder_config.created_at IS '配置创建时间。';
COMMENT ON COLUMN ai.sms_forwarder_config.updated_at IS '配置更新时间。';

ALTER TABLE ai.verification_challenge
    ADD COLUMN IF NOT EXISTS sms_forwarder_config_id BIGINT REFERENCES ai.sms_forwarder_config(sms_forwarder_config_id),
    ADD COLUMN IF NOT EXISTS sms_route_key VARCHAR(64),
    ADD COLUMN IF NOT EXISTS sms_stream_key VARCHAR(180),
    ADD COLUMN IF NOT EXISTS business_reference VARCHAR(180),
    ADD COLUMN IF NOT EXISTS auto_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS human_fallback_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS human_notice_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS human_notice_message_id VARCHAR(180),
    ADD COLUMN IF NOT EXISTS answer_source VARCHAR(16),
    ADD COLUMN IF NOT EXISTS source_message_id VARCHAR(180);
COMMENT ON COLUMN ai.verification_challenge.sms_forwarder_config_id IS '本次请求绑定的短信转发机器人配置；NULL 表示人工接收。';
COMMENT ON COLUMN ai.verification_challenge.sms_route_key IS '平台与用途规则编码，不从店铺名称推测短信归属。';
COMMENT ON COLUMN ai.verification_challenge.sms_stream_key IS '不可区分短信流的互斥键，关联转发配置和平台。';
COMMENT ON COLUMN ai.verification_challenge.business_reference IS '请求关联的实际文件或导出任务编号，例如京东 taskid；不得虚构。';
COMMENT ON COLUMN ai.verification_challenge.auto_until IS '自动接收截止时间，默认创建后 120 秒，早于总等待截止。';
COMMENT ON COLUMN ai.verification_challenge.human_fallback_at IS '转入人工兜底的时间；自动超时、通道故障或平台判错时设置。';
COMMENT ON COLUMN ai.verification_challenge.human_notice_sent_at IS '人工兜底通知成功发送时间，防止重复提醒。';
COMMENT ON COLUMN ai.verification_challenge.human_notice_message_id IS '人工通知飞书消息 ID，用于多任务回复关联。';
COMMENT ON COLUMN ai.verification_challenge.answer_source IS '答案来源 auto 或 human；密文仍保存于既有答案字段。';
COMMENT ON COLUMN ai.verification_challenge.source_message_id IS '提供当前答案的飞书消息 ID，不保存消息原文。';

CREATE TABLE IF NOT EXISTS ai.verification_message_receipt (
    feishu_app_id BIGINT NOT NULL REFERENCES ai.feishu_app(feishu_app_id),
    message_id VARCHAR(180) NOT NULL,
    challenge_uuid UUID NOT NULL REFERENCES ai.verification_challenge(challenge_uuid) ON DELETE CASCADE,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (feishu_app_id, message_id)
);
COMMENT ON TABLE ai.verification_message_receipt IS '验证码消息的唯一任务归属；事件和历史入口共用，错误答案也不能再次分配。';
COMMENT ON COLUMN ai.verification_message_receipt.feishu_app_id IS '读取消息的接收应用配置主键。';
COMMENT ON COLUMN ai.verification_message_receipt.message_id IS '飞书消息 ID，与接收应用联合唯一，不能用 event_id 替代。';
COMMENT ON COLUMN ai.verification_message_receipt.challenge_uuid IS '消息唯一绑定的 Challenge；删除请求时硬删除收据。';
COMMENT ON COLUMN ai.verification_message_receipt.received_at IS '首次绑定时间，不包含答案明文。';
