# 达人运营配置台

用于维护达播达人配置库的月度历史版本、商务跨平台月度GMV目标，以及公司统一商品分类、产品和商家编码映射。达人列表只读取配置库，不会把订单中的当月活跃达人补入配置库。达人或商品配置保存后会在同一数据库事务中刷新对应ADS。

## 启动

推荐通过统一配置中心启动：

```powershell
python apps/fund_split_adjust/server.py --bind 127.0.0.1 --port 8770
```

浏览器访问 `http://127.0.0.1:8770/influencer/`。统一服务只通过 `apps/fund_split_adjust/influencer_module.py` 挂载本模块，本目录内的前端、业务规则和数据库访问仍可单独维护。

如需独立调试本模块，也可以继续使用原有启动方式：

先配置项目统一使用的PostgreSQL环境变量：`PGHOST`、`PGPORT`、`PGDATABASE`、`PGUSER`、`PGPASSWORD`，然后在项目根目录运行：

```powershell
python apps/influencer_config/server.py --bind 127.0.0.1 --port 8765
```

浏览器访问`http://127.0.0.1:8765/`。

服务默认只监听本机，不包含登录模块。需要多人共享时，请放到公司的内网反向代理和统一身份认证之后，不要直接暴露到公网。

## 初始导入

达人归属Excel按指定生效月导入：

```powershell
python etl/common/load_influencer_business_assignment.py `
  --file "data/达人归属/达人归属表-（月更）.xlsx" `
  --month 2026-07-01
```

导入按`平台+达人ID+生效月`去重，已有同月版本不会被覆盖，因此网页中手工维护的结果会被保留。

## 使用规则

- 选择“配置月份”后修改归属，只新增或更新该生效月版本，不覆盖历史月份。
- 可新增、查询、编辑和删除配置库达人；编辑支持修改平台、UID、达人名称、商务、店铺和备注。
- 达人列表采用服务端分页，默认每页20条，可切换10、20、50或100条；工具栏选择筛选条件或输入搜索词时不会立即请求，点击“查询”后才应用全部条件并回到第一页，“重置”会清空条件并刷新。
- 删除会在所选月份写入停用版本，从该月起不再显示，但之前月份的历史仍可查询。
- 未分配达人可以保留；设置为“未分配商务”会写入显式的未分配版本。
- 商务目标按`商务+月份`维护，为跨平台总目标；商务姓名可在目标表第一列直接修改，并随本行目标一起保存。
- 删除商务执行软停用：从当前配置和可选商务中移除，但保留已有达人归属及月度目标历史。
- 商品生效关系为`一级分类 -> 二级分类 -> 公司商品 <- 公司级编码表达规则`。`product_id`是稳定系统主键，`company_product_code`是独立业务编码；平台和店铺只保存在订单事实与观察统计中，不参与商品归属。
- “商品品类配置”包含公司商品、一级分类和二级分类；公司商品内部ID统一为`PRD-CODE-`加16位十六进制且不在业务列表展示。统一“商品编码映射”工作台同时展示七平台实际观察编码、未映射编码族和已配置规则，可直接映射到公司商品，不再保留重复的“原始商品编码”菜单。
- “商品编码映射”下的“编码修正规则”用于维护仓库手工漏写分隔符等异常组件，例如把`M-RYKK-1M-NXSY-XD-1`改写为`M-RYKK-1+M-NXSY-XD-1`；修正发生在商品与数量解析之前并保留原组件和规则ID审计。
- 商品编码映射列表读取预先生成的ADS结果；订单导入刷新或商品配置变更后自动更新。更新期间展示上一成功结果，完成后自动刷新；失败时可点击“重试更新”。首次升级命令和刷新说明见[商品编码映射预计算](../../docs/product_code_mapping_workbench.md)。
- 编码尾部正整数只表示数量，`M-MGNT-1/-2/-10`共用`M-MGNT`规则；前缀数量缩写（如`2MG`）通过公司级别名规则识别。组合装按`+`拆组件，赠品仍解析和映射，但`paid_quantity=0`、GMV为0且不进入付费数量分母。
- 商品配置保存、停用、启用或删除后，会刷新七平台产品组件DWS和共享商品ADS；看板按稳定商品ID和公司商品编码汇总。未配置编码族仍带GMV进入ADS并在工作台告警，不会丢失金额。
- 商品列表采用服务端分页；筛选和搜索在左、新增按钮在右，筛选项和搜索词均须点击“查询”后才生效，“重置”会恢复默认条件并刷新；分页区左侧显示总数，右侧依次为每页条数、前后翻页和页码。
- 分类、产品或商家编码保存后，服务会在同一事务中刷新产品分摊DWS和产品占比ADS，DataEase直接看到新分类名称和产品归属。
- 商品“停用”保留记录且可以重新启用；“删除”永久移除记录。存在下级分类或产品时不允许删除分类，避免误改看板归属。
- Excel导入记录被网页修改后转为`manual`维护来源，后续文件刷新不会覆盖人工名称或归属。
- 实际达成、完成率、归属达人和月10万+人数均来自ADS，不在页面前端自行计算。
- 新增商务后即可在归属和目标配置中使用；名称修改和删除均可在商务月度目标页完成。

## 接口

- `GET /api/health`：数据库与服务健康状态。
- `GET /api/businesses`：在职商务列表。
- `POST /api/businesses`：新增商务。
- `PUT /api/businesses/{id}`：修改商务姓名。
- `DELETE /api/businesses/{id}`：软停用商务并保留历史数据。
- `GET /api/influencers`：只从配置库按月份、平台、商务、归属状态和关键字查询达人。
- `POST /api/assignments`：新增或编辑达人月度配置版本并刷新ADS。
- `DELETE /api/influencers`：写入达人停用版本并刷新ADS，保留删除月份以前的历史。
- `GET /api/targets`：查询商务月度目标及实际结果。
- `POST /api/targets`：保存商务月度目标并刷新ADS。
- `GET /api/product-categories`：查询品类、产品统计和页面指标卡数据。
- `POST /api/product-categories`、`PUT /api/product-categories/{id}`：新增、编辑一级或二级分类。
- `DELETE /api/product-categories/{id}`、`PUT /api/product-categories/{id}/status`：永久删除或停用/启用品类。
- `GET /api/product-catalog`：兼容旧页面的商品和编码联表查询。
- `GET /api/product-category-list`：按层级、状态、关键字和页码查询一级/二级分类子页面。
- `GET /api/products`：分页查询产品选项；也保留`GET /api/product-categories/{id}/products`。
- `GET /api/product-categories/{id}/products`：分页搜索指定品类的产品。
- `GET /api/products`、`POST /api/products`、`PUT /api/products/{product_id}`、`DELETE /api/products/{product_id}`：公司商品分页查询及增删改；`PUT /api/products/{product_id}/status`停用或启用。
- `GET /api/product-mappings`：统一查询已配置规则与七平台观察到的未映射编码族；平台参数只筛选观察来源。
- `POST /api/product-mappings`、`PUT /api/product-mappings/{id}`：维护全公司编码表达（后缀数量、前缀数量或精确编码）到公司商品的规则；`POST /api/product-mappings/batch`支持工作台直接映射。
- `GET/POST /api/product-code-normalizations`、`PUT/DELETE /api/product-code-normalizations/{id}`：查询和维护公司级异常编码组件修正规则；`PUT /api/product-code-normalizations/{id}/status`停用或启用。
- `GET /api/product-source-codes`：保留为兼容查询，返回与统一工作台相同的数据，不再对应独立页面。
- `DELETE /api/product-mappings/{id}`、`PUT /api/product-mappings/{id}/status`：停用或启用商家编码。

达人配置使用公司统一达人身份：`dim_company_influencer`保存公司达人，`dim_company_influencer_source_mapping`保存各平台UID到公司达人的映射，`dim_company_influencer_business_assignment_monthly`按公司达人和月份保存商务归属。同一达人跨平台合并时若已有商务归属冲突，接口会返回冲突明细并要求明确保留目标归属或使用来源归属。

商品品类表迁移包含在统一服务的 `--migrate` 中；单独启动本模块时也可执行：

```powershell
.\.venv\Scripts\python.exe -m apps.influencer_config.server --migrate --bind 127.0.0.1 --port 8765
```

可执行不会保留测试数据的接口验收：

```powershell
.\.venv\Scripts\python.exe -m apps.influencer_config.crud_smoke_test
```

商品分类、产品、商家编码和看板刷新链路可执行：

```powershell
.\.venv\Scripts\python.exe -m apps.influencer_config.product_catalog_crud_smoke_test
```

七平台公司商品身份与赠品分摊可执行只读回归验收：

```powershell
.\.venv\Scripts\python.exe -m etl.operating_sales.validate_product_identity
```
