# 天猫宝贝销售明细迁移与指标加工实施报告

## 1. 实施结论

天猫订单源从“主订单导出报表”切换到“宝贝销售明细报表”的代码改造已经完成：

- 规范ODS表名继续使用`ods.ods_tmall_order_raw`，不要求下游更换表名。
- ODS业务粒度改为一个标准店铺下一个子订单一行。
- 源文件只入库13个当前指标必需字段，其余字段由Loader忽略。
- GSV、运营GMV、退款、订单、件单价、产品占比、达人业绩和达人佣金补零均已适配真实子订单粒度。
- 天猫已接入七平台运营成交三张共享ADS，DataEase原共享数据集可以继续使用。
- 产品编码`A1`、`C3`已幂等初始化为`非商品 -> 购物金 -> 购物金`，保证产品分摊金额与总GMV对账。
- 商品品类配置后台的保存刷新范围已加入天猫产品分摊。
- 两次事务内全量刷新结果一致，测试事务已回滚，正式数据库旧ODS未被替换。

正式迁移已于2026-07-28完成。2026-07-29将新增退款状态和退款金额的同范围文件作为批次45追加导入；当前`ods.ods_tmall_order_raw`保留批次41和45共2,196个来源版本，最新业务粒度仍为1,098个子订单、558个主订单。旧ODS已移出规范链路并归档为`ods.ods_tmall_order_raw_legacy_20260728_164401`。

迁移程序默认仍强制检查完整历史覆盖。只有用户明确确认可丢弃旧测试数据时，才允许同时使用`--execute --allow-incomplete-history-for-test-cutover`显式执行不完整历史切换，防止日常迁移误用。

## 2. 标准ODS

### 2.1 业务字段

`ods.ods_tmall_order_raw`保留以下13个源业务字段：

1. `子订单编号`
2. `主订单编号`
3. `商品标题`
4. `购买数量`
5. `商品属性`
6. `订单状态`
7. `商家编码`
8. `买家应付货款`
9. `买家实付金额`
10. `退款状态`
11. `退款金额`
12. `订单创建时间`
13. `订单付款时间`

同时保留七个公共审计字段。Loader允许源文件包含额外列，但上述13列缺少任意一列都会停止导入。

### 2.2 店铺归属

新报表没有可靠的店铺字段，每次导入必须显式传入标准`shop_code`。当前文件对应：

| 平台 | 标准店铺编码 | 店铺 | 公司 |
| --- | --- | --- | --- |
| tmall | 549820088 | MOCK旗舰店 | 墨客咖时（南京）生物科技有限公司 |

ODS只保存`batch_id`，平台、店铺和公司仍通过`ods.ods_file_ingest_log`及`common.v_ingest_batch_shop_context`取得。

## 3. 指标口径与分层

| 指标 | DWD最小粒度 | DWS口径 |
| --- | --- | --- |
| GSV | 标准店铺+子订单最新版本 | 排除`交易关闭`、退款状态`退款成功`及标题含`购物金`，汇总`买家实付金额`；付款日期优先、创建日期兜底 |
| 运营成交 | 标准店铺+子订单最新版本 | GMV为`买家应付货款`；不按状态筛GMV；`交易关闭`同口径金额计退款 |
| 成交订单 | 同上 | 按`主订单编号`去重 |
| 成交件数 | 同上 | 有效正GMV商品行取购买数量，辅助行和零GMV行记0 |
| 产品占比 | 有效正GMV子订单的编码组件 | 按付费编码数量权重拆分，最后一项吸收分币差 |
| 达人业绩 | 标准店铺+子订单最新版本 | 标题命中达人，GMV取买家应付，交易关闭计退款 |
| 达人佣金 | 标准店铺+子订单最新版本 | 天猫当前无佣金源，按自然日生成零值占位 |

运营和达人链路均按主订单`买家应付货款`合计大于2,000元排除整单；等于2,000元保留。运营链路把标题等于`MOCK推荐官`或包含`赠品勿拍`的辅助行GMV、退款和件数归零，但保留主订单参与订单数去重。

## 4. 数据库对象

### ODS与迁移

- `sql/tmall/ods/18_ods_tmall_order_raw_postgres.sql`
- `sql/tmall/ods/297_ods_tmall_order_raw_item_grain_stage_postgres.sql`
- `etl/tmall/load_tmall_order_ods.py`
- `etl/tmall/migrate_tmall_order_source.py`

迁移程序先把所有新格式文件装入临时表并完成覆盖、唯一性、金额和店铺映射校验；仅在`--execute`模式且全部通过时，才在同一事务中把旧ODS归档并将新表切换为规范表名。

### GSV

- `sql/tmall/gsv/40_dwd_tmall_gsv_order_detail_postgres.sql`
- `sql/tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql`
- `sql/tmall/gsv/42_refresh_dwd_tmall_gsv_order_detail_postgres.sql`
- `sql/tmall/gsv/43_refresh_dws_tmall_gsv_shop_daily_postgres.sql`
- `etl/tmall/run_tmall_gsv_etl.py`

### 运营成交和产品占比

- `sql/tmall/operating_sales/298_dwd_tmall_operating_sales_order_item_detail_postgres.sql`
- `sql/tmall/operating_sales/299_dws_tmall_operating_sales_order_item_postgres.sql`
- `sql/tmall/operating_sales/300_dws_tmall_operating_sales_product_allocation_postgres.sql`
- `sql/tmall/operating_sales/301_refresh_dwd_tmall_operating_sales_order_item_detail_postgres.sql`
- `sql/tmall/operating_sales/302_refresh_dws_tmall_operating_sales_order_item_postgres.sql`
- `sql/tmall/operating_sales/303_refresh_dws_tmall_operating_sales_product_allocation_postgres.sql`
- `sql/dim/304_seed_tmall_shopping_fund_product_postgres.sql`
- `etl/operating_sales/run_operating_sales_etl.py`

共享ADS刷新SQL`163`、`164`、`165`已加入天猫DWS。

### 达人业绩和佣金

- `sql/tmall/influencer_performance/281_tmall_influencer_performance_tables_postgres.sql`
- `sql/tmall/influencer_performance/282_refresh_tmall_influencer_performance_postgres.sql`
- `etl/influencer_performance/run_multiplatform_influencer_performance_etl.py`
- `sql/tmall/influencer_commission/289_tmall_influencer_commission_zero_tables_postgres.sql`
- `sql/tmall/influencer_commission/290_refresh_tmall_influencer_commission_zero_postgres.sql`
- `etl/influencer_commission/run_influencer_commission_etl.py`

### 一键刷新

`etl/tmall/run_tmall_order_metrics_etl.py`依次刷新天猫GSV、七平台运营成交与产品占比、多平台达人业绩和达人佣金补零。

## 5. 当前新文件验收结果

### 5.1 文件和ODS目标

| 验收项 | 结果 |
| --- | ---: |
| 源明细行/子订单 | 1,098 / 1,098 |
| 主订单 | 558 |
| 日期范围 | 2026-06-25至2026-07-05 |
| 按用户确认不再进入规范ODS的旧测试主订单 | 2,634 |
| 未映射批次店铺 | 0 |

### 5.2 GSV

| 验收项 | 结果 |
| --- | ---: |
| DWD子订单 | 1,098 |
| 交易关闭子订单 | 238 |
| 非交易关闭购物金子订单 | 9 |
| 非交易关闭且非购物金退款成功子订单 | 1 |
| GSV纳入子订单/主订单 | 850 / 429 |
| GSV | 43,934.37 |

### 5.3 天猫运营成交

| 指标 | 结果 |
| --- | ---: |
| GMV | 64,891.08 |
| 退款 | 9,157.84 |
| 退款率 | 14.11% |
| 成交主订单 | 558 |
| 成交件数 | 568 |
| 成交件单价 | 114.24 |
| 产品分摊组件 | 741 |
| 未映射付费组件 | 0 |

七平台共享ADS验收结果：

| 验收项 | 结果 |
| --- | ---: |
| GMV/退款/订单/件数 | 2,026,185.98 / 596,391.74 / 13,030 / 12,809 |
| 退款率/件单价 | 29.43% / 158.18 |
| 指标卡/流量/产品ADS行数 | 91 / 442 / 509 |
| 三张ADS未匹配公司 | 0 / 0 / 0 |
| 三张ADS最终粒度双向差异 | 0 / 0 / 0 |

### 5.4 天猫达人

| 验收项 | 结果 |
| --- | ---: |
| 达人DWD子订单 | 1,098 |
| 达人DWS商品行 | 5 |
| 活跃达人 | 1 |
| 达人GMV/退款 | 495.00 / 99.00 |

`【加购！胡可推荐】`和`【胡可推荐】`继续统一为达人“胡可”，达人稳定ID按月度归属配置取得。

### 5.5 达人佣金补零

天猫佣金DWD为1,098个子订单，生成11个自然日零值DWS；旧版独立达人佣金链路停用时保留的历史总额为909,067.88元，当前看板不再读取该ADS。

## 6. 正式迁移操作

### 6.1 补导并只读校验

先按相同宝贝销售明细格式补导旧ODS覆盖的历史区间，并把所有历史新格式文件同时传给迁移程序：

```powershell
python etl/tmall/migrate_tmall_order_source.py `
  --file "data/天猫/订单/天猫历史销售明细表.xlsx" `
  --file "data/天猫/订单/天猫订单6.25-7.5销售明细表+退款状态+退款金额.xlsx" `
  --shop-code 549820088
```

不带`--execute`时只探查文件、临时装载并执行校验，不切换规范ODS。必须看到：

- 旧ODS所有主订单均被新文件覆盖；
- 缺失历史主订单为0；
- 子订单主键唯一；
- 所有批次店铺映射有效；
- 必需字段和日期均合法。

### 6.2 原子切换

只读校验通过后，用相同文件清单增加`--execute`：

```powershell
python etl/tmall/migrate_tmall_order_source.py `
  --file "data/天猫/订单/天猫历史销售明细表.xlsx" `
  --file "data/天猫/订单/天猫订单6.25-7.5销售明细表+退款状态+退款金额.xlsx" `
  --shop-code 549820088 `
  --execute
```

程序在一个事务内完成新批次登记、旧ODS归档和新ODS表名切换。任一步失败都会回滚。

本次测试数据切换经用户明确授权，不导入历史文件，实际执行命令为：

```powershell
python etl/tmall/migrate_tmall_order_source.py `
  --file "data/天猫/订单/天猫订单6.25-7.5销售明细表+退款状态+退款金额.xlsx" `
  --shop-code 549820088 `
  --execute `
  --allow-incomplete-history-for-test-cutover
```

该豁免参数只允许在明确可丢弃旧测试数据时使用，不作为日常生产迁移方式。

### 6.3 全链路刷新

```powershell
python etl/tmall/run_tmall_order_metrics_etl.py --enforce-current-file-baseline
```

当前规范ODS只包含本次1,098行固定测试文件，因此使用固定基准参数。后续导入新订单批次后应移除该参数，并以实际来源行数、日期范围和汇总金额验收。

### 6.4 日常增量导入

正式迁移后，后续天猫销售明细继续使用：

```powershell
python etl/tmall/load_tmall_order_ods.py `
  --file "data/天猫/订单/新销售明细表.xlsx" `
  --shop-code 549820088
```

同一日期区间重复导出不会直接覆盖旧批次；DWD按`标准店铺+子订单编号`选择最新版本。

## 7. DataEase

以下共享数据集表名不变：

- `ads.ads_operating_sales_company_shop_daily`
- `ads.ads_operating_sales_traffic_company_shop_daily`
- `ads.ads_operating_sales_product_company_shop_daily`

天猫流量源字段当前不存在，统一展示为`未提供 -> 未提供`。产品图表可使用`large_product_category -> product_category_l2 -> product_name`三级下钻；达播看板默认展示二级分类，一级分类继续保留给筛选和汇总。

正式切换后必须核对：

- 指标卡合计等于ADS合计；
- 平台、流量和产品图表的各点之和等于对应指标卡；
- 公司、日期、平台和店铺筛选联动；
- 产品ADS含购物金时与总GMV对账，过滤一级分类`非商品`时只解释公司商品。

## 8. 当前操作边界

规范ODS已经切换并完成两次连续全链路刷新。旧3,192行不再参与任何指标，但按项目原始数据保护规则保留在独立归档表，不进行不可恢复的物理删除。`天猫订单4.10-5.30销售明细表.xlsx`未导入ODS，也未登记成功导入批次。

切换后验收：

- 规范ODS：2,196个来源版本、1,098个最新子订单、558个主订单，日期为2026-06-25至2026-07-05；
- 新退款字段批次：45，店铺映射`tmall / 549820088 / MOCK旗舰店`；
- 天猫GSV：43,934.37元（已排除交易关闭、退款成功和购物金）；
- 天猫运营GMV/退款：64,891.08元 / 9,157.84元；
- 产品分摊741个组件，未映射付费组件0；
- 天猫达人GMV/退款：495.00元 / 99.00元；
- 两次连续刷新结果一致，DWS/ADS双向差异和未匹配公司均为0。
