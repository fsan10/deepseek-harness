ALTER TABLE ai.verification_challenge
    ADD COLUMN IF NOT EXISTS answer_notice_sent_at TIMESTAMPTZ;
COMMENT ON COLUMN ai.verification_challenge.answer_notice_sent_at IS
    '当前答案接收成功回执发送时间；自动与人工入口共用，发送失败由轮询重试，判错后清空。';
