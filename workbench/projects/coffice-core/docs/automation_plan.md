# 数据导入自动化实施说明

## Automation Workbench 增量编排

`apps/automation_center/` 在既有下载总控和 FileIngest/ETL 之上提供控制面：

`Automation Job/Run -> DownloadController -> Artifact -> FileIngest -> ETL -> ADS`

AutomationWorker 复用 `all_platform_downloads.json`、lane、checkpoint、controller lock、profile 生命周期和
现有下载脚本；只通过可选 event sink 记录实时步骤和归档目录差异。它不复制 Loader、ODS 导入、ETL
任务规划、advisory lock、`SKIP LOCKED` 或 stale recovery。旧 `/ingest/` 和
`/api/automation/verification/*` 保持兼容。ETL 定时任务统一由 Automation Job 配置及 AutomationScheduler
负责；FileIngest 不再保留独立夜间调度器。

## 已实现范围

- 28 类电商报表集中注册于 `apps/file_ingest/registry.py`。
- `etl/tmall/load_tmall_fund_ods.py` 保留为 legacy，只在 `DEPRECATED_LOADERS` 中登记，不进入 API、网页或夜间导入。
- 每条启用配置包含稳定 `report_type`、唯一的平台内中文 `report_name`、平台、Loader、ODS、允许扩展名、默认 Sheet、表头行、数据起始行和下游 ETL。
- `xhs_fund` 正常导入 ODS，但无下游 ETL。
- 统一命名与识别、影刀命令行改名、网页表单参数与文件名识别两种模式。
- PostgreSQL 持久化采集会话、文件任务、ETL 运行/节点、操作日志和刷新水位。
- 文件状态分为两层：服务器落盘后为 `uploaded`（只代表已进入待处理队列）；Loader 返回批次号并成功写入 `ods.ods_file_ingest_log` 后才为 `success`（ODS导入成功）。每个文件的导入记录详情展示状态、批次/目标表、Loader退出码、标准输出摘要、错误摘要和开始/完成时间。
- 同一采集会话的 ETL 失败会附带本次会话的ODS文件清单；各平台的公司归属由当前有效 DIM 店铺映射生成，不再校验源文件主体与历史批次主体或历史公司快照是否一致。源文件主体字段仍保留用于审计展示。
- 独立 Worker 串行处理；全局 PostgreSQL advisory lock 防止多 Worker 同时运行 ETL。
- 银行批次提交锁定与 ETL 入队在同一事务内完成。
- 手动或 Automation Job 全量 ETL 不刷新银行经营指标；平台银行汇总复用最近一次已提交成功的银行 ADS。银行经营指标只在财务提交锁定银行批次时入队，成功后再刷新平台银行汇总。
- 任一标记为平台银行汇总来源的平台ETL刷新时，自动追加平台银行汇总；银行批次提交刷新银行ADS时也自动追加汇总。两侧无需同时刷新，汇总总是读取另一侧最近一次成功快照。
- 费用映射直接维护 `dim.dim_platform_fee_mapping`，候选查询优先读取各平台 ODS 真实值、用平台费用来源明细补齐固定列场景，再左连 DIM；查询不修改 ODS。

## 文件与职责

| 文件 | 职责 |
| --- | --- |
| `apps/file_ingest/registry.py` | 28 类报表、1 个 legacy Loader、ETL 白名单和依赖计划 |
| `apps/file_ingest/naming.py` | Windows 安全命名、四段式/流水号识别 |
| `apps/file_ingest/rename_file.py` | 影刀调用的 JSON 命令行工具 |
| `apps/file_ingest/service.py` | DIM 校验、上传幂等、任务与费用映射事务 |
| `apps/file_ingest/module.py` | 复用现有 HTTP 服务的 API 与静态页面模块 |
| `apps/file_ingest/worker.py` | Loader、受影响 ETL 与依赖阻断 |
| `apps/automation_center/scheduler.py` | Automation Job/已发布 Flow 的定时调度 |
| `sql/common/368_file_ingest_automation_postgres.sql` | `ops` 运维表及 ODS 日志扩展 |
| `apps/file_ingest/static/` | 数据上传、导入记录、ETL、费用映射、操作日志页面 |

## 运行

首次执行现有经营配置中心与数据导入模块迁移：

```powershell
.venv\Scripts\python.exe -m apps.fund_split_adjust.server --migrate --no-serve
```

启动现有经营配置中心：

```powershell
.venv\Scripts\python.exe -m apps.fund_split_adjust.server
```

另开一个后台进程启动 Worker：

```powershell
.venv\Scripts\python.exe -m apps.file_ingest.worker
```

管理员可安装开机启动的 FileIngest Worker；该脚本也会移除旧的 FileIngest 夜间 ETL 计划任务（如存在）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_file_ingest_tasks.ps1 `
  -PythonExe ".venv\Scripts\python.exe"
```

每日 ETL 调度在 Automation Workbench 的 `full_etl` Job 中配置；负责扫描计划的进程为：

```powershell
.venv\Scripts\python.exe -m apps.automation_center.scheduler
```

迁移 `431_retire_legacy_etl_nightly_schedule_postgres.sql` 会关闭旧 `ops.etl_nightly_schedule` 配置；旧 `/api/etl/nightly-schedule` API、Web 内置调度线程、独立 FileIngest 调度进程和 Windows 一次性创建器均已退役。历史 ETL 运行记录保留。

全量 ETL 仍不会越过财务提交关卡重跑银行经营指标。若平台类上游任一任务失败，平台银行汇总会标记为“依赖任务未成功”并跳过，避免把新旧上游结果混合汇总。

网页入口：`http://127.0.0.1:8770/ingest/`。

## 影刀流程

1. 按平台、店铺、报表分组下载全部文件。
2. 单文件调用改名模块且不传 `--sequence`；多文件按稳定顺序传 `1..N`。
3. 创建一个带预期文件数和幂等键的 robot 会话。
4. 逐个上传改名后的文件和标准业务参数。
5. 调用 complete；轮询 run，文件导入成功后再轮询关联 ETL。
6. 失败任务保留错误摘要，可在网页人工重试；重复 SHA256 不再次写 ODS。

## 验收命令

```powershell
python -m unittest discover -s apps/file_ingest/tests -v
node --check apps/file_ingest/static/app.js
```

测试覆盖 28+1 Loader 一一对应、天猫资金路由、Sheet/表头参数、必填字段缺失失败、额外字段按字段名忽略、文件命名、Windows 禁用字符、流水号、名称含下划线和拒绝覆盖。

## 部署注意

- `INGEST_ROBOT_TOKEN` 只放环境变量。
- `INGEST_FILE_ROOT` 指向有备份和容量监控的数据盘；默认 `.uploads/file_ingest` 仅适合单机验证。
- Web 与 Worker 使用同一组 `PG*` 环境变量。
- Worker 可由附带的 Windows 任务安装脚本、NSSM 或其他服务包装器常驻；Web 重启不会丢任务。
- 反向代理应限制 `/api/ingest` 与 `/api/etl` 的内网访问，并注入可信 `X-Operator`。
