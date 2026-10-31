INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
VALUES ('module.ai', 'AI管理', 'module', 'ai', NULL, '/ai/', 60, TRUE, NOW())
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name, route_path=EXCLUDED.route_path,
    display_order=EXCLUDED.display_order, is_active=TRUE, updated_at=NOW();

WITH resources(resource_code, resource_name, resource_type, parent_code, route_path, display_order) AS (
    VALUES
    ('ai.analysis.view','AI数据分析','page','module.ai','/ai/',10),
    ('ai.analysis.query','发起AI只读分析','action','ai.analysis.view',NULL,11),
    ('ai.model.manage','模型配置','page','module.ai','/ai-admin/#models',20),
    ('ai.datasource.manage','数据源管理','page','module.ai','/ai-admin/#sources',30),
    ('ai.prompt.manage','提示词模板','page','module.ai','/ai-admin/#prompts',50),
    ('ai.feishu_app.manage','飞书应用配置','page','module.ai','/ai-admin/#feishuApps',60),
    ('ai.audit.view','AI会话与审计','page','module.ai','/ai-admin/#audit',70)
)
INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT r.resource_code,r.resource_name,r.resource_type,'ai',p.resource_id,r.route_path,r.display_order,TRUE,NOW()
FROM resources r JOIN iam.permission_resource p ON p.resource_code=r.parent_code
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name=EXCLUDED.resource_name, resource_type=EXCLUDED.resource_type,
    parent_resource_id=EXCLUDED.parent_resource_id, route_path=EXCLUDED.route_path,
    display_order=EXCLUDED.display_order, is_active=TRUE, updated_at=NOW();

INSERT INTO ai.provider_config (
    config_code,config_name,provider_code,api_base_url,model_name,temperature,
    request_timeout_seconds,thinking_enabled,is_active,is_default
)
VALUES ('deepseek_default','DeepSeek 默认配置','deepseek','https://api.deepseek.com',
        'deepseek-v4-flash',0.20,120,FALSE,FALSE,TRUE)
ON CONFLICT (config_code) DO NOTHING;

WITH templates(template_code,template_name,selection_alias,description,content,sort_order,is_default) AS (
    VALUES
    ('general_operations','通用经营分析','general','概览核心指标、趋势与异常。','收到明确的指标、平台、月份或日期范围、粒度和维度后直接完成详细经营分析，不重复确认。年份未写时采用最近有匹配数据的年份；月份数据不完整时分析已有日期并明确缺失范围。报告充分展开结论摘要、按日数据与趋势、公司和店铺贡献、异常、口径、范围、来源、限制及可执行建议。',10,TRUE),
    ('period_comparison','同比环比分析','compare','对指定指标进行同比与环比。','先确认同比和环比的可比期间及一致口径，再计算变化量、变化率并解释主要维度贡献。',20,FALSE),
    ('anomaly_change','异常波动分析','anomaly','定位异常波动和可能因素。','识别异常波动的时间区间，从平台、公司、店铺和状态等维度逐层核验，仅将数据支持的因素表述为事实。',30,FALSE),
    ('data_quality','数据质量检查','quality','检查缺失、重复、异常值和刷新状态。','从完整性、唯一性、合理性、时效性检查数据质量，列出证据、影响范围和建议。',40,FALSE),
    ('metric_definition','指标口径说明','definition','解释指标字段、公式和筛选口径。','依据 ads、dim 实时元数据与数据库注释说明指标定义、字段、公式、日期、状态与单位；缺少注释的口径标记为待核实。',50,FALSE),
    ('daily_operations_report','每日经营分析报告','daily','按最新完整数据日期生成每日经营报告。','根据用户一句话直接生成完整每日经营报告，不重复确认。自动识别最近匹配年份和已有数据日期，分析按日趋势、公司贡献、店铺贡献、异常波动、计算口径、筛选范围、数据来源、数据缺口与可执行建议；只输出最终报告，不输出工具调用或内部计划。',60,FALSE)
)
INSERT INTO ai.prompt_template (
    template_code,template_name,selection_alias,description,
    is_enabled,is_default,web_available,feishu_available,current_version,sort_order
)
SELECT template_code,template_name,selection_alias,description,TRUE,is_default,TRUE,TRUE,1,sort_order
FROM templates
ON CONFLICT (template_code) DO NOTHING;

WITH templates(template_code,content) AS (
    VALUES
    ('general_operations','围绕问题给出经营结论、核心数据、趋势或异常、计算口径、时间与筛选范围、数据来源、数据质量限制以及建议继续追问的问题。'),
    ('period_comparison','先确认同比和环比的可比期间及一致口径，再计算变化量、变化率并解释主要维度贡献。'),
    ('anomaly_change','识别异常波动的时间区间，从平台、公司、店铺和状态等维度逐层核验，仅将数据支持的因素表述为事实。'),
    ('data_quality','从完整性、唯一性、合理性、时效性检查数据质量，列出证据、影响范围和建议。'),
    ('metric_definition','依据 ads、dim 实时元数据与数据库注释说明指标定义、字段、公式、日期、状态与单位；缺少注释的口径标记为待核实。'),
    ('daily_operations_report','先从 ads、dim 实时元数据中识别可用日期字段并确认最新完整数据日期，再生成每日经营摘要、核心数据、变化趋势、异常提示、计算口径、来源、数据质量限制和建议追问。')
)
INSERT INTO ai.prompt_template_version (
    prompt_template_id,version_no,template_content,output_format,change_note
)
SELECT p.prompt_template_id,1,t.content,
       '{"sections":["结论摘要","核心数据","趋势或异常","计算口径","时间及筛选范围","数据来源","数据质量或限制","建议继续追问的问题"]}'::jsonb,
       '系统初始化版本'
FROM templates t JOIN ai.prompt_template p ON p.template_code=t.template_code
ON CONFLICT (prompt_template_id,version_no) DO NOTHING;
