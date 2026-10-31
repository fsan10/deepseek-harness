# 每日六平台报表下载

总控下载脚本每完成一份标准报表归档，就通过系统 API 上传。`--trigger-type schedule`（含定时执行）记录为自动化 API；默认 `--trigger-type manual` 的终端人工执行记录为人工上传，使用用户登录权限。系统沿用 FileIngestWorker 导入 ODS，并自动刷新受影响 ETL。自动化控制台和报表日历补跑也使用同一导入服务。流程编排中的 API 上传与 ETL 节点默认启用，按归档 → 上传 → ODS 完成 → ETL 的顺序执行。

总控从项目根目录未提交的 `.env` 加载配置，仅作用于当前进程。`INGEST_API_BASE_URL` 默认 `http://127.0.0.1:8770`，部署到其他地址时在 `.env` 中配置；定时自动化认证沿用 `INGEST_ROBOT_TOKEN`，不要通过命令行传入令牌。API 不可用或上传失败时保留归档并停止，修复后可重跑；上传使用文件路径、SHA256 和声明参数生成幂等键，避免重复提交。后端、FileIngestWorker 需正常运行才能完成入库和刷新。

终端人工执行使用未提交 `.env` 中的 `INGEST_USERNAME`、`INGEST_PASSWORD` 登录；需要交互输入密码或处理整段范围采信时，可使用 `python -m apps.file_ingest.cli`（运行时显式使用项目虚拟环境解释器）。上传会校验 Profile 对应的 DIM 标准店铺、报表类型、文件摘要和覆盖声明；存在内容差异时保留草稿，需在网页核对后确认。[上传与采信契约](../../docs/ingest-coverage-contract.md)说明预检、复用文件和重试流程。

旧调用端必须升级为显式传递标准 `shop_code`；缺少时返回 HTTP 400 和 `data.details.error_code=SHOP_CODE_REQUIRED`，不再从文件名推断店铺。补数据后选择“使用最新数据重跑”，只重跑原店铺和原月份。原快照重放会替换当前指标，终端使用该高级操作时必须显式加 `--confirm-replay-publish`。旧 `settlement_sources --manifest` 不再作为人工覆盖入口。

总控在打开商家页面前检查本次上传身份所需配置。京东日常任务先取资金、再取结算；自动导入时，尚未取得已核验资金覆盖的主营收支任务显示为延后，资金导入后会触发新的刷新。已核验范围内的真实缺失、金额差异仍停止刷新并报错。

京东、快手、抖音订单和天猫推广费在验证码、文件密码或登录验证需要人工处理时返回退出码 `2`（`needs_human`），保留已有导出任务、加密文件和恢复状态；普通程序或报表错误返回 `1`。处理后沿用原命令续跑，成功检查点继续跳过。

淘宝联盟、万相台推广费优先复用同一 Cloak Login Profile 已登录的联盟会话或“快速进入”确认页；需要重新建立会话时，从该 Profile 的千牛商家中心点击“推广→淘宝联盟”，接管同一浏览器上下文打开的标签页，再点击“快速进入”完成平台授权。浏览器自动沿用现有 Cookie，不跨 Profile 复制或导出 Cookie。仅在现有会话不可用且出现真实内嵌密码表单时，回退到 `//*[@id="container"]` 登录，不点击会弹出第二个登录框的“立即登录”。密码回退沿用 `--username`、`--password-env`，默认从项目未提交 `.env` 读取 `TMALL_LOGIN_PASSWORD`；已有会话无需提供密码。遇到人机验证、二次验证或账号授权未完成时保留现场并返回 `needs_human`。

## 按月归档与历史补跑

报表统一保存到 `归档根目录\平台\标准报表名\YYYY.MM\`，月份取报表业务日期。默认根目录为 `C:\Users\win\Desktop\data`，例如八月订单保存到 `抖音\订单\2026.08\`。单文件跨月区间按结束日期月份保存；日历保留其完整业务期间。标准文件名和同名递增规则不变，流程编排使用同一归档入口。

归档公司名和店铺名取自 Profile 备注 `platform=<平台>;company=<公司>;shop=<店铺>`；独立运行下载脚本时取对应 CLI 参数。备注应与 DIM 当前公司店铺名称一致，修改备注只影响后续下载，已有文件需另外改名。动态总控在启动浏览器前检查同一平台、同一店铺的所有启用 Profile：公司名称冲突时停止并提示核对备注，括号全角/半角差异按同一名称比较。

后台入口：**自动化工作台 → 报表日历**。选择月份、公司/平台、店铺对应的 Profile 和报表，点击“查询”应用筛选；可多选日期或选择整月，再点击“补跑所选日期”。预览显示实际执行区间、文件数和已完成跳过项。补跑下载归档后自动提交导入，并刷新受影响 ETL。

- 默认跳过具有已确认业务期间且文件仍存在的成果；勾选“重新获取”后更新预览，可保留旧文件并重新下载。
- 每个 Profile 进入现有后台队列；关闭页面后继续执行。失败或等待验证时，在处理现场后点击“处理后继续”，沿用原运行和检查点。
- 补跑冻结 Profile 标识及业务归属；执行前若店铺身份已改变，会停止并提示重新核对计划。
- 报表完成情况按业务日期展示；执行情况按运行日期展示。月汇总仅表示月报已获取，不能代替日报。未匹配 DIM 的 Profile 禁止补跑。
- 定时下载每天运行，包含周末和法定节假日；手动历史补跑可选择相应业务日期。平台未生成或不开放历史报表时停止并保留缺口，不使用其他日期替代。
- Codex/CLI 通过归档根目录下 `.automation_logs/report_ledger` 记录结果；后台 Worker、Scheduler 和日历查询幂等同步。后台临时不可用时保留事件等待后续同步。
- 上线前的旧文件和未记录的历史运行不能自动推断为已完成；补跑一次或取得可核验的期间记录后，日历才会标记已补齐。

独立部署迁移与核验（从项目根目录运行，自动加载未提交的 `.env`）：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.report_calendar_admin migrate
& ".venv\Scripts\python.exe" -m scripts.auto_download.report_calendar_admin check
```

升级后重启原有后台、AutomationWorker 和 AutomationScheduler。现有 Codex 定时命令无需修改。

旧文件整理工具默认预览，`--apply` 执行整理并同步已有归档引用：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.archive_months
& ".venv\Scripts\python.exe" -m scripts.auto_download.archive_months --apply
```

工具对文件计算 SHA256、避免覆盖同名文件、写入迁移清单；发生错误时恢复文件路径。无法识别日期的文件保留原位。文件内容、ODS 和导入批次不变。

修正已有归档中的公司错字时，可指定原公司名及 DIM 当前的平台、公司、店铺（默认预览，加 `--apply` 执行）：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.archive_company_names --platform "抖音" --old-company "<原公司名>" --company "<DIM当前公司名>" --shop "<DIM当前店铺名>"
```

工具自动从项目 `.env` 加载当前进程的数据库连接设置，校验目标 DIM 唯一映射；只改指定店铺的文件名，保留日期、流水号、所在月份和文件内容，并同步归档台账中的文件名、路径引用。执行时禁止与下载任务并行，目标文件已存在时停止，发生错误时回滚。

## 每日调度

Codex 的凌晨任务每天 05:00、上午验证及补跑任务每天 09:20（Asia/Shanghai）执行，包含周末和法定节假日。凌晨任务跳过天猫；天猫商家及财务账号的订单、聚合账户资金、支付宝账户资金、淘宝联盟和万相台推广费统一纳入上午验证及补跑任务。两条任务直接调用下载总控，按配置串行执行：

```powershell
& ".venv\Scripts\python.exe" -m scripts.auto_download.run_all_platform_downloads --config scripts\auto_download\all_platform_downloads.json --lane overnight --exclude-platform 天猫 --lock-wait-seconds 0 --trigger-type schedule
& ".venv\Scripts\python.exe" -m scripts.auto_download.run_all_platform_downloads --config scripts\auto_download\all_platform_downloads.json --lane interactive --lock-wait-seconds 21600 --trigger-type schedule
```

`--trigger-type schedule` 将运行记录标记为定时执行，并校验上海时区当天的检查点日期；手动执行可省略此参数。两条任务共用每日检查点和互斥锁，上午任务跳过当天已成功的步骤，并等待凌晨总控释放锁后继续。`--exclude-platform` 跳过指定平台；不传时仍按原有全平台配置执行。
