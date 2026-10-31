-- 极简 AI：移除 Skill、应用层 AI 数据权限和飞书用户绑定，并增加每日报告。
-- 仅修改 ai schema 与对应 IAM 资源，不触碰任何 ODS 对象或数据。

ALTER TABLE IF EXISTS ai.conversation DROP COLUMN IF EXISTS skill_version_id;
ALTER TABLE IF EXISTS ai.conversation DROP COLUMN IF EXISTS skill_id;
ALTER TABLE IF EXISTS ai.prompt_template DROP COLUMN IF EXISTS recommended_skill_id;
ALTER TABLE IF EXISTS ai.feishu_app DROP COLUMN IF EXISTS default_skill_id;

DROP TABLE IF EXISTS ai.access_policy;
DROP TABLE IF EXISTS ai.skill_version;
DROP TABLE IF EXISTS ai.skill;
DROP TABLE IF EXISTS ai.feishu_identity_binding;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ai' AND table_name='prompt_template' AND column_name='command_alias')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ai' AND table_name='prompt_template' AND column_name='selection_alias') THEN
        ALTER TABLE ai.prompt_template RENAME COLUMN command_alias TO selection_alias;
    END IF;
END $$;
COMMENT ON COLUMN ai.prompt_template.selection_alias IS '斜杠提示词面板使用的简短选择别名。';

ALTER TABLE ai.conversation ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE ai.conversation ADD COLUMN IF NOT EXISTS external_actor_id VARCHAR(200);
COMMENT ON COLUMN ai.conversation.user_id IS '网页端IAM用户主键；飞书和系统任务为空。';
COMMENT ON COLUMN ai.conversation.external_actor_id IS '飞书用户或系统任务的脱敏外部标识。';

ALTER TABLE ai.query_audit ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE ai.query_audit ADD COLUMN IF NOT EXISTS external_actor_id VARCHAR(200);
COMMENT ON COLUMN ai.query_audit.user_id IS '网页调用IAM用户；飞书和系统任务为空。';
COMMENT ON COLUMN ai.query_audit.external_actor_id IS '飞书或系统任务外部标识，不保存令牌。';

ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS daily_report_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS daily_report_time TIME NOT NULL DEFAULT TIME '09:00';
ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS daily_report_timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai';
ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS daily_report_chat_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS daily_report_prompt_template_id BIGINT REFERENCES ai.prompt_template(prompt_template_id);
ALTER TABLE ai.feishu_app ADD COLUMN IF NOT EXISTS last_daily_report_date DATE;
COMMENT ON COLUMN ai.feishu_app.daily_report_enabled IS '是否按日自动生成并发送经营分析报告。';
COMMENT ON COLUMN ai.feishu_app.daily_report_time IS '每日报告在配置时区内的触发时间。';
COMMENT ON COLUMN ai.feishu_app.daily_report_timezone IS '每日报告IANA时区名称。';
COMMENT ON COLUMN ai.feishu_app.daily_report_chat_ids IS '接收每日报告的飞书群聊ID数组。';
COMMENT ON COLUMN ai.feishu_app.daily_report_prompt_template_id IS '每日报告使用的提示词模板。';
COMMENT ON COLUMN ai.feishu_app.last_daily_report_date IS '最近一次成功发送报告的业务日期。';

CREATE TABLE IF NOT EXISTS ai.daily_report_run (
    daily_report_run_id BIGSERIAL PRIMARY KEY,
    feishu_app_id BIGINT NOT NULL REFERENCES ai.feishu_app(feishu_app_id),
    report_date DATE NOT NULL,
    chat_id VARCHAR(180) NOT NULL,
    status VARCHAR(16) NOT NULL CHECK (status IN ('started','success','failed','cancelled')),
    error_category VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    retention_until TIMESTAMPTZ NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL '365 days'),
    CONSTRAINT uq_ai_daily_report_target UNIQUE (feishu_app_id, report_date, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_ai_daily_report_run_date ON ai.daily_report_run (report_date DESC, status);
COMMENT ON TABLE ai.daily_report_run IS '飞书每日经营分析报告执行记录和幂等控制。';
COMMENT ON COLUMN ai.daily_report_run.daily_report_run_id IS '每日报告执行主键。';
COMMENT ON COLUMN ai.daily_report_run.feishu_app_id IS '使用的飞书应用配置。';
COMMENT ON COLUMN ai.daily_report_run.report_date IS '配置时区内的报告日期。';
COMMENT ON COLUMN ai.daily_report_run.chat_id IS '报告接收群聊ID。';
COMMENT ON COLUMN ai.daily_report_run.status IS '执行状态。';
COMMENT ON COLUMN ai.daily_report_run.error_category IS '脱敏错误分类。';
COMMENT ON COLUMN ai.daily_report_run.started_at IS '开始时间。';
COMMENT ON COLUMN ai.daily_report_run.completed_at IS '完成时间。';
COMMENT ON COLUMN ai.daily_report_run.retention_until IS '建议保留截止时间。';

DELETE FROM iam.permission_resource
WHERE resource_code IN ('ai.skill.manage','ai.permission.manage','ai.feishu_binding.manage');
