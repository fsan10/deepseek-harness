# 数据导入中心与 API 上传

自动化控制台与 Codex 定时脚本的新导入会话使用 `source: "api"`，导入记录显示“API”。兼容保留 `robot`（历史影刀）和 `manual`（网页）来源。`api` 和 `robot` 均须使用 `INGEST_ROBOT_TOKEN` 进行 Bearer 认证，文件上传携带 `Idempotency-Key`，其他上传与批次完成契约相同。

## Automation Workbench 控制面

网页入口为 `/automation/`。控制面只允许 `apps.automation_center.registry` 中的白名单任务，
不接受 shell、Python module、脚本路径或数据库命令。长任务由独立 AutomationWorker 从
PostgreSQL `ops.automation_run` 领取，HTTP 请求只创建任务并立即返回。

- `GET /api/automation/workbench?date=YYYY-MM-DD`：当日计划、完成、执行中、等待人工、失败及平台/店铺步骤。
- `GET /api/automation/jobs`、`GET /api/automation/jobs/{id}`：任务和解析后的白名单步骤。
- `POST /api/automation/jobs/{id}/run`：立即入队，返回 Automation Run ID。
- `PUT /api/automation/jobs/{id}`：只允许启停、`manual/daily`、固定 `HH:MM`、时区、重试次数、超时和说明。
- `GET /api/automation/runs`、`GET /api/automation/runs/{id}`：运行列表与下载、Artifact、FileIngest、ODS、ETL timeline。
  查询参数：`page`、`page_size`（1–100）、`date_field`（`business_date` 默认 / `started_at` / `completed_at`）、
  `date_from`、`date_to`、`status`、`job_id`、`trigger_type`、`platform`（精确匹配步骤平台）、`shop`（模糊匹配步骤店铺）。
  `page`/`page_size` 非法（如 `NaN`）返回 400 中文提示；`date_from`/`date_to` 必须是 `YYYY-MM-DD`；
  `started_at`/`completed_at` 按 `Asia/Shanghai` 取日期比较。
- `POST /api/automation/runs/{id}/retry`、`POST /api/automation/runs/{id}/cancel`：安全重试或请求取消。
- `GET /api/automation/daily-results?date=YYYY-MM-DD`：按执行日期查看成果，每个步骤单独保留业务日期范围。
- `GET /api/automation/health`：AutomationWorker、FileIngest Worker、Cloak Login 可达性和数据库状态。
- `GET /api/automation/report-targets?refresh=1`：从共用下载配置和 Cloak Profile 清单解析店铺报表，并核验 DIM；未映射店铺禁止补跑。
- `GET /api/automation/report-day?date=YYYY-MM-DD`、`GET /api/automation/report-calendar?month=YYYY-MM`：返回店铺报表的下载、导入状态；支持 `date_basis=business|execution`，API 默认 `business` 保持兼容，页面默认 `execution` 查看当天实际任务，并每5秒自动同步。业务日期按报表期间判断覆盖，执行日期按上海时区的步骤开始时间判断，与文件导入台账的写入时间无关。支持 `company`、`platform`、`shop`、`profiles`、`report_types` 筛选，后两者用逗号分隔。
- `POST /api/automation/report-batches/preview`：传入 `profiles`、可选 `report_types`，以及 `dates` 数组 / `month` / `start_date` 与 `end_date`，预览历史补跑计划；支持同样的 `date_basis`。按执行日期补跑时，转换为该任务实际请求的业务期间后生成计划，防止把执行当天错传给昨日账单。`force` 默认为 false，仅跳过具有已确认期间且文件仍存在的成果。
- `POST /api/automation/report-batches`：同预览参数并增加 UUID `request_key`，返回 202 和补跑批次。服务重新核验清单，通过白名单生成并冻结计划；任务只下载归档。
- `GET /api/automation/report-batches/{id}`：批次进度、各 Profile 当前运行及重试历史。失败或待人工的运行沿用现有 `/runs/{id}/resume` 入口。

日历读取要求 `automation.results.view`，预览和创建补跑要求 `automation.runs.execute`。补跑沿用现有 Worker 队列、检查点和资源锁；外部 Codex/CLI 在下载开始、归档完成、上传提交、结束时同步同一执行台账，数据库暂不可用时保留日志供读取或后续执行补同步，不由 Worker 再次领取。导入状态直接读取 FileIngest，遗留断链通过 SHA256、文件大小、原文件名及 DIM 平台/公司/店铺身份核验后恢复关联，不重复导入。月汇总不会标记业务日期下的日报已齐；执行日期下显示该月报下载任务的实际完成结果。缺口按当前店铺清单计算。

状态包括 `queued/running/success/success_with_warnings/no_data/needs_human/failed/cancelled/skipped`。
`no_data` 是成功终态；子下载脚本退出码 `2` 映射为 `needs_human`，退出码 `130` 映射为 `cancelled`。
Artifact 只保存相对于归档根目录的路径、大小和 SHA256，不把二进制写入 PostgreSQL。

独立运行（命令会从项目根目录 `.env` 加载数据库配置）：

```powershell
.venv\Scripts\python.exe -m apps.automation_center.worker
.venv\Scripts\python.exe -m apps.automation_center.scheduler
```

原 `/api/automation/verification/*` 仍由验证码/人工接管模块处理，路由、Bearer Token 与返回契约不变。

数据导入中心与银行资金、达播运营共用 `apps.fund_split_adjust.server`，默认地址为 `http://127.0.0.1:8770`，网页入口为 `/ingest/`。数据库连接只从服务启动参数或 `PG*` 环境变量读取。

## 通用规则

- JSON 响应统一为 `{"code":0,"data":...,"message":"success"}`。
- 网页请求通过内网反向代理身份，操作人放入 `X-Operator`。
- 影刀请求额外携带 `Authorization: Bearer <INGEST_ROBOT_TOKEN>`。
- 自动化验证码转发请求使用 `Authorization: Bearer <AUTOMATION_ROBOT_TOKEN>`；未单独配置时可兼容 `INGEST_ROBOT_TOKEN`。
- 影刀创建会话必须携带 `Idempotency-Key`；网页也会生成幂等键。
- 不接收、不返回、不保存 `original_filename`。
- 文件上传后立即落盘和校验，Loader 与 ETL 由 Web 默认内置启动的后台 Worker 异步执行。

## 基础数据

- `GET /api/ingest/report-types`：28 类启用报表、Loader、ODS、扩展名、Sheet/表头及 ETL。
- `GET /api/ingest/shops?platform_code=tmall`：当前有效 DIM 店铺。
- `GET /api/ingest/guess?filename=...`：严格识别四段式或末尾三位流水号文件名。
- `GET /api/health`：统一返回银行、达播、导入、Worker 和 DataEase 嵌入代理状态。
- `GET /api/ingest/health`：兼容旧调用，响应头包含 `Deprecation: true`，新调用必须迁移到 `/api/health`。

## 采集会话

### 创建

`POST /api/ingest/runs`

```json
{
  "source": "robot",
  "expected_file_count": 2,
  "auto_refresh": true
}
```

请求头：

```text
Authorization: Bearer <token>
Idempotency-Key: xiaodao-20260804-tmall-001
X-Operator: 影刀-电商日报
```

### 上传文件

`POST /api/ingest/runs/{run_id}/files`，请求体为 `multipart/form-data`：

影刀上传的 `Idempotency-Key` 请求头必须与 `client_file_id` 一致；网页请求使用表单中的 `client_file_id` 完成同等幂等控制。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | 文件二进制，单次一个文件 |
| `client_file_id` | 是 | 会话内唯一 ID，重试保持不变 |
| `platform_name` | 参数模式必填 | 标准平台中文名 |
| `company_name` | 参数模式必填 | 与 DIM 严格一致 |
| `shop_code` | 参数模式必填 | 标准店铺编码 |
| `shop_name` | 参数模式必填 | 与 DIM 严格一致 |
| `report_name` | 参数模式必填 | 唯一标准报表名称 |
| `report_type` | 可选 | 内部编码；若传入则与中文参数交叉校验 |

参数优先；没有报表与店铺参数时才用文件名识别补齐。接口不允许传 Loader 路径、数据库密码、任意命令参数或绕过必填字段校验。

### 完成与查询

- `POST /api/ingest/runs/{run_id}/complete`：文件数与预期一致后进入 Worker 队列。
- `GET /api/ingest/runs/{run_id}`：会话、文件、批次和关联 ETL。
- `GET /api/ingest/runs?limit=50`：最近会话。
- `POST /api/ingest/file-tasks/{id}/retry`：失败文件人工重试，然后再次 complete。

## ETL

- `POST /api/etl/runs`：`{"scope":"all"}` 或 `{"scope":"selected","etls":["tmall_main_business_finance"]}`。
- `GET /api/etl/runs/{etl_run_id}`：运行及节点状态、退出码、输出/错误摘要。
- `GET /api/etl/runs?limit=50`：最近运行。
- `POST /api/etl/tasks/{task_id}/retry`：失败或跳过节点重试。

通常无需单独启动 Worker。如需把 Web 与 Worker 分开部署，Web 使用 `--no-ingest-worker`，再启动：

```powershell
.venv\Scripts\python.exe -m apps.file_ingest.worker
```

ETL 定时配置统一使用 Automation Workbench 的 `full_etl` Job；FileIngest 不再提供独立夜间 ETL 开关或调度 API。需要执行日计划时运行 AutomationScheduler：

```powershell
.venv\Scripts\python.exe -m apps.automation_center.scheduler
```

旧 `ops.etl_nightly_schedule` 会在迁移 `431_retire_legacy_etl_nightly_schedule_postgres.sql` 中停用；旧 `/api/etl/nightly-schedule` 路由不再提供。历史 `nightly` ETL 记录仍保留供查询。

## 费用映射

列表中的已有配置直接来自 `dim.dim_platform_fee_mapping`；未映射候选从各平台 ODS 按稳定业务类型或费用项去重生成。订单号、交易备注、自由文本描述和 DWD 明细行不会各自生成费用场景。

- `GET /api/ingest/fee-mappings`：支持 `platform_code`、`source_document_type`、`mapping_status`、`included`、`keyword`、`page`、`page_size`。
- `GET /api/ingest/fee-categories`：现有一级分类去重列表。
- `POST /api/ingest/fee-mappings/assign`：单条或批量分配，也可直接使用新分类编码/名称。
- `PUT /api/ingest/fee-mappings/{mapping_id}/status`：停用或重新启用，携带 `updated_at` 做并发检查。
- `GET /api/ingest/operation-logs`：上传、重试、会话和映射审计。

网页还支持修改描述匹配方式、匹配值、优先级，并将当前筛选结果导出为 UTF-8 CSV。

映射保存事务成功后只创建 ETL 任务，不在 HTTP 请求中执行长刷新。

## 影刀统一改名

```powershell
python -m apps.file_ingest.rename_file `
  --file "D:\robot\download.csv" `
  --platform-name "天猫" `
  --company-name "墨客咖时（南京）生物科技有限公司" `
  --shop-name "MOCK旗舰店" `
  --report-name "结算支出"
```

同组多文件增加 `--sequence 1`。成功输出仅包含 `success/path/filename/renamed`，不会输出改名前文件名。

## 自动化验证码转发

验证码机器人配置在 `/ai-admin/#verificationRelays` 中维护，与每日报告机器人配置分开：
可选择飞书应用、群聊 `chat_id`、负责人 `open_id`、适用平台和等待时长。验证码答案只在数据库
中短期 AES-GCM 加密保存，接口和审计日志不返回或记录明文。

- `POST /api/automation/verification/challenges`：自动化脚本创建有类型的 Challenge。请求体包含
  `challenge_type`（`verification_code` 或 `archive_password`）、`platform`、`company`、`shop`、
  `purpose` 和可选 `page_url`，返回 `challenge_id` 与等待秒数。短信自动接收启用时，先等自动消息，
  2 分钟未收到或平台判错后发送带负责人 @ 的人工提醒；未启用时立即提醒。未传 `challenge_type` 时兼容旧调用方，默认为 `verification_code`。
  `force_human=true` 用于已发送密码但自动请求失效的恢复；`defer_human_notice=true` 仅用于下载前的密码预登记，
  无自动通道时延后人工提醒，确认需要解压后调用 `resume` 立即提醒，或到 2 分钟自动兜底。
- `POST /api/automation/verification/notices`：自动化脚本发送不需要回复的人工接手提醒。请求体包含
  `platform`、`company`、`shop` 和 `purpose`，服务向匹配平台的启用群聊发送带负责人 @ 的飞书消息，
  不创建或保存验证码 Challenge。
- `GET /api/automation/verification/challenges/{challenge_id}`：自动化脚本轮询状态；状态为
  `answered` 时只在 HTTPS/本机受保护的 Bearer 请求中返回短期答案，`pending`、`expired`、
  `cancelled` 不返回答案。
- `POST /api/automation/verification/challenges/{challenge_id}/resume`：显式恢复待答请求并重新发送人工提醒，
  保留原截止时间；已答请求保持答案，过期请求返回 `expired`，调用方改建 `force_human=true` 的新请求。
- `POST /api/automation/verification/challenges/{challenge_id}/cancel`：撤销尚未真正触发下载的密码预登记，清除答案密文并释放短信等待流。
- `POST /api/automation/verification/challenges/{challenge_id}/reject`：平台判错后在原截止时间内转人工，错误消息不可再次分配。
- 飞书事件收到群聊文本后，服务优先匹配同群未过期挑战并按类型解析：`verification_code` 接受验证码格式，
  `archive_password` 接受“解压密码：...”“文件提取码：...”或不含中文空格的原始密码。答案加密保存，随后按类型回复
  “验证码已收到，自动化任务将继续。”、“解压密码已收到，自动化任务将继续。”或“文件提取码已收到，自动化任务将继续。”，
  自动短信、事件和群历史接收共用回执，重复消息不重复确认；发送失败会重试且不丢失已保存答案。
  不要求负责人再次 @ 机器人；普通聊天文本不会误完成 Challenge。
- 重试 Challenge 的 `purpose` 可包含“验证码错误”或“解压密码错误”；机器人会先明确提示上一次输入错误，
  再要求负责人重新回复，避免无原因地重复发送请求。

服务端必须设置 `AUTOMATION_ROBOT_TOKEN`（推荐）或兼容的 `INGEST_ROBOT_TOKEN`；令牌不写入日志。
