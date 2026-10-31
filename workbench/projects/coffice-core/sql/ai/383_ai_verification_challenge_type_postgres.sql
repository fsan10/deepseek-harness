ALTER TABLE ai.verification_challenge
    ADD COLUMN IF NOT EXISTS challenge_type VARCHAR(32) NOT NULL DEFAULT 'verification_code';

ALTER TABLE ai.verification_challenge
    DROP CONSTRAINT IF EXISTS ck_ai_verification_challenge_type;

ALTER TABLE ai.verification_challenge
    ADD CONSTRAINT ck_ai_verification_challenge_type
    CHECK (challenge_type IN ('verification_code', 'archive_password'));

COMMENT ON COLUMN ai.verification_challenge.challenge_type IS
    '自动化请求类型：verification_code=短信验证码，archive_password=压缩包解压密码、文件提取码或文档密码；两类答案分别解析。';
