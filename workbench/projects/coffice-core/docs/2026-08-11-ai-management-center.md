# 极简 AI 数据分析中心实施说明

## 实现范围

本期保留 AI 数据分析、DeepSeek 模型配置、PostgreSQL 数据源、提示词模板、飞书应用配置和会话审计。数据目录页面和持久化目录已删除；网页与飞书复用同一个 `AiAnalysisService`、提示词、实时元数据探查、只读 SQL 执行器和审计链路。

已删除 Skill 管理、AI 数据权限、飞书用户绑定、`@数据`和通用 `/命令`。网页输入 `/` 只打开提示词选择面板，不执行命令。飞书成员无需绑定系统用户，群内可见范围由飞书自身控制。

## 模块结构

- `apps/ai_analysis/`：DeepSeek 客户端、统一对话编排、固定安全规则、AST SQL 校验、只读查询和审计。
- `apps/ai_admin/`：模型、数据源、目录、提示词、飞书应用和审计 API。
- `apps/ai_web/`：会话列表、消息渲染、SSE 对话和提示词选择面板。
- `apps/feishu_ai/`：Webhook、官方 SDK 长连接、事件去重、群聊问答和每日报告调度。
- `apps/fund_split_adjust/server.py`：模块挂载、统一认证、CSRF 和服务生命周期。

## 调用链

1. 网页端验证 IAM 会话和 AI 页面权限；飞书端验证应用配置、事件签名、群白名单及 @ 规则。
2. 使用只读账号实时探查启用数据源中实际可见的 `ads`、`dim` 表、视图、字段和数据库注释。
3. DeepSeek 只能调用受控 metadata/query 工具。
4. 服务端使用 `sqlglot` 重解析 SQL，并按本次实时发现的对象逐表逐字段校验。
5. 数据源专用 PostgreSQL 账号在 `READ ONLY` 事务中执行。
6. 结果限行、脱敏后才返回模型。
7. 网页通过 SSE 流式输出；飞书异步分段回复。
8. 保存模板版本、来源、耗时、Token、SQL 哈希和审计记录。

## 数据访问边界

极简版不再按系统用户、角色或部门计算 AI 数据权限。任何拥有网页 AI 页面权限的登录用户，以及符合飞书应用响应规则的群成员，都能分析所有“已启用 AI 数据源”中已扫描的对象。

因此，数据隔离必须在 PostgreSQL 专用账号上完成。当前 `mock_ai_reader` 仅有 `ads`、`dim` 的 `USAGE/SELECT`，没有 ODS 权限和写权限，未来新增表不会自动授权。若不同飞书群需要不同数据范围，应配置不同飞书应用、不同只读数据源账号或拆分部署，不能依赖提示词实现隔离。

## 只读 SQL 安全边界

- 只接受单条 `SELECT` 或安全的 `WITH ... SELECT`。
- 拒绝 DML、DDL、`COPY`、`CALL`、`DO`、多语句、`SELECT INTO`、`EXPLAIN ANALYZE`、系统 schema 和危险函数。
- 禁止 `SELECT *` 和未限定 schema 的表名，逐表逐字段校验实时元数据；ODS 和其他 schema 不进入元数据范围。
- 强制只读事务、查询/锁/空闲事务超时、执行计划上限、返回行数上限和取消。
- 敏感字段在返回模型前脱敏；审计只保存 SQL 哈希，不保存完整 SQL 或凭据。
- 固定安全规则内置在服务端，提示词无法覆盖，也不能要求执行写 SQL。

## 每日经营报告

飞书应用配置支持启用每日报告、发送时间、IANA 时区、接收群聊 ID 和报告提示词。后台调度器每 30 秒检查一次到期配置，以“应用 + 日期 + 群聊”唯一约束防止重复发送。报告进入对应群聊的同一 AI 会话，后续群内 @ 机器人提问可延续上下文。执行结果写入 `ai.daily_report_run`。

## 密钥保护

DeepSeek API Key、数据源密码、飞书 App Secret、Verification Token 和 Encrypt Key 使用 AES-256-GCM 加密。主密钥只从 `AI_CONFIG_ENCRYPTION_KEY` 读取；接口只返回掩码，空白编辑保留旧密钥。密钥不会进入前端存储、Cookie、普通日志或审计详情。

## 环境变量

- `AI_CONFIG_ENCRYPTION_KEY`：URL-safe Base64 编码的 32 字节主密钥。

Windows 本机部署应将该值保存为当前用户环境变量，并在首次配置后重新打开
PowerShell。此后可以直接运行：

```powershell
python apps/fund_split_adjust/server.py --bind 0.0.0.0 --port 8770
```

主密钥一旦用于保存模型、数据源或飞书配置就不得重新生成或覆盖，否则已有
密文无法解密；变量值不得写入仓库、日志或启动命令。
- `AI_MAX_ANALYSIS_SECONDS`：默认 180。

单次回答不再按 SQL 查询次数、工具调用次数或返回行数中断，服务端也不会自动向模型 SQL 追加 `LIMIT`。只读事务、SQL AST 校验、数据源查询超时、整次分析超时、取消和审计继续生效；系统提示词要求模型优先聚合，并一次性确认最近可用日期、日期连续性和数据量，避免无意义的大明细与重复摸底。

单一启用数据源由服务端直接选定，模型传入空值或错误 `source_code` 均不能改变目标数据源；存在多个启用数据源时，模型只能选择实时元数据工具公布的编码。失败或取消的提问会保留给页面展示，但不会进入下一轮模型上下文。

模型配置不再保存或发送 `max_tokens`，回答长度由模型服务和详细报告规则决定。会话消息会持续保存；发送给模型的近期上下文由服务端上下文窗口控制，与输出 `max_tokens` 无关。“每日日报”等明确表达会自动选择每日经营报告提示词；用户在网页中手动选择的提示词优先。
- `AI_MAX_CONTEXT_CHARS`：默认 40000。
- `AI_USER_REQUESTS_PER_MINUTE`：默认 10。
- `AI_DEPARTMENT_REQUESTS_PER_MINUTE`：默认 60（飞书/系统任务按渠道计数）。
- `AI_MAX_CONCURRENT_PER_USER`：默认 2。
- `AI_MAX_CONCURRENT_PER_DEPARTMENT`：默认 10。
- `FEISHU_AI_LONG_CONNECTION_ENABLED`：官方 SDK 长连接默认启动；仅在明确设置为 `false` 时关闭。每日报告调度器不依赖此开关。修改飞书应用凭证或连接模式后需重启统一服务以重建长连接。
- `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`：配置中心管理库连接，不得作为 AI 查询账号。

## SQL 清单

- `sql/ai/381_optimize_ai_daily_report_postgres.sql`：优化日报/通用提示词的最近日期与聚合查询策略。

- `sql/ai/374_ai_configuration_catalog_postgres.sql`
- `sql/ai/379_remove_ai_catalog_postgres.sql`
- `sql/ai/375_ai_skill_permission_postgres.sql`（历史编号保留，当前只定义提示词表）
- `sql/ai/376_ai_conversation_feishu_audit_postgres.sql`
- `sql/ai/377_seed_ai_permissions_defaults_postgres.sql`
- `sql/ai/378_simplify_ai_daily_report_postgres.sql`

378 会删除 `ai.skill`、`ai.skill_version`、`ai.access_policy`、`ai.feishu_identity_binding` 及对应 IAM 页面资源，并新增每日报告配置和执行表。全部脚本显式指定 schema、可重复执行且不触碰 ODS。

## 初始化提示词

通用经营分析、同比环比分析、异常波动分析、数据质量检查、指标口径说明和每日经营分析报告。

## 飞书长连接配置与手工验收

1. 飞书开放平台中开启机器人能力，在“事件与回调”选择“使用长连接接收事件”，订阅“接收消息 v2.0（`im.message.receive_v1`）”。
2. 至少授权接收单聊消息、接收群内 @ 机器人消息，以及以应用身份发送消息；保存权限后创建并发布新版本，等待企业管理员审批生效。
3. 将机器人加入目标群并确认机器人有发言权限。管理页的群聊字段必须填写 `oc_` 开头的真实 `chat_id`，不能填写群名称、App ID 或机器人 ID。
4. 连接模式选择“长连接”、开启配置；开启“响应私聊”后私聊不受群白名单限制。群白名单留空表示响应机器人所在的所有群，填写后只响应列表内群聊。群名称不能作为白名单，必须填写事件中 `oc_` 开头的 `chat_id`。白名单和问答开关会在下一条消息处理时读取数据库最新值，不需要重启服务。
5. 重启统一服务。飞书应用列表应显示长连接监听为 `started`；`failed / lark_oapi_not_installed` 表示需要按 `apps/fund_split_adjust/requirements.txt` 安装依赖。
6. 点击“端到端测试”。系统会向首个报告群（没有则使用白名单首个群）发送测试消息；这一步同时验证凭证、发消息权限、机器人入群和群 ID。
7. 在私聊发送“你好”，再在白名单群中 `@机器人 你好`。到“AI 会话与审计 > 飞书收发”查看事件状态；没有消息事件通常说明飞书事件订阅、权限、应用发布或长连接未生效。

长连接无需填写 Webhook 地址、Verification Token 或 Encrypt Key；这些字段只供 Webhook 模式使用。

## 测试命令

```powershell
$env:PYTHONPATH='D:\fsan10\mock_coffice\apps\fund_split_adjust\.vendor'
& '<python-path>' -m unittest discover -s apps -p 'test_*.py'
$env:RUN_DB_TESTS='1'
& '<python-path>' -m unittest apps.ai_analysis.tests.test_integration apps.identity_access.tests.test_integration apps.identity_access.tests.test_http_security
```

正式环境迁移前应备份 AI/IAM 配置，部署新代码，在维护窗口按 374 至 378 顺序执行 SQL，再复核只读账号、DeepSeek 和飞书。当前仅迁移测试库 `mock_coffice`。
