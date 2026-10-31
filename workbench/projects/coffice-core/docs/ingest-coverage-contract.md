# 文件补缺、范围采信与重试契约

逐日核对和人工范围替换适用：抖音资金/结算、京东资金/结算、视频号结算，共3个平台5种报表。网页、自动化和终端API使用同一套后端校验和来源选择。

`GET /api/ingest/report-types` 提供各报表的 `coverage_modes` 和 `coverage_note`。网页按本次勾选报表限制选项，未接入范围替换的报表在上传前说明，不能把跳过逐日比较表述为已完成逐日核对。

## 1. 不变的业务约束

- ODS 原始行和批次保留，文件 SHA256 相同则复用已有完整成功批次。
- 平台、报表、标准 `shop_code` 和 DIM 必须匹配，不使用文件名代替店铺归属。
- 范围来自实际查询参数、绑定文件的可信回执或已登录人工的完整导出确认；首末交易日期只描述文件内容。
- 不改变收入、费用、退款、经营归属及分类公式。资金和结算分开选择；同额、同订单不等于同一笔业务。
- 指标自动刷新仅替换受影响的平台、店铺和业务月份，不自动回退全量。

## 2. 三种处理方式

| import_mode | 意图 | 已有日期 | 缺失日期 | 内容差异 |
|---|---|---|---|---|
| `fill_gaps` | 默认补缺 | 保留既有采信来源 | 纳入新文件 | 阻断，展示差异供人工核对 |
| `replace_range` | 指定范围以本次文件为准 | 采用确认的新来源 | 纳入新文件 | 需预检、完整范围、确认令牌及原因 |
| `refresh_only` | 复用已有来源重新加工 | 保留已有来源 | 仍遵守来源校验 | 不作为绕过冲突校验的入口 |

`replace_range` 仅允许已登录的人工用户，包括网页和终端 API。自动化不能自行替换内容有差异的来源。

### 重复与冲突的判定

1. **投递重试**：相同会话、相同 `client_file_id`，内容、店铺、报表和覆盖声明必须相同；改变请求返回 409。
2. **文件重复**：SHA256、平台、标准店铺、全部目标表和成功批次一致。复用批次，不重复写 ODS。
3. **业务内容一致**：逐日比较所有标准化源业务字段的多重集合，不依赖源文件名、行号或导入时间；保留重复行的数量。
4. **冲突**：同店铺、同报表、同业务日的字段值或重复行数量不同。行数相同、金额相同仍可能冲突。
5. 京东已有的单据编号版本选择及七字段钱包事件键继续保留，且按标准店铺隔离。
6. 视频号结算按标准店铺和平台“流水单号”识别同一流水。单文件流水身份缺失或重复时停止；跨导出重复且全部业务字段一致时仅计算一次；内容不同的旧新版本必须经人工范围确认。结算与经营收支均引用同一有效来源，原有金额、日期和分类公式不变。

### 来源优先级

已明确采信的逐日决定优先；同一日的新人工范围替换决定须重新预检。默认补缺和自动化均保留既有采信来源。没有逐日决定的历史日期继续使用既有来源规则，未知重叠仍停止计算。

不以“API 比人工可信”“整月一定优于每日”或“最后上传时间”直接决定业务真实性。人工明确选择旧的相同文件，也能产生新的采信版本，无需复制 ODS。

### 空日和账户

- 没有交易的日期可以合法为空，不要求区间内每天都有明细。
- 新文件没有交易、旧来源有交易时，补缺模式保留旧来源。
- 替换模式必须在 `confirmed_empty_days` 中逐日明确确认，才允许把旧来源替换为零交易。
- 已确认的零交易日不是“缺失日”，之后自动化收到非零记录时会产生冲突。
- 抖音新文件遗漏旧来源中的账户时拒绝非空范围替换，避免用单账户文件覆盖其他账户。
- 同一会话内同店铺同报表的日期交叉拒绝提交；需拆开处理或先取得一份完整导出，不能猜测为分片。

## 3. 网页流程

1. 选择文件并核对平台、公司、店铺、报表。对于缺少 `账单日期` 的京东文件，在该文件行明确填写业务日。
2. 默认选择“补入缺失日期”；需要财务版本替换时选择“替换所选范围的来源”。
3. 如填写范围，使用平台真实查询的开始、结束日期，并确认是完整导出。
4. 点击提交后自动逐日核对。普通补缺无冲突时直接提交入库，不再弹出重复配置；存在差异或选择范围替换时展开核对窗口。
5. 核对窗口默认展示已有设置和比较结果，“调整导入设置”可展开修改，修改后自动重新核对。替换时才显示原因；旧来源有交易而本次为空时，按具体店铺、报表、日期逐项确认零交易，不能把“系统尚未导入”当作“平台零交易”。
6. 点击“确认导入并刷新”（已入库文件为“确认来源并刷新”）。入库、来源确认与关联 ETL 分阶段展示；入库完成不等于指标刷新成功。

“保存草稿，稍后继续”会保存尚未通过核对的表单输入，但不提交入库、不切换来源、不创建ETL。人工草稿不因10分钟未更新而失效；读取列表不会修改会话状态。数据上传中的已暂存文件、导入记录列表及详情均提供“继续确认”。

旧版本已超时失败、文件仍完整暂存且未入库的人工记录，可在继续确认时恢复同一草稿；服务端重新核验文件摘要，清除过期预检，随后重新核对。已有采信结果或关联ETL的记录不从该入口恢复，避免重复提交。

对于已经成功入库的文件：在“导入记录 → 查看详情 → 使用这些文件重新核对”创建新草稿。该操作引用原文件和原批次，不需要重新下载或重新上传；原会话和失败记录保留。删除这个复用草稿不会删除原文件。

没有新文件、只想重新计算时，直接使用导入记录列表或详情中的“重新计算”，也可从上传页的“重新计算已入库文件”进入。该入口预选 `refresh_only`，复用已入库文件，仅计算原记录对应的店铺和月份，保留来源比较保护；不能以“重新计算”绕过来源冲突。

数据上传页恢复浏览器暂存后立即按原 `run_id`/`file_task_id` 读取服务器状态；后台处理中的记录继续轮询，网络异常按退避间隔重连。重新联网、聚焦窗口、切回页面及打开导入详情均会同步。状态未同步时显示“状态待同步”，不把网络异常标成ODS失败；忽略过期响应和其它会话的状态，成功或重复文件沿用自动移除流程。

### 草稿保存与继续确认接口

- `POST /api/ingest/runs/{run_id}/draft`：保存 `import_mode`、统一 `coverage` 或逐文件 `items` 声明。允许未填完的草稿；旧预检失效，完整提交仍执行严格校验。
- `POST /api/ingest/runs/{run_id}/resume`：只恢复可继续的人工未入库记录，不执行 Loader 或 ETL。恢复动作写入审计日志，原超时日志保留。
- `GET /api/ingest/file-tasks/{file_task_id}/review-context`：给旧浏览器暂存项找回原会话，无需重新上传。
- 列表和详情统一提供 `can_complete`、`can_resume`、`can_reuse`。前端依据这些能力提供对应操作，不向失败会话直接发预检。

自动化未完成会话的超时收尾移到 Worker 定期维护执行，人工草稿不参与该超时规则。新页面通过 `ingest_review_version=3` 检查后台兼容性，旧后台下提示重启，不会先上传后卡在新接口。

### 历史视频号重叠来源修复

旧版已成功写入ODS但跳过逐日核对的会话，在使用最新来源重试时，可按原补缺方式恢复未裁决日期；仅在所有重叠日期业务内容完全一致时恢复，差异则停止并要求人工核对。SQL NULL 与 JSON null 都按“尚未采信”识别，原始文件与ODS须逐字段、多重集合一致。失败批次复用时不会把尚未采信的自身版本误当成既有基准；显式已裁决日期始终保留其决定。

受限维护入口：

```powershell
# 默认只保存原文件核对及修复前摘要，不修改数据库。
& .\.venv\Scripts\python.exe -m etl.platform_finance.repair_wechat_settlement --ingest-run <原导入会话UUID> --output <核对结果JSON>
# 复用原失败运行创建关联重试，限定原店铺/月份，等待现有Worker执行，并核对日/月ADS。
& .\.venv\Scripts\python.exe -m etl.platform_finance.repair_wechat_settlement --apply --ingest-run <原导入会话UUID> --output <修复结果JSON>
```

该入口只接受一份完整成功入库、已声明完整查询范围的视频号结算文件；不重导ODS，不回退全量。输出原始ODS及范围外结算记录摘要、文件全字段核对、5条抽样、真实关联运行ID和逐日/月度金额核对结果。运行时只从指定 `.env` 加载本进程 PG 配置，不持久化 Windows 环境变量。

## 4. 共用 HTTP 接口

### 创建会话

`POST /api/ingest/runs`

```json
{
  "source": "manual",
  "idempotency_key": "unique-request-id",
  "expected_file_count": 1,
  "auto_refresh": true,
  "import_mode": "fill_gaps"
}
```

网页和终端人工使用 `manual`，通过用户登录 Cookie、CSRF 和上传权限校验。自动化使用 `api`；历史 `robot` 兼容。

### 逐文件上传

`POST /api/ingest/runs/{run_id}/files`，使用 multipart：

- `file`：原始 CSV/XLS/XLSX/XLSM 文件。
- `client_file_id`：稳定的逐文件幂等键。
- `report_type`：例如 `douyin_settlement`。
- `shop_code`：DIM 中的标准店铺编码。
- `coverage`：JSON 字符串，可选；范围替换和零行文件必须提供完整范围。

```json
{
  "start": "2026-10-01",
  "end": "2026-10-18",
  "complete_export": true,
  "reason": "财务核对后采用本次完整导出",
  "confirmed_empty_days": []
}
```

京东缺少账单日期的单日文件另传 `coverage.bill_date`。不能通过文件名或文件时间推测业务日。不同文件需要不同日期时应分别声明。

自动化 API 使用 `Authorization: Bearer ...`，逐文件还必须带 `Idempotency-Key`，并与 `client_file_id` 一致。凭据从进程 Secret 或未提交的 `.env` 读取，不放进命令参数。

总控脚本的定时执行须使用 `--trigger-type schedule`；默认 `--trigger-type manual` 的终端人工执行使用用户登录凭据，记录为人工。自动化控制台和报表日历仍属于自动化场景。总控用 Profile 元数据或显式回执身份唯一匹配 DIM，然后显式传标准编码，不用文件名猜店铺。

如果传 `artifact_id`，服务端验证回执真实存在、已验证、SHA256、平台、店铺、实际请求范围和归档范围一致。自动化中心内部提交也走这一逻辑。

### 预检

`POST /api/ingest/runs/{run_id}/coverage-preflight`

可以在请求中修改 `import_mode`、统一 `coverage`，或者通过 `items: [{file_task_id, coverage}]` 分别声明。仅允许待提交草稿。

响应包括：`blocked`、`token`、`summary`、逐文件逐日 `items`。`blocked=true` 时不会写 ODS 或切换来源。预检不写原始事实，仅保存草稿声明和比对结果。

### 确认提交

`POST /api/ingest/runs/{run_id}/complete`

```json
{"preflight_token": "token-returned-by-the-last-preflight"}
```

范围替换必须提交对应令牌。确认时重新解析文件、验证摘要并比较当前来源；Loader 完成后，在来源采信激活前再次验证文件与 ODS 全业务字段及行数。相关日期的采信版本或内容改变则停止，要求重新预检。其他店铺无关变更不使确认失效。

### 复用已经入库的文件

`POST /api/ingest/runs/{run_id}/reuse`

```json
{"idempotency_key": "unique-review-request"}
```

返回一个新人工草稿及文件引用；后续仍需预检和确认。

### 结果与重试

- `GET /api/ingest/runs/{run_id}`：文件状态、原批次、采信结果 `coverage_result` 和关联 ETL。
- `GET /api/etl/runs/{etl_run_id}`：节点结果、冻结范围和 `parent_etl_run_id`。
- `POST /api/etl/tasks/{task_id}/retry`：默认请求 `{"snapshot_policy":"latest"}`。

默认重试创建新的关联运行，保持原平台/店铺/月份，冻结当前成功来源与采信版本，并重新排队原运行的相关上下游。不会只重置失败节点，也不会改写旧失败记录。重复点击会复用正在排队/执行的关联重试。

仅相同快照方式的排队/执行运行可以复用；已有 `replay` 时不能把它作为 `latest` 返回，反向也同样拒绝混用。

`snapshot_policy=replay` 是显式使用原快照的高级入口，不会把后来补入的资金带进来。它会写回原范围当前指标，不是只读诊断；必须同时提交 `confirm_replay_publish: true`。CLI 对应 `--snapshot-policy replay --confirm-replay-publish`，缺少确认时在登录前拒绝。页面只提供“使用最新数据重跑”；普通补数据后重试应使用默认 `latest`。原运行若为全量或缺少明确范围，默认重试拒绝自动扩大范围，需明确创建人工刷新。

详情页显示原店铺数量、业务月份和冻结上限，明确“不会扩展到新月份”。`snapshot_diagnostics` 按该运行相关报表、店铺、月份检查新来源；京东资金包括次月首日的跨日依赖。新增批次、冻结时未完成而后来成功的旧批次、只增加采信版本的变化分别识别。全库最大批次仅作参考，不直接判定当前运行过时。执行前观察，失败时再观察；结果保存在节点 `result_metrics.source_snapshot`，不改变计算输入或自动扩大发布范围。

京东对账从同一批次/采信快照中的资金来源读取钱包，沿用原有七字段事件键及收支符号公式，避免次月到账依赖未发布的次月 DWD，也避免旧快照读取后来发布的钱包数据。只核对依赖，不发布次月指标。

资金交易日期首末值分别记录为观察边界；`fund_coverage` 只记录当前冻结版本中已采信、声明完整导出的业务日及连续区间，包含有效确认的零交易日。补缺时新文件为空而保留旧明细的日期不作为完整性证明。历史日期缺少钱包时，区分已覆盖但缺失、范围未覆盖、完整覆盖未知；三者都停止刷新，不通过改状态放行。尚未到预计到账日或预计当日记为预计待到账。新快照保存 `as_of_date`，复现保留该检查日期。

对账输出 `settlement_group_count`、`source_batch_count` 和 `settlement_batches`（来源批次及日期范围）。旧 `settlement_batch_count` 保留为已弃用的单据组数别名，不能按物理批次解释。

## 5. 终端人工调用

使用同一 HTTP 接口，不提供绕过校验的直接写库分支。用户名、密码可从根目录未提交 `.env` 的 `INGEST_USERNAME`、`INGEST_PASSWORD` 读取；未配置时在终端交互输入，密码不回显。`INGEST_BASE_URL` 可选，默认本机 8770。均只加载到该 CLI 进程。

manifest 示例（路径相对 manifest 所在目录）：

```json
[
  {
    "path": "exports/douyin-settlement.csv",
    "report_type": "douyin_settlement",
    "shop_code": "<standard-shop-code>",
    "coverage": {
      "start": "2026-10-01",
      "end": "2026-10-18",
      "complete_export": true,
      "reason": "财务核对后的完整导出"
    }
  }
]
```

```powershell
.\.venv\Scripts\python.exe -m apps.file_ingest.cli --env-file .env upload --manifest manifest.json --idempotency-key unique-upload-request --mode replace_range
.\.venv\Scripts\python.exe -m apps.file_ingest.cli --env-file .env complete --run-id <returned-run-id> --preflight-token <returned-token>
.\.venv\Scripts\python.exe -m apps.file_ingest.cli --env-file .env status --run-id <returned-run-id>
```

第一条只上传并预检，不切换来源。先检查逐日结果，再执行确认。仅补缺时可使用 `--submit` 在无冲突时直接提交；范围替换禁止这样跳过预览。

已上传文件可用 `reuse --run-id ... --idempotency-key ...`。`preflight --run-id ... --declarations declarations.json` 可提供统一或逐文件声明，不必再次传输文件。

退出码：0 请求/预检成功；2 参数或网络错误；3 预检冲突；4 登录/权限错误；5 查询到导入会话失败。0 不代表异步指标已经完成，须查看关联 ETL 的终态。

## 6. 迁移、验收和运行边界

迁移使用显式顺序 `468 → 436 → 460 → 469`：先建立采信记录，再更新有效来源视图，最后增加会话和重试字段。不会修改 ODS 行，也不自动登记本次事故文件的覆盖范围。

```powershell
.\.venv\Scripts\python.exe -m apps.file_ingest.migrate_coverage --apply
.\.venv\Scripts\python.exe -m apps.file_ingest.migrate_coverage
```

迁移不执行经营配置种子或指标刷新；遇到运行中的 ETL 拒绝，锁等待超过 3 秒回滚。现有后端和 Worker 需要重启才能加载 Python 改动；网页和 CLI 会检查 `ingest_coverage_version=1`。

来源选择和刷新排队在同一事务完成。ETL 仍按既有节点分别提交，各节点失败回滚其自身；因此应分别查看采信、入库和加工状态，不能声称整条链路是一个跨节点事务。

对其他平台的原有上传继续兼容，本次不开放其 `replace_range`。相同会话内的重叠文件、未明确的分片、多账户部分导出不能通过猜测消解。

## 7. 2026-10-21 维护入口及旧客户端兼容

- 所有上传必须显式传 `shop_code`；未传的旧客户端返回 HTTP 400。顶层数字 `code` 保持不变，`data.details.error_code` 为 `SHOP_CODE_REQUIRED`，终端 CLI 也输出该业务错误码。请升级调用端，禁止恢复文件名或默认店铺兜底。
- `etl.common.settlement_sources --manifest` 不再接受人工 `user_confirmed` 写入。新增登记仅接受 `evidence_type=automation_receipt` 和真实 `evidence.artifact_id`，写入函数内部复核文件摘要、完整导入、标准店铺、回执绑定批次及实际请求范围；手工分片组不能通过该入口授权。
- 现有历史人工登记继续生效，相同已登记内容可幂等核验，不批量补写逐日记录、不删除历史。不能因为快手、天猫、小红书尚未接入新逐日表，就使其正常历史来源失效。
- `etl.platform_finance.reconcile_settlement --apply` 只刷新和核对已批准来源，不再新增人工覆盖登记；抖音已在新流程逐日采信的参考文件可按全部业务字段多重集核验，兼容保留一致旧日报的情况。
- 人工范围采信使用网页或 `apps.file_ingest.cli`。其他平台尚未开放的新人工范围替换会明确拒绝，需先扩展同等保护，不能继续通过维护脚本绕过确认。普通已无冲突的文件上传和可信自动化回执登记继续可用。

本轮加固不需要新增建表或业务数据迁移。请重新启动后端及独立 Worker，使新的维护入口限制、诊断和校验生效；不需要重新上传已经成功的业务文件。
