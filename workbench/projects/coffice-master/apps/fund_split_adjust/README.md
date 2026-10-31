# 经营配置中心

统一承载银行资金、达播运营和数据导入三套配置台。数据导入模块默认随 Web 服务启动后台 Worker，上传文件不需要再单独启动另一个进程。

- 银行资金配置台：`http://127.0.0.1:8770/`
- 达播运营配置台：`http://127.0.0.1:8770/influencer/`
- 数据导入中心：`http://127.0.0.1:8770/ingest/`

银行下载文件进入 ODS，网页拆分、分类和调账结果进入财务确认 DWD。网页提交本身只锁定 DWD；独立的银行经营指标 ETL 只读取成功且已提交批次，再刷新主营业务收入、总营收、总费用和主营业务成本的 DWS/ADS。

## 已实现

- 银行 `.xlsx` 文件上传、SHA-256 防重复导入、源文件下载和批次审计。
- `原数据` 全量进入 `ods.ods_bank_statement`，完整 36 个源字段同时保存在 `raw_data`。
- 文件包含 `整理后` 时，按流水号和连续子行自动识别拆分、调账和分类，写入 `dwd.dwd_statement_split`。
- 主编辑表支持筛选、拆分/重拆、取消拆分、手工调账、一键平衡、批量分类、备注和提交锁定。
- 费用类型、入账科目、允许归属关系、导入记录和操作日志完整维护。
- 同一入账科目允许关联多个费用类型，以兼容样本中“入账-社会保险费”“入账-公积金”等真实跨类型归属。

## 环境

Python 3.12，并安装：

```powershell
pip install -r apps/fund_split_adjust/requirements.txt
```

数据库连接读取 `PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`，缺省主机、端口、数据库和用户分别为 `192.168.77.111`、`5432`、`mock_coffice`、`postgres`。

## 首次迁移与样本导入

```powershell
python etl/bank/load_bank_statement_ods.py `
  --file "data/银行/看板数据.xlsx" `
  --migrate `
  --operator "系统初始化"
```

样本应得到：ODS 58 条、DWD 63 条、费用类型 8 个、入账科目 25 个；三组拆分分别为税费、公积金和报销，调账净差为 `0.00`。

## 启动

```powershell
python apps/fund_split_adjust/server.py --bind 127.0.0.1 --port 8770
```

打开 `http://127.0.0.1:8770/`，通过左侧模块入口切换三个配置模块。数据导入 Worker 会在同一进程内自动启动；只有专门部署独立 Worker 时才传入 `--no-ingest-worker`。服务无自带登录模块，默认只监听本机；多人使用时应放在公司内网统一认证代理之后。

也可一次完成迁移、导入并启动：

```powershell
python apps/fund_split_adjust/server.py `
  --migrate `
  --import-file "data/银行/看板数据.xlsx"
```

`--migrate` 会执行银行资金、达播运营和数据导入模块迁移，各模块仍独立维护自己的迁移文件。

## 业务口径说明

- 拆分基准金额之和严格等于 ODS 原金额，调账不修改 ODS 或拆分基准金额。
- 待分配金额定义为 `ABS(SUM(adjusted_diff))`。正负调账对冲后为 0；同时另展示 `SUM(ABS(adjusted_diff))` 作为调整流量。
- 提交要求：待分配为 0、所有 DWD 行均已分类、所有母子行金额相等。提交只锁定 DWD 供后续链路使用，本阶段不写 ADS。

## 银行经营指标刷新

财务提交批次后执行：

```powershell
python etl/bank/run_bank_management_metrics_etl.py
```

指标 ETL 不读取未提交批次，并会在刷新前检查重复账号流水号、DWD来源覆盖、拆分基准金额、批次调账净差、分类关系和公司映射。任一检查失败时整次事务回滚。

## 测试

```powershell
python -m unittest apps.fund_split_adjust.tests.test_domain -v
python -m unittest apps.fund_split_adjust.tests.test_influencer_module -v
```
