# 商品编码映射页面预计算

商品编码映射列表读取 `ads.ads_product_code_mapping_workbench` 的当前成功版本。
搜索、平台/状态筛选和分页只处理该版本的规则结果，不在列表请求中扫描七平台商品组件DWS。
公司商品编辑候选按需加载，避免其请求阻塞列表显示。

## 数据与发布

- 业务口径保持 `common.v_operating_sales_product_code_observation`：已配置规则（包括停用和无观察订单规则）及未映射编码族。
- 付费、赠品、GMV、编码/平台集合和店铺去重口径沿用原观察查询。
- 457号SQL建立持久化刷新状态及配置语句级触发器；458号SQL建立ADS；459号SQL计算并发布新版本。
- 新版本逐字段双向对比观察查询，差异非零即抛错，整个ETL事务回滚。
- `ops.refresh_watermark` 的 `product_code_mapping` 水位保存当前版本、前一版本、数量及来源请求版本。
- 页面只读当前版本；新版本发布前保留旧版。旧版与新版共存，删除更早的派生版本不会修改ODS。
- 新表不对实时DIM建立外键，确保配置删除后仍能读取完整上一版本。商品删除依赖检查继续使用权威来源。

## 刷新入口

1. 订单导入的 `operating_sales` ETL 在DWD/DWS及商品销售ADS刷新、校验完成后，于同一事务生成页面ADS。
2. 商品、分类、编码映射、编码修正规则的增删改由数据库触发器在配置事务内递增请求版本；事务回滚时请求也回滚。
3. 商品后台队列合并连续请求，并定期检查持久化未完成请求；重启后恢复未完成工作。
4. 已明确失败的任务保留错误和待处理版本，页面提供“重试更新”；不会无限自动重试失败任务。
5. 页面区分“配置保存成功”和“统计更新完成”；后台成功后自动更新列表，保留尚未提交的筛选输入。
6. 导入关闭自动刷新时继续遵守该设置，不额外触发统计刷新。

所有刷新先取得全局ETL锁，再取得商品域事务锁。配置触发器只取得商品域锁。
导入Worker已在父连接持有全局会话锁，通过仅子进程有效的 `MOCK_COFFICE_ETL_LOCK_HELD=1` 告知ETL不要重复取同一把锁。
独立命令和商品后台刷新自行取全局锁。不要手工设置该内部标记。

## 首次升级与维护

先在已完成现有系统及商品配置迁移的数据库执行一次初始化：

```powershell
.\.venv\Scripts\python.exe -m etl.operating_sales.refresh_product_mapping_workbench
```

该命令只为当前进程加载项目根目录未提交的 `.env`，使用现有七平台商品DWS生成结果；不导入或修改ODS。
它不是商品规则变更后的全链路重算工具；存在尚未处理的配置变更时会拒绝仅重建页面结果，应由商品后台或完整运营成交ETL完成刷新。
随后由使用者重启后端，并刷新浏览器加载新前端。未来订单导入和商品配置保存会自动维护结果。

## 验证

```powershell
$env:RUN_PRODUCT_OBSERVATION_DB_TESTS='1'
.\.venv\Scripts\python.exe -m unittest apps.influencer_config.tests.test_product_mapping_workbench apps.influencer_config.tests.test_product_observation_sql
```

此开关仅对当前PowerShell进程及子进程有效，内容不是凭据。测试需已完成首次初始化；全部配置及派生结果变更均在事务中回滚。
覆盖字段一致性、筛选分页、赠品与精度、连续发布、旧版并发读取、失败回滚、持久化请求与配置全链路刷新、表和字段注释。
