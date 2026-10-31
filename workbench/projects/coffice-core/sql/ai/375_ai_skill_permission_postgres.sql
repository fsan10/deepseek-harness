CREATE TABLE IF NOT EXISTS ai.prompt_template (
    prompt_template_id BIGSERIAL PRIMARY KEY,
    template_code VARCHAR(64) NOT NULL UNIQUE,
    template_name VARCHAR(120) NOT NULL,
    selection_alias VARCHAR(48) NOT NULL UNIQUE,
    description VARCHAR(500),
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    web_available BOOLEAN NOT NULL DEFAULT TRUE,
    feishu_available BOOLEAN NOT NULL DEFAULT TRUE,
    current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version > 0),
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_by BIGINT REFERENCES iam.user_account(user_id),
    updated_by BIGINT REFERENCES iam.user_account(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMPTZ
);
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ai' AND table_name='prompt_template' AND column_name='command_alias')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ai' AND table_name='prompt_template' AND column_name='selection_alias') THEN
        ALTER TABLE ai.prompt_template RENAME COLUMN command_alias TO selection_alias;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_prompt_one_default ON ai.prompt_template ((1)) WHERE is_default AND is_enabled AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_ai_prompt_active_sort ON ai.prompt_template (is_enabled, sort_order) WHERE deleted_at IS NULL;
COMMENT ON TABLE ai.prompt_template IS '网页和飞书共用的AI提示词模板主记录。';
COMMENT ON COLUMN ai.prompt_template.prompt_template_id IS '提示词模板主键。';
COMMENT ON COLUMN ai.prompt_template.template_code IS '模板唯一英文编码。';
COMMENT ON COLUMN ai.prompt_template.template_name IS '模板显示名称。';
COMMENT ON COLUMN ai.prompt_template.selection_alias IS '斜杠提示词面板使用的简短选择别名。';
COMMENT ON COLUMN ai.prompt_template.description IS '模板简要说明。';
COMMENT ON COLUMN ai.prompt_template.is_enabled IS '是否启用。';
COMMENT ON COLUMN ai.prompt_template.is_default IS '是否为唯一默认模板。';
COMMENT ON COLUMN ai.prompt_template.web_available IS '网页端是否可用。';
COMMENT ON COLUMN ai.prompt_template.feishu_available IS '飞书端是否可用。';
COMMENT ON COLUMN ai.prompt_template.current_version IS '当前生效版本号。';
COMMENT ON COLUMN ai.prompt_template.sort_order IS '显示排序。';
COMMENT ON COLUMN ai.prompt_template.created_by IS '创建IAM用户主键。';
COMMENT ON COLUMN ai.prompt_template.updated_by IS '最后更新IAM用户主键。';
COMMENT ON COLUMN ai.prompt_template.created_at IS '创建时间。';
COMMENT ON COLUMN ai.prompt_template.updated_at IS '更新时间。';
COMMENT ON COLUMN ai.prompt_template.deleted_at IS '软删除时间。';

CREATE TABLE IF NOT EXISTS ai.prompt_template_version (
    prompt_template_version_id BIGSERIAL PRIMARY KEY,
    prompt_template_id BIGINT NOT NULL REFERENCES ai.prompt_template(prompt_template_id),
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    template_content TEXT NOT NULL,
    output_format JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_note VARCHAR(500),
    created_by BIGINT REFERENCES iam.user_account(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ai_prompt_version UNIQUE (prompt_template_id, version_no)
);
COMMENT ON TABLE ai.prompt_template_version IS '不可变提示词模板版本。';
COMMENT ON COLUMN ai.prompt_template_version.prompt_template_version_id IS '提示词模板版本主键。';
COMMENT ON COLUMN ai.prompt_template_version.prompt_template_id IS '所属提示词模板主键。';
COMMENT ON COLUMN ai.prompt_template_version.version_no IS '单模板内递增版本号。';
COMMENT ON COLUMN ai.prompt_template_version.template_content IS '提示词正文，不允许包含凭据。';
COMMENT ON COLUMN ai.prompt_template_version.output_format IS '模板默认回答格式JSON。';
COMMENT ON COLUMN ai.prompt_template_version.change_note IS '版本变更说明。';
COMMENT ON COLUMN ai.prompt_template_version.created_by IS '创建该版本的IAM用户。';
COMMENT ON COLUMN ai.prompt_template_version.created_at IS '版本创建时间。';
