# 正式数据测试库工具

本目录用于从只读 `mock_coffice` catalog 快照生成并验证 `coffice_production`。所有写入工具都会拒绝目标数据库名 `mock_coffice`，不会删除或覆盖任何数据库。

## 环境切换

将真实连接写入进程或服务账号环境，不要写入仓库：

```powershell
$env:TEST_DATABASE_URL = 'postgresql://<user>:<password>@<host>:<port>/mock_coffice'
$env:PRODUCTION_DATABASE_URL = 'postgresql://<user>:<password>@<host>:<port>/coffice_production'
```

开发测试环境：

```powershell
. .\scripts\production_db\Set-DatabaseEnvironment.ps1 -Environment test
```

正式数据测试环境：

```powershell
. .\scripts\production_db\Set-DatabaseEnvironment.ps1 -Environment production
```

该脚本将 URL 映射到项目现有的 `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD`，因此不需要修改后端和 ETL 代码。未显式选择生产环境时，项目原有缺省值仍指向 `mock_coffice`。

## 可重复执行流程

以下命令中的连接参数也可完全由环境变量或 `PRODUCTION_DATABASE_URL` 提供。密码只从环境读取。

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m scripts.production_db.audit_database --dbname mock_coffice --exact-counts
& $py -m scripts.production_db.analyze_dependencies
& $py -m scripts.production_db.generate_analysis_report
& $py -m scripts.production_db.generate_schema_migration

& $py -m scripts.production_db.create_database `
  --host <host> --user <admin-user> --maintenance-db postgres `
  --target-db coffice_production

& $py -m scripts.production_db.bootstrap_database `
  --host <host> --user <user> --dbname coffice_production
```

`bootstrap_database.py` 会在一个事务中执行生成结构、兼容性迁移（包括财务配置和看板组件）以及静态配置 seed；
失败会报告具体步骤并整体回滚。重复执行结构和 seed 不会重复建表或产生重复配置。

## 测试库清理

`cleanup_test_data.py` 只接受数据库名 `mock_coffice`，默认是只读筛查；只有显式传入
`--execute` 才会在一个事务中提交清理。脚本不使用 `CASCADE`，会先检查活动连接、运行中的导入/ETL
和外键边界，清空 ODS 原始导入、DWD/DWS/ADS 衍生事实、导入记录、ETL/Worker 运行记录、会话、登录尝试、
审计/AI会话日志，并重置刷新水位。DIM、商品/费用/达人映射、财务配置、看板组件、AI配置、IAM配置和夜间调度配置不会被清理。

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m scripts.production_db.cleanup_test_data --dbname mock_coffice
& $py -m scripts.production_db.cleanup_test_data --dbname mock_coffice --execute
```

## 测试配置迁移到正式库

`sync_approved_runtime_config.py` 只从测试库读取并写入非 `mock_coffice` 目标库，不复制 ODS、DWD、DWS、ADS
事实或任何会话/导入/ETL历史。它会同步全部保留的 DIM（包括新达人主数据、来源映射、月度商务归属和商品编码映射）、
IAM用户/角色/部门/权限关系、看板及组件、7张财务配置表；带上 `--include-encrypted-ai-config` 时再同步模型、
数据源、提示词及版本、飞书应用和验证码转发配置，密钥只在内存中传递，不打印、不落盘。

当前测试库的非零 GMV 目标不会默认覆盖正式库；确认要携带时显式增加 `--include-gmv-targets`。正式迁移建议使用：

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m scripts.production_db.sync_approved_runtime_config `
  --source-db mock_coffice `
  --target-db coffice_production `
  --include-gmv-targets `
  --include-encrypted-ai-config
```

如果使用 `TEST_DATABASE_URL` 和 `PRODUCTION_DATABASE_URL`，脚本会优先读取这两个进程环境变量；不要把真实密码写入命令、
仓库或文档。迁移完成后再用正式库审计和页面验收脚本核对结构与配置数量。

## 初始化数据边界

初始化脚本只执行项目内可审查 SQL：

- 24 条公司店铺严格 DIM 映射；Loader 和全部启用 ETL 必需。
- 8 个银行费用类型。
- 15 个银行入账科目及 19 条允许关系。
- 129 条平台费用映射模板。
- 40 个平台费用一级分类。
- 6 名商务人员、133 条达人月度归属，以及 3 条 0 元 GMV 目标。
- 19 条商品分类、40 个商品和 44 条商家编码映射（映射同时保留平台、店铺和原始编码）。
- 经营配置中心所需的预算配置、DWD、DWS、ADS 结构会创建为空表；`finance_operating_config` 仍不进入全量 ETL 调度。

经营配置中心运行配置由
`scripts/production_db/generated/002_runtime_config_seed.sql` 写入。该 SQL
由只读生成器从已确认配置生成，并使用 `ON CONFLICT DO NOTHING`；重复执行
只补缺失记录，不覆盖正式库后续网页维护结果。

不会初始化银行流水、拆分、上传记录、任务历史或任何 ODS/DWD/DWS/ADS
业务数据。生成配置快照可执行：

```powershell
& .\.venv\Scripts\python.exe -m scripts.production_db.generate_runtime_config_seed `
  --host <host> --user <user> --dbname mock_coffice
```

## 验证

```powershell
& .\.venv\Scripts\python.exe -m scripts.production_db.audit_database `
  --dbname coffice_production --exact-counts `
  --output docs\production_database\coffice_production_catalog.json

& .\.venv\Scripts\python.exe -m scripts.production_db.compare_catalogs
& .\.venv\Scripts\python.exe -m scripts.production_db.validate_empty_dashboard `
  --host <host> --user <user> --dbname coffice_production
& .\.venv\Scripts\python.exe -m scripts.production_db.validate_empty_etl `
  --host <host> --user <user> --dbname coffice_production
```

`validate_empty_etl.py` 只用于诊断。当前 ETL 保留严格源数据校验，ODS 为空时大部分任务会主动失败；不要把它配置为部署时自动执行。

## 回滚

数据库切换回滚不删除数据：停止正式环境 Web/Worker/计划任务，然后执行：

```powershell
. .\scripts\production_db\Set-DatabaseEnvironment.ps1 -Environment test
```

`coffice_production` 会原样保留。工具不提供自动 `DROP DATABASE`；如确认永久废弃，必须由 DBA 备份并人工审批后处理。
