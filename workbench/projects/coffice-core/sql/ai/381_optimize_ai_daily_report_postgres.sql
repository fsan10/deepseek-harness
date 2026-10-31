-- 优化每日经营报告提示词：一次性判断最近可用日期、日期连续性和数据量。
-- 仅更新 AI 提示词配置，不触碰任何业务表或 ODS 数据。

ALTER TABLE IF EXISTS ai.data_source
    DROP CONSTRAINT IF EXISTS ck_ai_source_limits;

ALTER TABLE IF EXISTS ai.data_source
    DROP CONSTRAINT IF EXISTS ck_ai_source_timeouts;

ALTER TABLE IF EXISTS ai.data_source
    DROP COLUMN IF EXISTS default_max_rows;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_ai_source_timeouts'
          AND conrelid = 'ai.data_source'::regclass
    ) THEN
        ALTER TABLE ai.data_source
            ADD CONSTRAINT ck_ai_source_timeouts CHECK (
                connect_timeout_seconds BETWEEN 1 AND 60
                AND statement_timeout_ms BETWEEN 100 AND 300000
                AND lock_timeout_ms BETWEEN 100 AND 30000
                AND idle_transaction_timeout_ms BETWEEN 1000 AND 300000
            );
    END IF;
END $$;

UPDATE ai.prompt_template_version version
SET template_content = '根据用户一句话直接生成完整每日经营报告，不重复确认。先从实时 ads、dim 元数据中选出最相关的业务事实表，不要枚举全部 ADS 表；首次查询应尽可能一次性得到最早日期、最新日期、日期数、数据量和日期连续性，并采用最近可用日期。随后使用聚合查询完成核心指标、趋势、公司与店铺贡献、异常波动分析，避免逐表、逐日重复摸底和无意义明细查询。完整说明计算口径、筛选范围、数据来源、数据缺口与可执行建议；只输出最终报告，不输出工具调用或内部计划。'
FROM ai.prompt_template template
WHERE template.prompt_template_id = version.prompt_template_id
  AND template.template_code = 'daily_operations_report'
  AND version.version_no = template.current_version;

UPDATE ai.prompt_template_version version
SET template_content = '收到明确的指标、平台、月份或日期范围、粒度和维度后直接完成详细经营分析，不重复确认。年份未写时采用最近有匹配数据的年份；月份数据不完整时分析已有日期并明确缺失范围。涉及最新日期时，先选择最相关事实表，并尽可能用一次聚合查询确认最早日期、最新日期、日期数、数据量和日期连续性，不要逐表反复摸底。报告充分展开结论摘要、按日数据与趋势、公司和店铺贡献、异常、口径、范围、来源、限制及可执行建议。'
FROM ai.prompt_template template
WHERE template.prompt_template_id = version.prompt_template_id
  AND template.template_code = 'general_operations'
  AND version.version_no = template.current_version;
