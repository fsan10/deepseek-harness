# 结算来源选择与月报对账

## 本次修复

2026 年 9 月抖音、快手、小红书和天猫结算曾将被月报覆盖的旧日报同时计算。
保留所有 ODS 原始事实，只修改结算 DWD 的输入来源及 ETL 的有效行数基准。
收入、费用分类、退款、业务日期和公司归属公式继续使用现有链路。
拼多多继续使用已有范围覆盖规则；京东继续使用最新单据版本；视频号本次无来源重叠。

快手新增 DIM：MOCK音咖专卖店，店铺和账号 ID `2376318498`，公司漯河音咖商贸有限公司，编码 `company_013`。
迁移文件 `sql/dim/437_ks_yinka_shop_postgres.sql` 可重复执行，已有冲突归属时停止。

## 采用的架构

ODS → 覆盖登记/来源选择 → 平台原有 DWD/DWS → 事务内对账 → 共享日/月 ADS。

- 复用 `ods.ods_file_ingest_log` 的原始文件、SHA256、工作表、店铺映射和导入状态。
- 新增一张 `common.settlement_source_registry`，只登记批次的完整查询范围、显式分片组、证据和规则版本。
- `common.v_settlement_source_decision` 提供每批次每日期的选择结果、原因及覆盖者。
- `common.v_effective_settlement_source` 和各平台 `common.v_current_*_raw` 给 DWD 提供有效来源。
- 无需另建决策实体表：本规则没有待审批状态，决策可由登记信息和导入日志确定性计算；每次对账导出结果快照留作审计。
- 无需新建隔离数仓：对账工具在同一数据库事务内试算，其他连接只能看到已提交结果。任何失败回滚全部刷新；全部对账通过后才提交共享 ADS。

## 覆盖规则和保护条件

按标准店铺和 ODS 来源表独立选择；天猫两个账户不会互相覆盖。
经证明的完整宽范围覆盖窄范围；同范围取最新成功导入组。分片按完整组比较版本并全部保留。
未知范围的旧来源，只在被较新已验证来源覆盖的日期停止参与；范围外流水继续保留。
同一天仍存在两个有效组、未知新版本或交叉范围时停止 ETL，列出冲突批次。
不按订单号、金额、时间或业务字段去重；同一文件内的两条相同合法流水均保留。

小红书同一文件两张配套工作表必须同时成功入库、范围一致、所选版本一致；空工作表也参与完整性校验。
覆盖登记须核验原始文件摘要、完整导入行数、业务日期边界；ETL 仍验证全部历史批次映射。
自动登记只接受 `coverage_verified` 下载回执，且文件摘要、标准店铺和步骤查询日期一致。
回执尚未回填 batch_id 时，可用文件摘要与标准店铺绑定成功批次。
文件名前缀及第一笔/最后一笔交易日期均不能单独证明完整查询范围。

## 人工导入后的范围登记

没有可信下载回执时，依据平台导出参数或人工确认的完整区间创建 JSON 清单。
下面示例中的批次 ID 应替换为实际成功批次，说明应填写真实的确认依据：

```json
[
  {
    "batch_id": 123,
    "start": "2026-09-01",
    "end": "2026-09-30",
    "evidence": {"confirmation": "平台导出查询参数确认完整9月，已核对文件"}
  }
]
```

同一完整导出的多个分片还须填写相同 `group_key`；不同导出不可共用该键。
小红书两个工作表填写相同的文件组和完整查询范围。
登记命令只加载项目 `.env` 中的 PG 配置到本进程，不写 Windows 用户或系统环境变量：

```powershell
& .\.venv\Scripts\python.exe -m etl.common.settlement_sources --manifest <覆盖登记JSON路径>
```

已有不同范围的登记不会被静默覆盖。新增来源范围不明且与现有来源冲突时，先确认区间再登记。

## 发布前对账

`etl.platform_finance.reconcile_settlement` 的来源清单每项包含：
`path`、`platform_code`、`target_table`、`sheet`（Excel工作表）、`header_row`、`start`、`end`、`evidence`。
清单必须包括验收月份所有已发布店铺的参考报表；同店铺不同账户或配套表分别列出。
凭文件 SHA256 关联成功 ODS 批次，不根据文件名猜店铺。

```powershell
# 先保存修复前 ODS 批次事实摘要。
& .\.venv\Scripts\python.exe -m etl.platform_finance.reconcile_settlement --snapshot-only --output <修复前ODS摘要JSON>
# 同事务试算四个平台并刷新共享ADS，收入/支出/净额/事件数逐日、逐月全部一致才提交。
& .\.venv\Scripts\python.exe -m etl.platform_finance.reconcile_settlement --apply --manifest <来源清单JSON> --before-snapshot <修复前ODS摘要JSON> --output <对账结果JSON>
# 提交后独立复核，不刷新或提交数据库数据。
& .\.venv\Scripts\python.exe -m etl.platform_finance.reconcile_settlement --manifest <来源清单JSON> --output <复核结果JSON>
```

当前工具验收单个完整自然月；`--start` 必须是月初，`--end` 必须是对应月末。
检查包括文件与 ODS 全日期收支及数量、每表至少五条原始字段抽样（不足五条时检查全部）、
平台既有粒度/组成金额/公司映射校验、共享日/月 ADS 一致、原始 ODS 内容摘要不变。

天猫按现有结算分类核对月度资金文件中参与结算的款项，不能与整张资金账单总收支混用。
视频号本次无独立 `202609` 月报，仅核对现有范围文件中的 9 月部分；这不证明未取得报表的完整性。
抖音吉饮由用户自行导入，不在本次补录或验收店铺中。

## 测试

```powershell
& .\.venv\Scripts\python.exe -m unittest etl.common.tests.test_settlement_sources -v
```

测试在随机命名的 `codex_settlement_test_*` 临时数据库运行，事务回滚并删除该数据库。
生产库不写入测试批次、测试会话或测试日志。
