-- 简化模型配置：输出长度交由模型服务处理，工具调用轮次改为服务端内部防循环保护。
-- 仅修改 ai.provider_config，不触碰任何业务表或 ODS 数据。

ALTER TABLE IF EXISTS ai.provider_config
    DROP CONSTRAINT IF EXISTS ck_ai_provider_limits;

ALTER TABLE IF EXISTS ai.provider_config
    DROP COLUMN IF EXISTS max_tokens,
    DROP COLUMN IF EXISTS max_tool_rounds;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_ai_provider_request_timeout'
          AND conrelid = 'ai.provider_config'::regclass
    ) THEN
        ALTER TABLE ai.provider_config
            ADD CONSTRAINT ck_ai_provider_request_timeout
            CHECK (request_timeout_seconds BETWEEN 5 AND 600);
    END IF;
END $$;

UPDATE ai.prompt_template_version version
SET template_content = '收到明确的指标、平台、月份或日期范围、粒度和维度后直接完成详细经营分析，不重复确认。年份未写时采用最近有匹配数据的年份；月份数据不完整时分析已有日期并明确缺失范围。报告充分展开结论摘要、按日数据与趋势、公司和店铺贡献、异常、口径、范围、来源、限制及可执行建议。'
FROM ai.prompt_template template
WHERE template.prompt_template_id = version.prompt_template_id
  AND template.template_code = 'general_operations'
  AND version.version_no = template.current_version
  AND version.template_content = '围绕问题给出经营结论、核心数据、趋势或异常、计算口径、时间与筛选范围、数据来源、数据质量限制以及建议继续追问的问题。';

UPDATE ai.prompt_template_version version
SET template_content = '根据用户一句话直接生成完整每日经营报告，不重复确认。自动识别最近匹配年份和已有数据日期，分析按日趋势、公司贡献、店铺贡献、异常波动、计算口径、筛选范围、数据来源、数据缺口与可执行建议；只输出最终报告，不输出工具调用或内部计划。'
FROM ai.prompt_template template
WHERE template.prompt_template_id = version.prompt_template_id
  AND template.template_code = 'daily_operations_report'
  AND version.version_no = template.current_version
  AND version.template_content = '先确认最新完整数据日期，再概览核心指标、趋势、异常、口径、来源、数据限制，并给出后续建议。';
