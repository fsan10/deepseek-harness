# 资金与结算混合经营收支的来源选择和验收

经营收入读取 `ads.ads_platform_main_business_income_company_shop_daily_category`，
经营费用读取 `ads.ads_platform_expense_company_shop_daily_category`。
纯结算月度指标读取 `ads.v_settlement_net_company_shop_monthly_metric`。
两套指标分别验收；纯结算通过不代表混合链路的资金补充来源也已验证。

## 来源选择

- 抖音、快手、小红书、天猫的结算或结算用资金来源，复用
  `common.settlement_source_registry` 及 `common.v_current_*_raw` 的有效覆盖来源。
  继续校验范围证据、成功完整导入、全部历史批次映射、小红书配套表和天猫账户隔离。
- 抖音资金按标准店铺、动账账户、平台动帐流水号识别同一来源流水。
  快手按标准店铺、平台账务流水号；视频号经营链路按标准店铺、流水单号。
  跨文件的相同身份只选择一份完整、业务字段一致的版本，绑定原始文件SHA256。
  不按订单、金额或首末交易日期猜测来源覆盖。
- 流水身份缺失、同一文件身份不唯一、跨文件业务字段冲突、文件摘要不符、
  历史批次未映射或导入不完整时停止刷新，保留全部ODS供核查。
  同订单同金额但平台流水号不同的冻结、解冻、最终扣减等记录均保留。
- 拼多多沿用现有报表声明范围选择。京东沿用单据编号和七字段资金事件版本规则。
  京东、天猫的版本分组及DWD主键加入标准店铺身份；相同单号不能覆盖其他店铺。
  退款跨来源核对也限定标准店铺，不能用另一店铺的退款排除本店退款。

上述修改只改变计算来源，不改变来源金额公式、日期、已维护的分类或经营归属。
资金退货款冲减收入，佣金/服务费返还冲减费用；不能为匹配目标金额重复冲减。
没有覆盖证据的单一来源可以核对已有数据，但不能声称覆盖完整自然月，
也不能授权它替换其他来源或删除原始流水。

## 原子验收与刷新

命令只在当前进程读取项目根目录未提交的 `.env`，不写Windows用户或系统环境变量。
来源清单使用 `etl.platform_finance.reconcile_settlement` 的已核验文件格式，
必须包含验收月份所有已发布店铺、独立账户和配套表。
独立资金参考清单填写 `platform_code`、已核实的标准 `shop_code` 和 `path`，
通过 `--fund-manifest` 同时核对抖音、快手、京东资金文件的SHA256、完整入库行数及每行全部原始字段。
缺少成功导入批次时停止，不能把尚未导入的本地资金文件视为零值；天猫账户文件已包含在结算参考清单中。

```powershell
# 预演：完成两次刷新和验收后全部回滚。
.\.venv\Scripts\python.exe -m etl.platform_finance.reconcile_operating_sources --settlement-manifest <当前结算来源清单.json> --fund-manifest <独立资金来源清单.json> --output <经营来源预演.json>
# 提交：同一事务内全部校验通过后，原子更新混合经营指标和平台银行汇总。
.\.venv\Scripts\python.exe -m etl.platform_finance.reconcile_operating_sources --apply --settlement-manifest <当前结算来源清单.json> --fund-manifest <独立资金来源清单.json> --output <经营来源验收.json>
```

验收包括源文件与ODS逐日原始金额、记录数和字段抽样，纯结算日/月收支与净额，
七平台所选来源与候选DWD身份双向对照、原有分层校验、最终经营DWS与两张ADS一致、
两次刷新幂等，以及ODS事实、既有财务配置和纯结算ADS内容摘要不变。
补齐来源后可用 `--platform ks` 仅重建相应平台；仍完整验证七平台来源身份、共享ADS及纯结算。
费用ADS以正数记费用，返还以负数冲减；纯结算视图的支出展示符号沿用各平台确认字段。

纯结算来源清单中的 `unverified_single_source: true` 仅用于核对确无范围登记的单一有效来源。
验收工具检查实际来源决策，不因此生成覆盖登记；结果会记录范围尚未证实。
拼多多文件侧验收按已确认的退款归入收入及负号展示规则核对，原始文件核对仍保留原始收支。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest etl.common.tests.test_finance_sources etl.common.tests.test_settlement_sources etl.common.tests.test_settlement_reference -v
```

来源边界测试在随机命名的临时数据库执行，结束后回滚并删除数据库；
不在生产库保留测试批次、会话、登录尝试或审计记录。
