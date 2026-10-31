# 财务单指标 ODS 到 DataEase 标准开发流程

## 1. 项目目标

本项目只服务于指标逻辑快速验证和 DataEase 展示，不追求标准数仓复用。每收到一个指标或一种新图表需求，就为它建立独立的 DWD、DWS、ADS、刷新 SQL 和 ETL。

```text
平台源文件 -> 批次店铺确认 -> ODS -> 指标专属DWD -> 平台专属DWS -> DIM公司映射 -> 指标专属ADS -> DataEase
```

DataEase 只能读取 ADS。ODS 是源数据事实，DWD 用于可追溯清洗，DWS 承担平台计算口径，DIM维护公司店铺关系，ADS只输出公司与图表所需粒度。

平台资金经营收支的归属和一级分类独立维护：分类未映射保留已确认金额，提现及账户划转保留全部明细但不进入经营总额。该财务链路的来源公式与最终归属DWS阶段、ADS和验收命令见[经营收支归属说明](platform-operating-treatment.md)。

项目自动化入口固定为：先使用 `$explore-ods-data` 完成只读探查和业务确认；确认报告中 `remaining_questions` 为空后，再使用 `$build-metric-pipeline` 设计图表并实施指标链路。

## 2. 指标输入模板

开始开发前必须确认以下内容：

| 项目 | 必填内容 |
| --- | --- |
| 指标 | 指标中文名、英文编码、业务定义 |
| 平台 | 抖音、京东、快手等 |
| ODS来源 | 来源表及必须使用的原始字段 |
| 公式 | 字段优先级、加减关系、空值和文本金额处理 |
| 日期 | 指标归属日期及兜底字段 |
| 筛选 | 订单状态、售后状态和其他枚举条件 |
| 维度 | 平台、店铺、渠道、商品等 |
| 展示 | 指标卡、趋势图及图表最终粒度 |

口径未确认前只允许分析 ODS，不允许生成指标结果。

## 3. ODS 探查

1. 读取对应 ODS 建表 SQL，确认字段名称和类型。
2. 查询数据库真实数据，统计总行数、最小粒度唯一性和日期范围。
3. 查看状态字段枚举及数量，避免凭字段名猜测过滤条件。
4. 检查指标金额字段的空值、横杠、负数、文本前缀和解析失败情况。
5. 检查店铺、订单和子订单关系，并核对全部`batch_id`的店铺映射状态。
6. 分别计算候选口径并交由用户锁定，记录最终基准值。

ODS 只允许读取和追加导入，不得为了指标结果修改源数据。

## 4. 公司店铺DIM

公司、店铺、平台账号统一维护在 `dim.dim_platform_shop_company`。`shop_identity_key`由平台编码和店铺编码生成，版本代理主键支持同一店铺按有效期变更公司归属。

后台通过“系统管理 -> 平台店铺公司映射”维护该表。平台编码允许自定义，但这里只建立DIM映射；新平台仍需单独建设对应的ODS、DWD、DWS、ADS和ETL链路后才能产出指标。

- 公司与店铺关系不得硬编码在指标SQL中。
- 每次文件导入必须显式传入一个标准`shop_code`，由公共Loader校验DIM并写入导入日志。
- 同平台、店铺、目标表和文件哈希已经成功导入时，Loader必须拒绝创建重复批次。
- ODS明细不保存公司字段，通过`batch_id`关联`common.v_ingest_batch_shop_context`取得标准店铺。
- 源店铺字段与批次店铺冲突、批次未映射或DIM不唯一时必须停止，不得静默使用`default`。
- 抖音结算单的`商户主体名称`不是店铺ID，不参与公司归属解析；公司归属只由导入时显式传入的`shop_code`经批次上下文和DIM确定。该字段仍与DIM标准公司名称做严格一致性校验，用于发现人工选错店铺或DIM维护错误。
- ADS使用左连接；缺少映射的数据标记为 `unmapped` / `未匹配公司`，不能静默丢失。
- ADS按照统计日期匹配DIM有效期，DIM变更后必须重新刷新受影响ADS。

标准导入命令：

```powershell
python etl/<platform>/load_<domain>_ods.py --file "<path>" --shop-code <shop_id>
python etl/<platform>/load_<domain>_ods.py --file "<path>" --shop-code <shop_id> --shop-mapping-source robot_selected
```

## 5. 三层设计规则

### DWD

- 表名：`dwd_<platform>_<metric>_<detail_grain>`。
- 一行对应指标所需的最小业务粒度。
- 只选择必要字段、统一类型、解析日期和金额、记录兜底来源。
- 保留订单和售后状态，但不得在本层筛选。
- 保留 ODS ID、批次、文件、原始行号和来源时间，支持追溯。
- 统一通过`common.v_ingest_batch_shop_context`解析店铺，不在指标SQL中按文件名、唯一店铺或默认值猜测。

### DWS

- 表名：`dws_<platform>_<metric>_<summary_grain>`。
- 只实现该平台、该指标已经确认的筛选和公式。
- 输出最接近图表但仍保留平台业务维度的汇总，例如店铺日汇总。
- 记录纳入计算的明细数和来源更新时间，方便验收。

### ADS

- 表名：`ads_<metric>_<chart_grain>`。
- 一张 ADS 服务一个指标卡和一张配套图表。
- 只保留 DataEase 使用的维度、指标和审计字段。
- 同一指标扩展其他平台时，各平台 DWS 使用统一字段 `UNION ALL` 后汇总。
- 不得在 ADS 中编写平台特有清洗、状态判断或金额解析逻辑。

## 6. SQL 与 ETL 顺序

每个指标固定生成三份建表 SQL、三份刷新 SQL和一个 ETL：

```text
建DWD -> 建DWS -> 建ADS -> 刷新DWD -> 刷新DWS -> 刷新ADS
```

建表 SQL 必须包含表注释和所有字段注释。刷新采用事务内全量 `TRUNCATE + INSERT`；任一层失败，三层全部回滚。ETL 执行前检查 ODS 表和必需字段，执行后打印各层行数、日期范围和最终金额。

### SQL目录规则

```text
sql/
├── common/                         通用日志和基础对象
├── dim/                            跨平台维表
├── ads/<metric_code>/              跨平台指标ADS及ADS刷新
├── <platform>/ods/                 平台ODS建表
└── <platform>/<metric_code>/       平台指标DWD、DWS及对应刷新
```

- `sql/` 根目录不允许直接放SQL文件。
- 平台目录统一使用项目平台编码：`douyin`、`tmall`、`jd`、`ks`、`pdd`、`xhs`、`wechat_channels`。
- 同一指标的平台差异文件留在平台目录，共享ADS只能放在 `sql/ads/<metric_code>/`。
- DIM只放 `sql/dim/`，文件导入日志等通用对象只放 `sql/common/`。
- 新文件使用当前项目最大序号继续全局递增，不在每个目录重新从1编号。
- 文件名格式为 `<序号>_<动作或层级>_<平台>_<指标>_<粒度>_postgres.sql`；刷新文件以 `<序号>_refresh_` 开头。
- Python ETL必须列出完整相对路径，不能依赖扫描或按文件名排序执行全部SQL。

## 7. DataEase 配置

1. 在 PostgreSQL 数据源中选择数据库 `mock_coffice`。
2. 数据集只选择指标对应的 ADS 表。
3. 指标卡使用 `SUM(metric_amount)`，并设置金额为两位小数。
4. 趋势图使用统计日期作为横轴、指标金额求和作为纵轴、平台名称作为系列。
5. 公司筛选器使用 `company_name`，店铺筛选器使用 `shop_name`，时间筛选器使用 `stat_date`。
6. 公司、店铺、日期和平台筛选器同时关联所有财务指标ADS数据集的指标卡和趋势图。
7. 核对指标卡总额等于 ADS 总额，趋势点之和等于指标卡。

需要当前指标ADS未包含的渠道、商品等其他维度图时，应单独建立新的 ADS，不能让 DataEase 读取 DWS 临时拼图。

GSV共享数据集`ads.ads_gsv_company_daily`采用公司店铺日粒度，包含`shop_code`和`shop_name`。GSV指标卡、日趋势图均支持店铺筛选，也可使用`shop_name`作为类别制作各店铺GSV对比条形图。

## 8. 抖音 GSV 首版示例

### 指标口径

- 来源：`ods.ods_douyin_order_raw`。
- 统计日期：支付完成日期优先，订单提交日期兜底。
- 订单状态：只保留 `已发货`、`已完成`。
- 排除售后：`待收退货`、`待退货`、`售后待处理`、`退款成功`。
- 其他售后状态保留，空值和 `-` 视为未命中排除条件。
- ODS门店ID为`-`，通过已确认批次3映射到`douyin / 114877104`。

```text
GSV = 订单应付金额 + 优惠总金额 - 商家实际承担优惠金额
```

商家优惠优先取 `商家实际承担优惠金额`；取不到时解析 `商家优惠` 文本末尾数字并取绝对值；仍取不到时使用 `0`。`优惠总金额` 直接使用 ODS 同名字段，不拆分平台或达人优惠。

### 当前链路

```text
ods.ods_douyin_order_raw
  -> dwd.dwd_douyin_gsv_order_detail
  -> dws.dws_douyin_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/douyin/run_douyin_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD子订单数 | 19,469 |
| DWS纳入子订单数 | 13,738 |
| ADS日期范围 | 2026-06-25 至 2026-07-05 |
| ADS公司店铺日记录数 | 11 |
| GSV总额 | 1,066,039.39 |

## 8.1 天猫 GSV

### 指标口径

- 来源：`ods.ods_tmall_order_raw`。
- 目标ODS和DWD最小粒度：一个标准店铺下一个真实子订单一行，以`shop_code + sub_order_no`选择最新导入版本。
- 统计日期：订单付款时间优先，缺失时使用订单创建时间。
- 订单状态：仅排除`交易关闭`，其他状态纳入。
- 商品标题：排除标题包含`购物金`的子订单。
- 售后状态：使用源字段`退款状态`，排除`退款成功`；`退款金额`只保留审计，不参与GSV扣减。
- GSV金额：直接汇总子订单`买家实付金额`。

```text
天猫GSV = SUM(买家实付金额)
WHERE 订单状态 <> '交易关闭'
  AND 退款状态 <> '退款成功'
  AND 商品标题 NOT LIKE '%购物金%'
```

宝贝销售明细报表没有可靠店铺字段，导入时必须显式传入标准店铺`549820088`。DWD只通过批次上下文确定店铺，公司编码和公司名称仍只在ADS按日期通过DIM生成。

### 当前链路

```text
ods.ods_tmall_order_raw
  -> dwd.dwd_tmall_gsv_order_detail
  -> dws.dws_tmall_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/tmall/run_tmall_gsv_etl.py
```

### 当前实际数据库验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS版本行数 / DWD最新子订单数 | 2,196 / 1,098 |
| 交易关闭子订单数 | 238 |
| 非交易关闭购物金子订单数 | 9 |
| 非交易关闭且非购物金的退款成功子订单数 | 1 |
| DWS纳入子订单/主订单数 | 850 / 429 |
| ADS日期范围 | 2026-06-25 至 2026-07-05 |
| ADS天猫公司店铺日记录数 | 11 |
| 天猫GSV总额 | 43,934.37 |
| 未匹配公司记录数 | 0 |

以上数值来自当前规范`ods.ods_tmall_order_raw`。批次41保留原1,098个子订单版本；2026-07-29将字段完全对应并新增`退款状态`、`退款金额`的`天猫订单6.25-7.5销售明细表+退款状态+退款金额.xlsx`作为批次45追加导入。DWD按标准店铺和子订单取最新版本，因此当前1,098行全部来自批次45；旧3,192行仍在归档表中，不参与指标。

## 8.2 京东 GSV

### 指标口径

- 来源：`ods.ods_jd_order_raw`。
- 源表粒度：一行一个订单商品行；订单级金额在多商品行重复。
- DWD粒度：按订单号和最新导入批次聚合为一行一订单，保留全部ODS ID和原始行号数组。
- 金额：使用源字段`应付金额`，每个订单只计算一次。
- 统计日期：`付款确认时间`优先，缺失时使用`下单时间`。
- 订单状态：排除所有以`(删除)`开头的状态，其他状态纳入。

```text
京东GSV = SUM(应付金额)
WHERE 订单状态 NOT LIKE '(删除)%'
```

当前京东订单ODS的履约门店、下单门店和门店名称均为空。批次6已由用户确认映射到`jd / 123572735`，DWD只使用批次上下文，不依赖“京东只有一家店”的假设。

### 当前链路

```text
ods.ods_jd_order_raw
  -> dwd.dwd_jd_gsv_order_detail
  -> dws.dws_jd_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/jd/run_jd_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS商品明细行数 | 35 |
| ODS/DWD唯一订单数 | 34 |
| DWS排除删除状态订单数 | 9 |
| DWS纳入订单数 | 25 |
| ADS日期范围 | 2026-06-25 至 2026-07-05 |
| ADS京东公司店铺日记录数 | 10 |
| 京东GSV总额 | 2,440.91 |
| 未匹配公司记录数 | 0 |

## 8.3 拼多多 GSV

### 指标口径

- 来源：`ods.ods_pdd_order_raw`。
- 最小粒度：一行一个拼多多订单，订单号唯一。
- 统计日期：使用`订单成交时间`，无其他日期兜底。
- 订单状态：只纳入`已发货，待收货`和`已收货`。
- 售后状态：只纳入`无售后`或`售后取消`；当前源文件实际合并枚举为`无售后或售后取消`，刷新逻辑同时兼容拆分值。
- 店铺归属：批次13已确认映射到`pdd / 116694910 / 养颜轻食`；SQL不再硬编码店铺，公司信息仍只从DIM生成。

```text
拼多多GSV = SUM(商家实收金额)
WHERE 订单状态 IN ('已发货，待收货', '已收货')
  AND 售后状态 IN ('无售后', '售后取消', '无售后或售后取消')
```

### 当前链路

```text
ods.ods_pdd_order_raw
  -> dwd.dwd_pdd_gsv_order_detail
  -> dws.dws_pdd_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/pdd/run_pdd_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD订单数 | 1,116 |
| DWS纳入订单数 | 775 |
| DWS排除订单数 | 341 |
| 纳入订单商家实收 | 76,329.90 |
| 纳入订单店铺优惠（仅审计） | 16,621.30 |
| ADS日期范围 | 2026-06-25 至 2026-07-05 |
| ADS拼多多公司店铺日记录数 | 11 |
| 拼多多GSV总额 | 76,329.90 |
| 未匹配公司记录数 | 0 |

## 8.4 快手 GSV

### 指标口径

- 来源：`ods.ods_ks_order_raw`。
- 源表/DWD粒度：一行一个订单商品行，以ODS ID作为稳定明细标识。
- 统计日期：`订单支付时间`优先，缺失时使用`订单创建时间`。
- 订单状态：仅排除`交易关闭`，其他状态纳入。
- 售后状态：排除`退款成功`，其他售后状态和空值纳入。
- 店铺归属：批次9已映射到`ks / 3527127781 / MOCK陌时专卖店`，DWD只通过`common.v_ingest_batch_shop_context`解析店铺。

```text
快手GSV = SUM(实付款)
WHERE 订单状态 <> '交易关闭'
  AND 售后状态 <> '退款成功'
```

### 当前链路

```text
ods.ods_ks_order_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_ks_gsv_order_item_detail
  -> dws.dws_ks_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/ks/run_ks_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD商品行数 | 1,378 |
| ODS/DWD唯一订单数 | 1,376 |
| DWS排除交易关闭商品行 | 634 |
| DWS另排除退款成功商品行 | 15 |
| DWS纳入商品行/订单数 | 729 / 729 |
| ADS日期范围 | 2026-06-01 至 2026-06-30 |
| ADS快手公司店铺日记录数 | 30 |
| 快手GSV总额 | 82,650.00 |
| 未匹配公司记录数 | 0 |

## 8.5 视频号 GSV

### 指标口径

- 来源：`ods.ods_wechat_channels_order_raw`。
- 源表粒度：一行一个订单商品行；订单级实际收款和实际支付金额会在多商品行重复。
- DWD粒度：按订单号和最新导入批次聚合为一行一订单，保留全部ODS ID与原始行号数组。
- 统计日期：`支付时间`优先，缺失时使用`订单下单时间`。
- 订单状态：仅纳入`已完成`。
- 售后状态：订单任一商品行的`商品售后`为`退货退款完成`或`退款完成`时，排除整个订单。
- 店铺归属：批次16已映射到`wechat_channels / wx21c4b9f6b83ef84a / MOCK咖啡店`，DWD只通过统一批次店铺上下文解析店铺。

```text
视频号GSV = SUM(订单实际收款金额)
WHERE 订单状态 = '已完成'
  AND 订单商品售后不包含('退货退款完成', '退款完成')
```

其中订单实际收款金额是订单级字段，每单只计算一次；活动商家补贴保留为审计字段，不参与当前GSV公式。

### 当前链路

```text
ods.ods_wechat_channels_order_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_wechat_channels_gsv_order_detail
  -> dws.dws_wechat_channels_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/wechat_channels/run_wechat_channels_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS商品行数/唯一订单数 | 452 / 444 |
| DWS纳入订单数/源商品行数 | 90 / 95 |
| 纳入订单实际收款 | 18,623.00 |
| 纳入订单活动商家补贴（仅审计） | 0.00 |
| ADS日期范围 | 2026-06-25 至 2026-07-04 |
| ADS视频号公司店铺日记录数 | 9 |
| 视频号GSV总额 | 18,623.00 |
| 未匹配公司记录数 | 0 |

## 8.6 小红书 GSV

### 指标口径

- 来源：`ods.ods_xhs_order_raw`。
- 源表/DWD粒度：一行一个订单SKU商品行，以ODS ID作为稳定明细标识；金额为SKU行级，可直接汇总。
- 统计日期：`支付时间`优先，缺失时使用`订单创建时间`。
- 订单状态：仅纳入`已完成`。
- 售后状态：仅纳入`无售后`。
- 店铺归属：批次31已映射到`xhs / 6674ec57c822d300018cf1 / MOCK旗舰店`，源店铺名称与批次上下文一致。

```text
小红书GSV = SUM(商家应收金额（支付金额）)
WHERE 订单状态 = '已完成'
  AND 售后状态 = '无售后'
```

### 当前链路

```text
ods.ods_xhs_order_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_xhs_gsv_order_item_detail
  -> dws.dws_xhs_gsv_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_gsv_company_daily
  -> DataEase GSV指标卡 + GSV日趋势图
```

刷新命令：

```powershell
python etl/xhs/run_xhs_gsv_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD SKU商品行数 | 12 |
| ODS/DWD唯一订单数 | 9 |
| DWS纳入SKU行数/订单数 | 6 / 4 |
| 纳入商家应收 | 501.70 |
| 纳入店铺优惠 | 0.00 |
| ADS日期范围 | 2026-06-25 至 2026-06-28 |
| ADS小红书公司店铺日记录数 | 2 |
| 小红书GSV总额 | 501.70 |
| 未匹配公司记录数 | 0 |

## 9. 七平台推广费

### 指标公式与来源

```text
抖音推广费 = 千川非赠款消耗
拼多多推广费 = 交易金额
  WHERE 资金类型 = '现金' AND 流水类型 = '支出'
京东推广费 = 京东通支出 + 京东联盟结算金额
  WHERE 京东通交易类型 = '全站营销扣费'
天猫推广费 = 淘宝联盟结算支出费用 + 万相台操作金额
  WHERE 万相台收支类型 = '支出' AND 交易类型 = '扣款'
快手、视频号、小红书推广费 = 0
  仅作为ADS筛选占位，不生成ODS、DWD或DWS业务事实
```

- 抖音日期取千川`日期`，金额只取`非赠款消耗(元)`；不再计入达人佣金或赠款消耗。
- 拼多多日期取`时间`日期部分。
- 京东通和京东联盟日期均取`结算时间`；联盟不增加状态或结算类型筛选。
- 淘宝联盟日期取`日期`，万相台日期严格取`记账时间`，不改用交易日期。
- 金额按支出为正展示；当前无负数，未来来源数据出现冲回时保留负号。
- 用户所称“微信小店”使用项目标准平台`wechat_channels / 视频号`，与其他ADS的公共筛选值保持一致。
- 补零日期取四个真实推广费DWS的去重业务日期；店铺、公司及平台名称取统计日期当日有效DIM版本，金额与纳入明细数为0，来源更新时间为NULL。

### 当前链路

```text
六张平台推广费ODS
  -> 四张平台指标专属DWD
  -> 四张平台店铺日DWS
  + 真实推广费日期脊柱
  + dim.dim_platform_shop_company中的快手、视频号、小红书有效店铺
  -> ads.ads_promotion_expense_company_shop_daily
  -> DataEase 推广费指标卡 + 平台推广费日趋势图
```

一键导入与刷新：

```powershell
python etl/promotion_expense/run_promotion_expense_etl.py `
  --douyin-shop-code 114877104 `
  --pdd-shop-code 345555399 `
  --jd-shop-code 123572735 `
  --tmall-shop-code 549820088
```

文件已成功导入后，仅刷新派生层：

```powershell
python etl/promotion_expense/run_promotion_expense_etl.py --skip-ods-load
```

后续增加店铺时，先用对应平台Loader显式传入新店铺`--shop-code`逐文件导入，再执行上述`--skip-ods-load`命令。不得修改中央脚本默认店铺、按文件名推断店铺或复用其他店铺批次。可用入口如下：

```text
etl/douyin/load_douyin_qianchuan_finance_ods.py
etl/pdd/load_pdd_promotion_expense_ods.py
etl/jd/load_jd_tong_promotion_expense_ods.py
etl/jd/load_jd_union_promotion_expense_ods.py
etl/tmall/load_tmall_taobao_union_promotion_expense_ods.py
etl/tmall/load_tmall_wanxiangtai_promotion_expense_ods.py
```

### DataEase配置

- 数据集：`ads.ads_promotion_expense_company_shop_daily`。
- 指标卡：`SUM(promotion_expense_amount)`，金额保留两位小数。
- 日趋势折线图：横轴`stat_date`，纵轴`SUM(promotion_expense_amount)`，系列`platform_name`。
- 公共筛选器：`company_name`、`shop_name`、`platform_name`、`stat_date`。

### 当前实际数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 抖音ODS/DWD行数 | 52 / 52 |
| 拼多多ODS/DWD行数 | 22 / 22 |
| 京东通/联盟ODS行数与京东DWD行数 | 37 / 5 / 42 |
| 淘宝联盟/万相台ODS行数与天猫DWD行数 | 30 / 29 / 59 |
| 抖音推广费 | 979,335.31 |
| 拼多多推广费 | 1,958.99 |
| 京东通/京东联盟/京东推广费 | 2,347.88 / 38.71 / 2,386.59 |
| 淘宝联盟/万相台/天猫推广费 | 1,291.09 / 47,516.31 / 48,807.40 |
| 快手补零 | 159行 / 3家店 / 0.00 |
| 视频号（微信小店）补零 | 53行 / 1家店 / 0.00 |
| 小红书补零 | 106行 / 2家店 / 0.00 |
| ADS行数与日期范围 | 445 / 2026-06-01至2026-07-23 |
| 推广费总额 | 1,032,488.29 |
| 未匹配公司记录数 | 0 |

抖音52行包含历史30条零消耗千川记录和本次22条有消耗记录；ODS未被修改或删除。完整探查和映射清单见`docs/promotion_expense_ods_exploration.md`。

### GSV与实际推广费月度汇总

为避免 DataEase 在日粒度关联后对 ROI 求和，月度表先分别汇总两张日 ADS，再按现有 GSV 主表做左连接：

```text
ads.ads_gsv_company_daily
  -> 按自然月、平台、公司、店铺汇总
ads.ads_promotion_expense_company_shop_daily
  -> 按自然月、平台、公司、店铺汇总
  -> 以月度GSV为主键集合做LEFT JOIN
  -> ads.ads_gsv_promotion_expense_company_shop_monthly
  -> DataEase月度销售额、实际推广费和ROI表格
```

月度 ADS 粒度为`stat_month + platform_code + company_code + shop_code`。`gsv_amount`和`actual_promotion_expense_amount`是月合计，`roi = gsv_amount / actual_promotion_expense_amount`，推广费为0时 ROI 为 NULL。月度 ROI 单位为“倍”，跨多行汇总时必须使用`SUM(gsv_amount) / SUM(actual_promotion_expense_amount)`，不能求和或平均`roi`。

该表已接入`etl/promotion_expense/run_promotion_expense_etl.py`的派生层刷新。订单 GSV 日 ADS 刷新完成且推广费来源已入库后，执行：

```powershell
python etl/promotion_expense/run_promotion_expense_etl.py --skip-ods-load
```

DataEase 数据集使用`ads.ads_gsv_promotion_expense_company_shop_monthly`；表格维度为`stat_month`、`platform_name`、`company_name`、`shop_name`，指标为`gsv_amount`、`actual_promotion_expense_amount`、`roi`。公共筛选器应使用月份、平台、公司和店铺字段；ROI 指标卡使用上述分子分母比值。

当前数据库月度验收基准：2行，月份为2026-08-01，GSV合计2,143,324.41元，实际推广费合计68,439.25元，汇总ROI为31.317181倍，未匹配公司0行。

## 9.1 抖音结算收入、支出和结算净额

### 指标口径

- 来源：`ods.ods_douyin_settlement_raw`，最小粒度为一行一条结算事件，不按订单号去重。
- 统计日期：使用源字段`结算时间`，无其他日期兜底。
- 筛选：所有结算单类型、结算前退款、结算后退款和支出退回全部纳入，不额外排除。
- 收入金额：使用源字段`收入合计`，退款冲销保留负号。
- 支出金额：对源字段`支出合计`取反，正常支出为正、支出退回为负。
- 结算净额：必须由收入金额减支出金额计算；源字段`结算金额`只用于核验，不作为指标取值。

```text
收入金额 = SUM(收入合计)
支出金额 = SUM(-支出合计)
结算净额 = 收入金额 - 支出金额
核验差额 = 结算净额 - SUM(结算金额) = 0
```

收入类型按用户实付、平台补贴、其他平台补贴、政府补贴平台垫资、达人补贴、抖音支付补贴、抖音月付营销补贴、银行补贴、以旧换新抵扣和平台补贴运费拆分。支出类型按平台服务费、达人佣金、服务商佣金、渠道分成、招商服务费、站外推广费和其他分成拆分。

### 当前链路

```text
ods.ods_douyin_settlement_raw
  -> dwd.dwd_douyin_settlement_income_event_detail
  -> dws.dws_douyin_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_douyin_settlement_raw
  -> dwd.dwd_douyin_settlement_expense_event_detail
  -> dws.dws_douyin_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_douyin_settlement_raw
  -> dwd.dwd_douyin_settlement_net_event_detail
  -> dws.dws_douyin_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

刷新命令：

```powershell
python etl/douyin/run_douyin_settlement_metrics_etl.py
```

### DataEase配置

- 收入指标卡：数据集`ads.ads_settlement_income_company_shop_daily_type`，指标`SUM(income_amount)`。
- 支出指标卡：数据集`ads.ads_settlement_expense_company_shop_daily_type`，指标`SUM(expense_amount)`。
- 结算净额指标卡：数据集`ads.ads_settlement_net_company_shop_daily`，指标`SUM(settlement_net_amount)`。
- 收入类型占比：横向条形图，类别`income_type_name`，指标`SUM(income_amount)`，按金额降序并显示占比标签，过滤汇总金额为0的类型。
- 支出类型占比：横向条形图，类别`expense_type_name`，指标`SUM(expense_amount)`，按金额降序并显示占比标签，过滤汇总金额为0的类型。
- 各平台收入占比：横向条形图，类别`platform_name`，指标`SUM(income_amount)`，按金额降序并显示占比标签。当前已联合抖音和京东收入DWS，其他平台继续按同一ADS字段扩展。
- 各公司收入占比：横向条形图，类别`company_name`，指标`SUM(income_amount)`，按金额降序并显示占比标签。
- 各店铺收入占比：横向条形图，类别`shop_name`，指标`SUM(income_amount)`，按金额降序并显示占比标签。
- 公共筛选器：`company_name`、`stat_date`、`platform_name`、`shop_name`，同时关联三个ADS数据集。

占比图使用条形而不使用饼图/环图，是因为退款冲回可能使单日类型净额为负；条形图能保留负值方向，不取绝对值或隐藏冲回。

### 源文件验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD结算事件数 | 34,654 |
| 日期范围 | 2026-04-01 至 2026-06-30 |
| 收入金额 | 5,167,898.42 |
| 支出金额 | 470,530.86 |
| 计算结算净额 | 4,697,367.56 |
| 源结算金额 | 4,697,367.56 |
| 净额核验差额 | 0.00 |

上述为当前4月至6月源数据的验收基准；数据库ODS行数、批次店铺映射、DIM命中率和双次刷新必须由一键ETL在实际数据库中再验收。

## 9.2 京东结算收入、支出和结算净额

### 指标口径

- 来源：`ods.ods_jd_settlement_raw`，最小粒度为一个最新单据编号一行，重复版本按`ingest_time`和ODS `id`取最新。
- 统计日期：使用源字段`账单日期`，支持`YYYYMMDD`和`YYYY-MM-DD`，无其他日期兜底。
- 筛选：订单、非销售单、取消退款单和售后服务单全部纳入，不额外排除。
- 收入金额：`收支方向 = '收入'`时取源`金额`，其他方向为0。
- 支出金额：`收支方向 = '支出'`时对源负数`金额`取反，其他方向为0。
- 结算净额：由收入金额减支出金额计算，并与源带符号`金额`汇总核验。京东源文件没有独立的结算金额字段。
- 一致性校验：`收入`必须对应`应收`且金额为正；`支出`必须对应`应付`且金额为负；币种必须为CNY。

```text
收入金额 = SUM(CASE WHEN 收支方向 = '收入' THEN 金额 ELSE 0 END)
支出金额 = SUM(CASE WHEN 收支方向 = '支出' THEN -金额 ELSE 0 END)
结算净额 = 收入金额 - 支出金额
核验差额 = 结算净额 - SUM(带符号金额) = 0
```

收入和支出类型均使用京东源字段`费用项`，当前包括货款、佣金、交易服务费、运费保险服务费、商品保险服务费、随单送的京豆、综合违约金和代收配送费。

### 当前链路

```text
ods.ods_jd_settlement_raw
  -> dwd.dwd_jd_settlement_income_document_detail
  -> dws.dws_jd_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_jd_settlement_raw
  -> dwd.dwd_jd_settlement_expense_document_detail
  -> dws.dws_jd_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_jd_settlement_raw
  -> dwd.dwd_jd_settlement_net_document_detail
  -> dws.dws_jd_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS与七个平台结算指标共用，通过各平台DWS `UNION ALL`后再关联DIM，DataEase无需切换数据集。平台结算ETL完成后统一执行`settlement_shared_ads`收口任务（脚本：`etl/platform_finance/run_settlement_shared_ads_etl.py`），由任务依赖保证共享ADS在已选平台DWS全部完成后只刷新一次；单个平台脚本仍保留独立刷新能力以兼容历史手工命令。

刷新命令：

```powershell
python etl/jd/run_jd_settlement_metrics_etl.py
```

### 实际数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| ODS行数/唯一单据数 | 975 / 975 |
| DWD收入/支出/净额行数 | 975 / 975 / 975 |
| DWS收入类型/支出类型/净额日行数 | 44 / 155 / 31 |
| 纳入收入/支出单据数 | 144 / 831 |
| ADS日期范围 | 2026-05-01 至 2026-05-31 |
| 收入金额 | 18,566.44 |
| 支出金额 | 1,802.12 |
| 计算结算净额 | 16,764.32 |
| 源带符号金额合计 | 16,764.32 |
| 净额核验差额 | 0.00 |
| ADS未匹配公司行数 | 0 |

当前批次5全部映射到`jd / 123572735 / MOCK饮品旗舰店`，并在指标日期范围内命中`company_002 / 墨客咖时（南京）生物科技有限公司`。

## 9.3 快手结算收入、支出和结算净额

### 指标口径

- 来源：`ods.ods_ks_settlement_raw`，最小粒度为一条ODS结算记录，以ODS `id`作为稳定事件主键；当前订单号亦唯一。
- 统计日期：使用源字段`实际结算时间`，无其他日期兜底。
- 筛选：全部佣金模式、结算规则及退款记录纳入，不额外排除。
- 收入金额：使用源字段`合计收入(元)`，并以订单实付、政府补贴、支付营销补贴、平台补贴、商家补贴和达人补贴之和逐行核验。
- 支出金额：使用源字段`合计支出(元)`，并以订单退款、技术服务费、预售增收技术服务费、达人佣金、团长佣金、快赚客佣金、服务商佣金和其他收费之和逐行核验。
- `支付营销回退（元）`仅保留核对。当前唯一非零记录未计入平台`合计支出(元)`，也未影响源实际结算金额，因此不作为支出类型。
- 结算净额：必须由收入金额减支出金额计算；源字段`实际结算金额(元)`只用于核验，不作为指标取值。

```text
收入金额 = SUM(合计收入(元))
支出金额 = SUM(合计支出(元))
结算净额 = 收入金额 - 支出金额
核验差额 = 结算净额 - SUM(实际结算金额(元))
```

当前源数据有2条记录的`实际结算金额(元)`不满足收入减支出公式，合计核验差额为`-152.32`。指标继续使用计算净额，DWD、DWS和ADS保留源金额及核验差额用于追溯，不通过修改ODS或取源结算金额修正结果。

### 当前链路

```text
ods.ods_ks_settlement_raw
  -> dwd.dwd_ks_settlement_income_event_detail
  -> dws.dws_ks_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_ks_settlement_raw
  -> dwd.dwd_ks_settlement_expense_event_detail
  -> dws.dws_ks_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_ks_settlement_raw
  -> dwd.dwd_ks_settlement_net_event_detail
  -> dws.dws_ks_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS与抖音、京东结算指标共用，通过三平台DWS `UNION ALL`后再关联DIM。DataEase继续使用三张指标卡、收入类型占比、支出类型占比、各平台收入占比、各公司收入占比和各店铺收入占比，以及公司、日期、平台、店铺公共筛选器。

刷新命令：

```powershell
python etl/ks/run_ks_settlement_metrics_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD结算事件数 | 1,437 |
| ODS唯一订单数 | 1,437 |
| 日期范围 | 2026-05-01 至 2026-05-31 |
| 收入金额 | 142,597.83 |
| 支出金额 | 49,653.14 |
| 计算结算净额 | 92,944.69 |
| 源实际结算金额 | 93,097.01 |
| 源金额差异明细数 | 2 |
| 净额核验差额 | -152.32 |
| 未匹配公司记录数 | 0 |

当前批次8映射到`ks / 3527127781 / MOCK陌时专卖店`，指标日期范围内公司归属为`company_010 / 南京陌时食品科技有限公司`。

## 9.4 拼多多结算收入、支出和结算净额

### 指标口径

- 来源：`ods.ods_pdd_settlement_raw`，最小粒度为一条账务流水，以ODS `id`作为稳定事件主键；商户订单号、发生时间、账务类型、金额和业务描述组成的当前业务事件亦唯一。
- 统计日期：使用源字段`发生时间`，无其他日期兜底。
- 筛选：交易收入、退款、优惠券结算、技术服务费、提现、转账等全部账务类型均纳入，不额外排除；无订单号流水同样纳入。
- 收入金额：使用源字段`收入金额（+元）`，源值均为非负数。
- 支出金额：对源字段`支出金额（-元）`取反，正常支出由负数标准化为正数。
- 结算净额：由收入金额减支出金额计算。拼多多没有独立结算金额字段，使用源收入加源负向支出的带符号流水合计进行核验。
- 每条源流水仅收入或支出一侧非零，不存在两侧同时非零或同时为0。

```text
收入金额 = SUM(收入金额（+元）)
支出金额 = SUM(-支出金额（-元）)
结算净额 = 收入金额 - 支出金额
源带符号流水 = SUM(收入金额（+元） + 支出金额（-元）)
核验差额 = 结算净额 - 源带符号流水 = 0
```

收入类型和支出类型均使用源`账务类型`，当前共11类。提现184,000元和转账83,210元按用户确认纳入支出，不按财务损益语义另行排除。

### 当前链路

```text
ods.ods_pdd_settlement_raw
  -> dwd.dwd_pdd_settlement_income_event_detail
  -> dws.dws_pdd_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_pdd_settlement_raw
  -> dwd.dwd_pdd_settlement_expense_event_detail
  -> dws.dws_pdd_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_pdd_settlement_raw
  -> dwd.dwd_pdd_settlement_net_event_detail
  -> dws.dws_pdd_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS与抖音、京东、快手结算指标共用，通过四个平台DWS `UNION ALL`后再关联DIM。DataEase继续使用三张指标卡、收入类型占比、支出类型占比、各平台收入占比、各公司收入占比和各店铺收入占比，以及公司、日期、平台、店铺公共筛选器。

刷新命令：

```powershell
python etl/pdd/run_pdd_settlement_metrics_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD账务事件数 | 21,704 |
| ODS唯一订单数 | 4,614 |
| 无订单号流水数 | 21 |
| 日期范围 | 2026-05-01 至 2026-05-31 |
| 收入金额 | 426,419.48 |
| 支出金额 | 384,886.02 |
| 计算结算净额 | 41,533.46 |
| 源带符号流水合计 | 41,533.46 |
| 净额核验差额 | 0.00 |
| 未匹配公司记录数 | 0 |

当前批次11映射到`pdd / 116694910 / 养颜轻食`，指标日期范围内公司归属为`company_001 / 津果日记生物科技（南京）有限公司`。

## 9.5 视频号结算收入、支出和结算净额

### 指标口径

- 来源：`ods.ods_wechat_channels_settlement_raw`，最小粒度为一条动账流水，以ODS `id`作为稳定事件主键；当前流水单号全部唯一。
- 来源范围：同时纳入批次14的`视频号-结算.xlsx`和批次15的`视频号6.22-7.2.xlsx`，不按文件名称排除资金流水。
- 统计日期：使用源字段`记账时间`，无其他日期兜底。
- 筛选：订单支付、订单退款、达人佣金、技术服务费、运费险、提现、极速退款垫资等全部动账类型纳入，不额外排除。
- 收入金额：`收支类型='收入'`时取源`收支金额`，其他方向为0。
- 支出金额：`收支类型='支出'`时取源`收支金额`，其他方向为0。源金额本身为正数，不需要取反。
- 结算净额：由收入金额减支出金额计算。视频号没有独立结算金额字段，按源收支方向还原带符号流水用于核验。
- 源金额全部大于0，收支类型仅有收入和支出两个枚举。

```text
收入金额 = SUM(CASE WHEN 收支类型='收入' THEN 收支金额 ELSE 0 END)
支出金额 = SUM(CASE WHEN 收支类型='支出' THEN 收支金额 ELSE 0 END)
结算净额 = 收入金额 - 支出金额
源带符号流水 = SUM(CASE WHEN 收支类型='收入' THEN 收支金额 ELSE -收支金额 END)
核验差额 = 结算净额 - 源带符号流水 = 0
```

收入类型和支出类型均使用源`动帐类型`。提现57,000元按用户确认纳入支出，不按财务损益语义另行排除。

### 当前链路

```text
ods.ods_wechat_channels_settlement_raw
  -> dwd.dwd_wechat_channels_settlement_income_event_detail
  -> dws.dws_wechat_channels_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_wechat_channels_settlement_raw
  -> dwd.dwd_wechat_channels_settlement_expense_event_detail
  -> dws.dws_wechat_channels_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_wechat_channels_settlement_raw
  -> dwd.dwd_wechat_channels_settlement_net_event_detail
  -> dws.dws_wechat_channels_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS与抖音、京东、快手、拼多多结算指标共用，通过五个平台DWS `UNION ALL`后再关联DIM。DataEase继续使用三张指标卡、收入类型占比、支出类型占比、各平台收入占比、各公司收入占比和各店铺收入占比，以及公司、日期、平台、店铺公共筛选器。

刷新命令：

```powershell
python etl/wechat_channels/run_wechat_channels_settlement_metrics_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| ODS/DWD动账事件数 | 4,206 |
| ODS批次数 | 2 |
| 收入/支出事件数 | 1,296 / 2,910 |
| 日期范围 | 2026-05-01 至 2026-07-02 |
| 收入金额 | 185,825.69 |
| 支出金额 | 126,591.73 |
| 计算结算净额 | 59,233.96 |
| 源带符号流水合计 | 59,233.96 |
| 净额核验差额 | 0.00 |
| 未匹配公司记录数 | 0 |

批次14和15均映射到`wechat_channels / wx21c4b9f6b83ef84a / MOCK咖啡店`，指标日期范围内公司归属为`company_012 / 墨客每刻（南京）食品科技有限公司`。

## 9.6 天猫结算收入、支出和结算净额

### 指标口径

- 收入来源：`ods.ods_tmall_settlement_income_raw`，最小粒度为一条收入文件记录，以ODS `id`作为稳定事件主键；同一订单、业务流水可以有多条商品明细，不按订单去重。
- 支出来源：`ods.ods_tmall_settlement_expense_raw`，最小粒度为一条服务费记录，以ODS `id`作为稳定事件主键；当前8个批次分别对应8类支出项目。
- 统计日期：收入和支出统一使用源字段`账期`，按`YYYYMMDD`解析为日期，无其他日期兜底。
- 收入金额：直接使用`订单实际金额（元）`，用户确认不减`退款金额（元）`；退款金额仅保留审计。
- 支出金额：优先使用源`扣费金额`，缺失时使用`支出金额（元）`，再缺失时使用`扣费金额（元）-退款金额`；退款冲回保留负号。
- 筛选：当前全部收入记录和8类支出项目均进入明细层，不按订单或业务流水去重；金额为0的记录保留在DWD和结算净额事件数中，但不生成金额为0的收支类型汇总行。
- 结算净额：必须由收入金额减支出金额计算。天猫两张结算ODS均没有独立结算金额字段，按收入表正向金额和支出表负向金额组成带符号源金额用于公式核对。

```text
收入金额 = SUM(订单实际金额（元）)
支出金额 = SUM(净扣费金额，退款冲回保留负号)
结算净额 = 收入金额 - 支出金额
源带符号组成金额 = SUM(收入表订单实际金额) - SUM(支出表净扣费金额)
核验差额 = 结算净额 - 源带符号组成金额 = 0
```

收入类型使用源`账单大类`，当前仅`货款收入`。支出类型使用源`支出项目`，当前包括先用后付服务费、光合平台软件服务费、品牌新享首单拉新、基础软件服务费、淘金币软件服务费、淘宝内容推广服务费、天猫佣金和限时红包代商家垫付扣回。

### 当前链路

```text
ods.ods_tmall_settlement_income_raw
  -> dwd.dwd_tmall_settlement_income_event_detail
  -> dws.dws_tmall_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_tmall_settlement_expense_raw
  -> dwd.dwd_tmall_settlement_expense_event_detail
  -> dws.dws_tmall_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_tmall_settlement_income_raw + ods.ods_tmall_settlement_expense_raw
  -> dwd.dwd_tmall_settlement_net_event_detail
  -> dws.dws_tmall_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS继续与抖音、京东、快手、拼多多、视频号和小红书结算指标共用。DataEase沿用三张指标卡、收入类型占比、支出类型占比、各平台收入占比、各公司收入占比和各店铺收入占比，以及公司、日期、平台、店铺公共筛选器。

天猫自资金明细可用月份起增加专属资金来源链路：

```text
ods.ods_tmall_aggregate_fund_raw + ods.ods_tmall_alipay_fund_raw
  -> dwd.dwd_tmall_settlement_fund_event_detail
  -> dws.dws_tmall_settlement_fund_income_shop_daily_type
  -> dws.dws_tmall_settlement_fund_expense_shop_daily_type
  -> dws.dws_tmall_settlement_fund_net_shop_daily
  -> dws.dws_tmall_settlement_*（同月资金覆盖旧结算DWS）
  -> ads.ads_settlement_*（七平台共享）
```

资金DWD完整保留两张资金单的所有记录；DWS仅把聚合账户`交易收款`、支付宝`交易付款`作为收入，把备注命中的平台费用作为支出。交易退款只保留审计，不从收入扣减；提现、普通转账和未识别资金行不进入结算金额。资金没有独立“结算金额”字段，结算净额仍严格按`收入金额-支出金额`计算，带符号资金合计只作核验值。若某个月同时存在旧结算单和资金单，该月以资金DWS为准；没有资金单的历史月份继续保留旧结算DWS，避免重复计算。

刷新命令：

```powershell
.\.venv\Scripts\python.exe etl/tmall/run_tmall_settlement_metrics_etl.py
.\.venv\Scripts\python.exe etl/tmall/run_tmall_settlement_from_funds_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| 收入ODS/DWD事件数 | 2,892 |
| 支出ODS/DWD事件数 | 7,302 |
| 结算净额DWD事件数 | 10,194 |
| 收入/支出批次数 | 1 / 8 |
| 收入非零/支出非零事件数 | 2,110 / 6,940 |
| 日期范围 | 2026-05-01 至 2026-05-31 |
| 收入金额（不减退款） | 219,965.24 |
| 退款审计金额（不参与扣减） | 2,489.19 |
| 支出净额 | 22,689.92 |
| 计算结算净额 | 197,275.32 |
| 两表带符号组成金额 | 197,275.32 |
| 净额组成核验差额 | 0.00 |
| 未匹配公司记录数 | 0 |

收入批次21以及支出批次17至20、22至25均映射到`tmall / 549820088 / MOCK旗舰店`，指标日期范围内公司归属为`company_002 / 墨客咖时（南京）生物科技有限公司`。

资金来源迁移后的当前验收（现有资金批次48、49，仅覆盖2026年6月）如下：

| 验收项 | 实际值 |
| --- | ---: |
| 聚合账户/支付宝资金行数 | 775 / 15,208 |
| 资金DWD完整事件数 | 15,983 |
| 资金DWS收入（交易收款/交易付款） | 264,960.54 |
| 资金DWS支出（已识别平台费用） | 31,341.61 |
| 资金DWS计算结算净额 | 233,618.93 |
| 旧结算历史保留收入/支出/净额（5月） | 219,965.24 / 22,689.92 / 197,275.32 |
| 天猫合并DWS日期范围 | 2026-05-01 至 2026-06-30 |
| 天猫合并DWS收入/支出/净额 | 484,925.78 / 54,031.53 / 430,894.25 |
| 资金结算净额核验差额 | 0.00 |
| 未匹配公司记录数（收入/支出/净额） | 0 / 0 / 0 |

资金来源费用分类包含现有结算单八类项目以及资金单中可明确识别的淘宝客佣金、返点积分、消费者体验、商家集运、淘宝联盟、保证金履约险和小额打款等场景；提现、普通转账、交易退款和未识别备注保留在资金DWD但不计入结算收入/支出。后续新增月份应以同月旧结算单或银行对账做勾稽后再确认分类是否需要扩展。

## 9.7 小红书结算收入、支出和结算净额

### 指标口径

- 收入来源：`ods.ods_xhs_settlement_income_raw`（订单结算）以及`ods.ods_xhs_settlement_expense_raw`中的`申诉调账`（平台补偿收入）；订单结算以ODS `id`作为稳定事件主键，申诉调账收入使用其他服务款ODS主键的负值作为DWD技术主键，所有收入事件保留源金额符号。
- 支出来源：`ods.ods_xhs_settlement_expense_raw`（其他服务款），排除收入型`申诉调账`；费用类其他服务款以ODS `id`作为稳定事件主键，正负动账均保留。
- 统计日期：两张源表统一使用`结算时间`的日期部分，不使用其他时间字段兜底。
- 收入金额：订单结算和`申诉调账`均直接汇总源`动账金额`；结算入账、平台补偿通常为正收入，退款或收入冲回为负收入。
- 支出金额：费用类其他服务款将带符号`动账金额`取反；平台扣费形成正费用，费用退款或补回形成负费用冲减。`申诉调账`不计费用。
- 筛选：只按业务类型执行“申诉调账收入/费用类其他服务款”分流，不删除ODS原始记录。订单结算的金额组成字段仅用于审计，指标以源`动账金额`为准。
- 结算净额：必须由收入金额减支出金额计算，再用两张源表带符号`动账金额`合计核验，不能直接取核验金额作为指标。

```text
收入金额 = SUM(订单结算.动账金额) + SUM(其他服务款 WHERE 业务款项='申诉调账'.动账金额)
支出费用净额 = SUM(-其他服务款 WHERE 业务款项<>'申诉调账'.动账金额)
结算净额 = 收入金额 - 支出费用净额
源带符号动账金额 = SUM(订单结算.动账金额) + SUM(其他服务款.动账金额)
核验差额 = 结算净额 - 源带符号动账金额 = 0
```

收入类型使用源`交易类型`，并增加其他服务款中的`申诉调账收入`；其他服务款费用类型使用源`业务款项`并排除`申诉调账`，同一费用类型允许出现正负动账。`申诉调账`的正数是平台补偿应税收入，负数按收入冲回保留，不转为费用。收入组成字段按源导出口径重算时有1条记录存在0.01元四舍五入差异，因此仅用于审计，不替代源动账金额。

### 当前链路

```text
ods.ods_xhs_settlement_income_raw
  -> dwd.dwd_xhs_settlement_income_event_detail
  -> dws.dws_xhs_settlement_income_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_income_company_shop_daily_type

ods.ods_xhs_settlement_expense_raw
  -> dwd.dwd_xhs_settlement_expense_event_detail
  -> dws.dws_xhs_settlement_expense_shop_daily_type
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_expense_company_shop_daily_type

ods.ods_xhs_settlement_income_raw + ods.ods_xhs_settlement_expense_raw
  -> dwd.dwd_xhs_settlement_net_event_detail
  -> dws.dws_xhs_settlement_net_shop_daily
  -> dim.dim_platform_shop_company
  -> ads.ads_settlement_net_company_shop_daily
```

三张ADS与抖音、京东、快手、拼多多、视频号和天猫结算指标共用。DataEase沿用三张指标卡、收入类型占比、支出类型占比、各平台收入占比、各公司收入占比、各店铺收入占比，以及公司、日期、平台、店铺公共筛选器。

刷新命令：

```powershell
python etl/xhs/run_xhs_settlement_metrics_etl.py
```

### 当前验收基准

| 验收项 | 预期值 |
| --- | ---: |
| 收入ODS/DWD事件数 | 287 |
| 支出ODS/DWD事件数 | 171 |
| 结算净额DWD事件数 | 458 |
| 收入/支出批次数 | 1 / 1 |
| 日期范围 | 2026-05-01 至 2026-05-31 |
| 结算入账 | 20,462.97 |
| 退款（负收入） | -5,363.19 |
| 收入金额 | 15,099.78 |
| 支出金额 | 120.18 |
| 计算结算净额 | 14,979.60 |
| 两表带符号动账金额 | 14,979.60 |
| 净额核验差额 | 0.00 |
| 未匹配公司记录数 | 0 |

收入批次29和支出批次30均映射到`xhs / 6674ec57c822d300018cf1eb / MOCK旗舰店`，指标日期范围内公司归属为`company_002 / 墨客咖时（南京）生物科技有限公司`。

## 9.8 七平台运营成交GMV、退款、订单和件单价

### 指标口径

- 来源：抖音、视频号、京东、快手、小红书、拼多多和天猫七张订单ODS；抖音和天猫DWD以最新子订单为最小粒度，其余平台以ODS订单商品行为最小粒度。
- 成交日期：抖音取`订单提交时间`、视频号取`订单下单时间`、京东取`下单时间`、快手、小红书和天猫取`订单创建时间`、拼多多取`订单成交时间`。拼多多成交时间为空时，从订单号前六位`YYMMDD`解析自然日。
- 刷单排除：原六个平台在订单任一商品行的平台应付或实付金额`>= 2000`时排除整单；天猫按主订单所有子订单`买家应付货款`合计`> 2000`排除整单，等于2,000元保留。DWD保留原始行，排除逻辑只在平台DWS执行。
- GMV：原六个平台对非刷单订单商品行直接取已确认的商品原价字段；天猫直接取子订单`买家应付货款`。均不乘商品数量、不扣商家补贴。
- 状态范围：GMV不筛选订单状态或售后状态，两个字段在DWD/DWS中保留用于审计。
- 总退款：仅使用平台订单状态，不使用售后状态。抖音为`已关闭`、视频号为`已取消`、京东为状态以`(删除)`开头、快手和天猫为`交易关闭`、拼多多为`已取消`或状态包含`退款成功`；小红书当前没有已关闭等价状态，退款为0。
- 退款率：`总退款 / GMV`。ADS同时保留分子、分母和日退款率，跨日期筛选按汇总分子除以汇总分母计算。
- 成交总订单数：非刷单范围内按订单号在成交日期、平台、公司和店铺内去重；当前订单不跨成交日期，日订单数可安全加总。
- 成交总人数：源收件人、手机号和地址已统一脱敏且无买家ID，按用户确认不展示、不加工该字段。
- 成交件数：仅正GMV的非刷单商品行取商品数量，零GMV赠品记0。天猫标题等于`MOCK推荐官`或包含`赠品勿拍`的辅助行，其GMV、退款和件数归零，但所属有效主订单仍参与订单数去重。
- 成交件单价：`GMV / 非零GMV成交件数`。ADS同时保留GMV、件数和日件单价，跨日期筛选按汇总GMV除以汇总件数计算。
- 数值清洗：各平台数量、商品行原价和刷单判断金额清理首尾空白、千分位逗号和币种符号后严格解析。

```text
GMV = SUM(平台确认商品行金额)
WHERE 主订单不属于平台口径识别的刷单主订单
且不筛选订单状态、售后状态

总退款 = SUM(GMV)
WHERE 订单状态命中平台已确认的关闭/取消状态

退款率 = 总退款 / GMV
成交总订单数 = COUNT(DISTINCT 主订单编号)
成交件单价 = GMV / SUM(CASE WHEN 商品单价 > 0 THEN 商品数量 ELSE 0 END)
成交日期 = DATE(平台确认的下单/创建/成交时间)
```

### 当前链路

```text
七张平台订单ODS
  -> common.v_ingest_batch_shop_context
  -> 七张平台运营成交订单商品行DWD
  -> 七张平台运营成交订单商品行DWS
  -> dim.dim_platform_shop_company
  -> ads.ads_operating_sales_company_shop_daily
  -> ads.ads_operating_sales_traffic_company_shop_daily

data/产品分类/产品编码.xlsx
  -> dim.dim_influencer_product_category
  -> dim.dim_influencer_product（稳定product_id + 公司商品编码）
  -> dim.dim_company_product_code_mapping（全公司编码表达/别名规则）

七张平台运营成交订单商品行DWD
  + dim.dim_company_product_code_mapping
  -> 七张平台运营成交产品分摊DWS
  -> dim.dim_platform_shop_company
  -> ads.ads_operating_sales_product_company_shop_daily
  -> DataEase 5张指标卡 + 平台GMV占比 + 流量结构GMV占比 + 公司统一产品GMV占比
```

第一张ADS采用公司店铺日粒度，服务GMV、总退款、退款率、成交订单数、成交件单价指标卡以及各平台GMV占比。当前目标代码已通过各平台独立DWD/DWS接入抖音、视频号、京东、快手、小红书、拼多多和天猫，并按统一字段`UNION ALL`进入三张共享ADS。

流量ADS采用公司店铺日、流量体裁、流量渠道粒度，DataEase使用`traffic_content_type -> traffic_channel`两级下钻。视频号使用`带货方式 -> 带货账号类型`，京东使用`订单来源 -> 订单渠道`，快手使用`订单载体 -> 渠道`，小红书、拼多多和天猫如实写入`未提供 -> 未提供`；空值、横杠和暂无来源也统一为`未提供`。产品ADS不再使用平台商品ID或选购商品链接名称，采用公司店铺日、一级分类、二级分类、公司统一产品名称粒度，DataEase使用`large_product_category -> product_category_l2 -> product_name`三级下钻。

公司商品使用稳定`product_id`作为系统身份，统一格式为`PRD-CODE-`加16位大写十六进制；使用独立`company_product_code`作为公司业务编码。编码映射表维护全公司的编码表达规则，不再以平台或店铺作为商品身份：尾部正整数解析为数量，前缀数字缩写通过公司级别名解析，例如`M-MGNT-1/-2/-10`均归属`M-MGNT`，`2MG`通过`MG -> M-MGNT`识别为数量2。平台和店铺只在订单事实、统计和观察工作台中保留。

组合装先按`+`拆出全部原始组件；若仓库手工编码漏写分隔符，则先用`dim.dim_company_product_code_normalization_rule`把异常组件改写为一个或多个标准组件，再逐项解析商品和数量。DWS同时保留`raw_merchant_code_component`和`normalization_rule_id`审计。规格或商品名出现“赠”时，赠字后的组件仍写入DWS、正常映射并保留审计字段，但`paid_quantity=0`、`allocated_gmv_amount=0`；GMV分母仅使用付费组件的`paid_quantity`。同一编码组件同时包含付费和赠品数量时分别写入`paid_quantity`和`gift_quantity`。最后一个付费组件吸收分币差。天猫购物金`A1/B2/C3`、预定有价券和红包继续作为特殊商品识别，本阶段不新增红包或优惠券扣减算法。未映射编码按去数量后的编码族保留，不静默丢失GMV，也不再产生`partial`状态。

刷新命令：

```powershell
.\.venv\Scripts\python.exe -m etl.operating_sales.run_operating_sales_etl
```

一键ETL默认直接使用数据库中的产品编码映射DIM，再在一个事务中刷新七个平台和三张ADS，不依赖部署镜像内的`data/产品分类/产品编码.xlsx`。如需从Excel显式回填或维护映射，可传入`--product-mapping-file`（或设置`PRODUCT_MAPPING_FILE`）；该文件只属于维护工具，不是指标刷新运行时的必需输入。当前新格式天猫单文件隔离验收可附加对应固定基准参数；正式历史迁移后不再使用固定基准参数。仅需单独维护产品编码映射时可运行：

```powershell
.\.venv\Scripts\python.exe -m etl.common.load_company_product_code_mapping --file "data/产品分类/产品编码.xlsx"
```

公司商品身份、数量族、简写别名、赠品零GMV和统一映射状态可执行只读回归验收：

```powershell
.\.venv\Scripts\python.exe -m etl.operating_sales.validate_product_identity
```

### DataEase配置

- 总成交额GMV：数据集`ads.ads_operating_sales_company_shop_daily`，指标`SUM(gmv_amount)`。
- 总退款：同一数据集，指标`SUM(refund_amount)`。
- 退款率：同一数据集，计算字段`SUM(refund_amount) / SUM(gmv_amount)`，格式为百分比。
- 成交总订单数：同一数据集，指标`SUM(transaction_order_count)`。
- 成交件单价：同一数据集，计算字段`SUM(gmv_amount) / SUM(sold_unit_count)`，格式为金额。
- 各平台GMV占比：同一数据集，类别`platform_name`，指标`SUM(gmv_amount)`，降序条形图并显示占比。
- 流量结构及GMV占比：数据集`ads.ads_operating_sales_traffic_company_shop_daily`，一级`traffic_content_type`、二级`traffic_channel`，指标`SUM(gmv_amount)`，使用支持层级下钻的堆叠条形图或矩形树图。
- 各产品GMV占比：数据集`ads.ads_operating_sales_product_company_shop_daily`，稳定键为`product_id`，展示层级`large_product_category -> product_category_l2 -> company_product_code -> product_name`，指标`SUM(gmv_amount)`，降序横向条形图或矩形树图并显示占比。
- 公共筛选器：`company_name`、`stat_date`、`platform_name`、`shop_name`，同时关联三张ADS数据集。

### 当前实际数据库验收基准

| 平台 | DWD行 | DWS行 | 成交订单 | GMV | 退款 | 成交件数 | 产品组件 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 抖音 | 86,736 | 86,106 | 54,024 | 6,753,683.62 | 2,360,522.48 | 81,381 | 66,116 |
| 视频号 | 600 | 600 | 597 | 101,511.10 | 34,770.40 | 623 | 867 |
| 京东 | 177 | 177 | 168 | 21,505.80 | 2,742.80 | 181 | 249 |
| 快手 | 12 | 12 | 12 | 1,127.00 | 177.00 | 12 | 12 |
| 小红书 | 75 | 75 | 74 | 11,801.10 | 0.00 | 76 | 89 |
| 拼多多 | 4,456 | 4,456 | 4,456 | 600,389.60 | 243,337.70 | 4,498 | 6,424 |
| 天猫 | 5,702 | 5,702 | 3,178 | 301,887.90 | 54,565.61 | 3,186 | 4,740 |
| 合计 | 97,758 | 97,128 | 62,509 | 7,791,906.12 | 2,696,115.99 | 89,957 | 78,497 |

| 七平台ADS验收项 | 实际值 |
| --- | ---: |
| 指标卡/流量/产品ADS行数 | 442 / 3,615 / 3,880 |
| 日期范围 | 2026-08-01 至 2026-09-08 |
| 退款率 | 34.60% |
| 成交件单价 | 86.62 |
| 三张ADS未匹配公司行数 | 0 / 0 / 0 |
| 三张ADS最终粒度双向差异 | 0 / 0 / 0 |
| 七平台未映射编码组件 | 178次，归并为3个待处理编码族/异常表达 |
| 连续两次刷新结果 | 完全一致 |

以上七平台基准为当前实际数据库结果，天猫规范ODS已正式切换为新格式单文件。商品品类配置后台保存后，会按已存在的七个平台DWD重新刷新各平台产品分摊DWS和共享产品ADS，因此一级分类、二级分类、产品名或商家编码修改会立即反映在产品GMV占比中。

2026-09-20补充验收：七平台商品ADS总GMV仍为`7,791,906.12`元，与订单商品DWS一致；产品组件DWS保留付费与赠品共98,863行，其中纯赠品组件20,366行，赠品分摊GMV为0。`M-CHK`已自动归属黑咖啡，京东异常组件`M-RYKK-1M-NXSY-XD-1`通过公司级修正规则拆为两个已映射赠品组件，当前只剩天猫字面值`UNMAPPED`一个未映射编码族，工作台不产生`partial`。

## 9.9 多平台达人运营业绩、商务归属与月度目标

### 指标口径

- 来源：抖音、视频号、快手、天猫、京东、小红书和拼多多订单ODS；每个平台使用达人指标专属DWD/DWS，不复用其他指标层。
- 统计日期：抖音取`订单提交时间`，视频号取`订单下单时间`，快手和天猫取`订单创建时间`，京东取`下单时间`，小红书取`订单创建时间`，拼多多取`订单成交时间`且缺失时用订单号前六位解析自然日。查看月度时在DataEase手动选择完整自然月；Top5、10万+和商务目标按自然月派生。
- 达人范围：抖音`流量来源='精选联盟'`；视频号使用有效`带货ID`；快手使用有效`CPS达人ID`；天猫商品标题命中`【xxx专属】`或`【xxx推荐】`。京东、小红书和拼多多当前无达人，按标准店铺和订单自然日生成零值占位行。
- 刷单排除：有达人平台按主订单排除订单应付或实付金额大于2,000元的整单；等于2,000元保留。视频号使用`订单实际支付金额`、快手使用`实付款`、天猫使用`买家应付货款`。
- 达人GMV：抖音和快手取每行`商品单价`，视频号取每行`商品价格(单件)`，均不乘数量；天猫直接取`买家应付货款`。GMV不按订单状态或售后状态筛选。
- 达人退款：抖音取`已关闭`、视频号取`已取消`、快手和天猫取`交易关闭`订单的同口径GMV金额，不直接使用售后状态或源退款金额。
- 达人退款率：`达人退款 / 达人GMV`，跨日期必须汇总分子、分母后重算。
- 活跃达人：筛选日期内实际产生达人GMV的`平台+达人ID`去重数；零值占位ID不计入。抖音达人ID为`0`时统一作为一个名为`其他`的达人。
- 天猫达人身份：`【加购！胡可推荐】`和`【胡可推荐】`统一规范为“胡可”，再按名称从`dim.dim_influencer_business_assignment_monthly`唯一取得稳定ID。当前配置为蜜蜂欢乐社`1111111`、蜜蜂心愿社`2222222`、胡可`3333333`、芳芳`4444444`。
- 商务归属：按`平台+达人ID+生效月`保留版本；最新的、不晚于指标月份的版本生效。未匹配达人保留为`未分配商务`。
- 商务目标：按`商务+月份`维护跨平台总目标；实际达成金额为该商务当月生效归属下的达人GMV。

### 当前链路

```text
ods.ods_douyin_order_raw
  -> dwd.dwd_douyin_influencer_sales_order_item_detail
  -> dws.dws_douyin_influencer_sales_order_item

ods.ods_wechat_channels_order_raw
  -> dwd.dwd_wechat_channels_influencer_sales_order_item_detail
  -> dws.dws_wechat_channels_influencer_sales_order_item

ods.ods_ks_order_raw
  -> dwd.dwd_ks_influencer_sales_order_item_detail
  -> dws.dws_ks_influencer_sales_order_item

ods.ods_tmall_order_raw
  -> dwd.dwd_tmall_influencer_sales_order_detail
  -> dws.dws_tmall_influencer_sales_order

ods.ods_jd_order_raw / ods.ods_xhs_order_raw / ods.ods_pdd_order_raw
  -> 各平台达人补零专属DWD
  -> 各平台达人店铺日补零DWS

各平台DWD均通过 common.v_ingest_batch_shop_context 取得标准店铺
各平台DWS统一 UNION ALL
  -> dim.dim_platform_shop_company
  -> dim.dim_influencer_business_assignment_monthly
  -> ads.ads_influencer_company_shop_daily
  -> ads.ads_influencer_company_shop_monthly_ranking
  -> ads.ads_influencer_business_monthly
  -> DataEase

达人归属Excel -> etl/common/load_influencer_business_assignment.py
配置网页 -> 商务人员 / 月度归属版本 / 商务月度GMV目标 -> 自动刷新达人ADS
```

三张ADS已经接入七个平台。京东、小红书和拼多多的占位行只进入达人日ADS，月排名和商务实际达成会过滤`gmv_amount=0`及`__no_influencer__`，不会产生虚假达人、排名或商务业绩。公司和店铺均来自标准DIM，不硬编码达播店铺范围，运营、其他部门和财务可使用公共店铺筛选器查看各自范围。

刷新与配置命令：

```powershell
python etl/common/load_influencer_business_assignment.py --file "data/达人归属/达人归属表-（月更）.xlsx" --month 2026-07-01
python etl/influencer_performance/run_multiplatform_influencer_performance_etl.py
python apps/influencer_config/server.py --bind 127.0.0.1 --port 8765
```

Excel只用于指定月份的初始导入，冲突时不覆盖网页已经维护的同月版本。配置页达人列表严格只读取配置库，不合并订单中的当月活跃达人；支持查询、新增、编辑平台/UID/名称/商务/店铺/备注，以及按生效月删除。删除通过`is_active = false`的停用版本实现，从删除月份起隐藏、删除月份以前的历史继续保留。配置页地址为`http://127.0.0.1:8765/`；保存、修改或删除归属以及保存目标后，相关ADS在同一数据库事务内刷新。服务默认仅监听本机，正式共享时应由现有内网反向代理与认证体系承载。

### DataEase配置

- 达人总量：数据集`ads.ads_influencer_company_shop_daily`，按当前筛选范围计算`COUNT(DISTINCT CASE WHEN gmv_amount > 0 THEN influencer_key END)`。
- 达人总成交额：同一数据集，指标`SUM(gmv_amount)`。
- 达人总退款金额：同一数据集，指标`SUM(refund_amount)`。
- 达人总退款率：同一数据集，计算字段`SUM(refund_amount) / SUM(gmv_amount)`，格式为百分比。
- 各平台达人总数量：同一数据集，类别`platform_name`，指标为产生GMV的`influencer_key`去重数，使用降序条形图。
- 月10万+达人数量：数据集`ads.ads_influencer_company_shop_monthly_ranking`，类别`stat_month -> platform_name`，按达人去重后筛选月GMV大于等于100,000元再计数。全平台全店视图可直接使用`is_platform_month_100k_plus`。
- 达人月销售额Top5：同一月排名数据集，类别显示`platform_name + influencer_name`。无店铺筛选时使用`MAX(platform_month_gmv)`、`MAX(previous_platform_month_gmv)`和`MAX(platform_mom_growth_rate)`并筛选`platform_month_rank <= 5`；按店铺查看时使用`SUM(current_month_gmv)`与`SUM(previous_month_gmv)`重算环比并设置Top N=5。
- 商务月度业绩：数据集`ads.ads_influencer_business_monthly`，展示`gmv_target`、`actual_gmv_amount`、`completion_rate`、`assigned_influencer_count`、`active_influencer_count`和`influencer_100k_plus_count`。
- 公共筛选器：日指标使用`company_name`、`stat_date`、`platform_name`、`shop_name`；月排名使用`company_name`、`stat_month`、`platform_name`、`shop_name`；商务目标本身为跨平台、跨店汇总，仅使用`stat_month`和`business_owner_name`。

### 当前实际数据库验收基准

| 平台 | ODS/DWD行 | DWS行 | 日ADS行 | 活跃达人 | GMV | 退款 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 抖音 | 19,469 / 19,469 | 237 | 102 | 35 | 22,931.00 | 6,443.00 |
| 视频号 | 452 / 452 | 416 | 33 | 10 | 78,940.00 | 13,294.00 |
| 快手 | 1,378 / 1,378 | 1,227 | 158 | 27 | 157,928.00 | 79,862.10 |
| 天猫 | 1,098 / 1,098 | 5 | 4 | 1 | 495.00 | 99.00 |
| 京东 | 35 / 35 | 11个补零店铺日 | 11 | 0 | 0.00 | 0.00 |
| 小红书 | 12 / 12 | 6个补零店铺日 | 6 | 0 | 0.00 | 0.00 |
| 拼多多 | 1,116 / 1,116 | 11个补零店铺日 | 11 | 0 | 0.00 | 0.00 |
| 合计 | 23,560 / 23,560 | 1,913 | 325 | 73 | 260,294.00 | 99,698.10 |

| 七平台ADS验收项 | 实际值 |
| --- | ---: |
| 达人总退款率 | 38.30% |
| 日期范围 | 2026-04-22 至 2026-07-05 |
| 达人日ADS行数 | 325 |
| 日ADS未匹配公司行数 | 0 |
| DWS与达人日ADS最终粒度双向差异 | 0 / 0 |
| 连续两次刷新结果 | 完全一致 |

以上基准为天猫新格式单文件正式切换后的当前实际数据库结果；月排名和商务目标仍由同一达人日ADS按月派生。当前已知达播店铺为`MOCK食品旗舰店`、`MOCK墨客咖时咖啡专卖店`、`MOCK咖啡旗舰店`、`MOCK官方旗舰店`；用户说明共有5家，第5家名称待后续补充。该清单只作业务说明，不参与SQL筛选。

## 9.10 银行指标与平台银行经营汇总

### 来源与财务提交关卡

- 银行原始流水来源于`ods.ods_bank_statement`，最小粒度为一条银行流水。
- 财务在经营配置中心完成拆分、分类和调账，结果写入`dwd.dwd_statement_split`；该表是银行指标共同的人工确认DWD，不再为四个指标复制清洗层。
- 指标只读取`fund.import_record.status='success' AND is_submitted=true`的批次。当前确认批次为`IMP20260721002`，ODS 58条、DWD 65条，日期为2026-01-02至2026-01-30。
- 刷新前必须阻断已提交批次的重复账号流水号、来源缺失、分类缺失、费用类型与入账关系无效、调账后非正金额、拆分基准金额不平和批次调账净差不为0。
- 银行账号名称通过`dim.dim_platform_shop_company`中的唯一公司名称解析公司编码；一名多码视为冲突，未匹配数据在ADS保留为`unmapped / 未匹配公司`。

### 日期、符号与公式

- 银行统计日期使用`ods.ods_bank_statement.transaction_date`；平台收入、平台费用和推广费使用各自ADS的`stat_date`。
- 银行贷方流入为正、借方流出为负；财务拆分指标金额使用`original_amount + adjusted_diff`。
- 收入按净流入展示，费用和成本按净流出展示；退款、冲回和反向流水保留反向符号，不取绝对值。
- 主营业务收入只纳入费用类型`主营业务收入`，并排除`dim.dim_account_entry.code='ACC002' / 平台提现`。
- 银行主表只包含银行流水；平台与银行汇总表从四张正式ADS读取，不再读取结算净额ADS。

```text
主营业务收入 = 主营业务收入分类净流入 - 平台提现
汇总总收入 = 平台主营收入 + 银行主营业务收入 + 银行营业外收入
汇总总支出 = 平台费用 + 独立推广费 + 银行费用 + 银行主营业务成本
经营结余 = 汇总总收入 - 汇总总支出
支出率 = 汇总总支出 / 汇总总收入
ROI = 汇总总收入 / 汇总总支出
总费用 = 销售费用 + 管理费用 + 税金及附加 + 人员成本 + 财务费用 + 营业外支出
主营业务成本 = 主营业务成本分类净流出
```

### 当前主链路

```text
ods.ods_bank_statement
  -> dwd.dwd_statement_split（财务网页提交锁定）
  -> dws.dws_bank_statement_account_daily_metric
  -> ads.ads_bank_statement_company_daily_metric
  -> DataEase银行流水指标卡、银行收入分类、费用分类

ads.ads_platform_main_business_income_company_shop_daily_category
ads.ads_platform_expense_company_shop_daily_category
ads.ads_promotion_expense_company_shop_daily
ads.ads_bank_statement_company_daily_metric
  -> ads.ads_platform_bank_total_revenue_company_daily_type
  -> DataEase总收入、总支出、经营结余、支出率、ROI及构成趋势图
```

`ads.ads_bank_statement_company_daily_metric`是银行流水唯一主数据集，只包含银行数据，
以`metric_group_code + metric_code`区分两类收入、六类费用和主营业务成本。
`ads.ads_platform_bank_total_revenue_company_daily_type`虽然保留旧表名，但已升级为通用收入支出长表。
平台店铺日数据先汇总到公司、平台、日期和分类，银行固定使用`platform_code='bank'`；
银行`revenue`进入收入，`expense`和`cost`进入支出。平台费用中的推广分类与独立推广账户费用均完整纳入，互不替代。
`ads.ads_main_business_revenue_company_daily`、`ads.ads_total_expense_company_daily_type`、
`ads.ads_main_business_cost_company_daily`和`ads.ads_total_revenue_company_daily_type`
继续由银行ETL刷新作为兼容层，
新建或迁移DataEase图表时不再使用这些兼容表。

刷新命令：

```powershell
python etl/bank/run_bank_management_metrics_etl.py
python etl/platform_bank_summary/run_platform_bank_summary_etl.py
```

生产刷新使用动态来源一致性、公式、唯一性、DIM、DWS/ADS双向差异和注释校验，不固定历史金额或行数。历史专项基准仅在人工验收时显式增加`--enforce-current-baseline`。自动化编排中，银行经营指标只由财务提交锁定批次触发；手动全量和夜间全量复用最近一次已提交成功的银行ADS，并在平台类依赖全部成功后刷新平台银行汇总。

### DataEase配置

- 银行流水数据集：`ads.ads_bank_statement_company_daily_metric`。
- 主营业务收入指标卡：过滤`metric_code='main_business_revenue'`，指标`SUM(metric_amount)`。
- 银行收入分类：过滤`metric_group_code='revenue'`，类别`metric_name`，指标`SUM(metric_amount)`。
- 总费用指标卡：过滤`metric_group_code='expense'`，指标`SUM(metric_amount)`。
- 各费用占比：过滤`metric_group_code='expense'`，类别`metric_name`，指标`SUM(metric_amount)`，使用降序横向条形图并显示占比标签。
- 主营业务成本指标卡：过滤`metric_code='main_business_cost'`，指标`SUM(metric_amount)`。
- 平台银行汇总数据集：`ads.ads_platform_bank_total_revenue_company_daily_type`。
- 总收入、总支出、经营结余、支出率和ROI使用DataEase自定义SQL，统一按`stat_date`和多选`company_code`参数筛选。
- 收入与支出分类构成：类别`primary_category_name`，指标`SUM(metric_amount)`，分别过滤`income`和`expense`。
- 收入/支出趋势：横轴`stat_date`，系列`financial_direction_name`，指标`SUM(metric_amount)`。
- 完整自定义SQL见`docs/platform_bank_summary_dataease.md`。
- 占比图使用横向条形图而非饼图或环图，因为未来退款或冲回可能使分类净额为负。

### 当前验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 已提交批次 | IMP20260721002 |
| ODS / DWD行数 | 58 / 65 |
| 银行日期范围 | 2026-01-02 至 2026-01-30 |
| 排除平台提现 | 833,748.88 |
| 主营业务收入 | 0.00 |
| 营业外收入 | 0.43 |
| 兼容表平台结算净额 | 4,796,746.68 |
| 兼容表总营收 | 4,796,747.11 |
| 销售费用 | 513,439.01 |
| 管理费用 | 59,185.78 |
| 税金及附加 | 108,759.18 |
| 人员成本 | 126,676.75 |
| 财务费用 | 79.45 |
| 营业外支出 | 0.00 |
| 总费用 | 808,140.17 |
| 主营业务成本 | 1,650.00 |
| 银行统一DWS / ADS行数 | 171 / 171 |
| 银行统一ADS日期范围 | 2026-01-02 至 2026-01-30 |
| 平台银行汇总ADS行数 | 3,972 |
| 平台银行汇总ADS日期范围 | 2026-01-02 至 2026-07-23 |
| 汇总总收入 | 6,302,004.28 |
| 汇总总支出 | 2,556,938.27 |
| 经营结余 | 3,745,066.01 |
| 支出率 | 40.5734% |
| ROI | 2.464668倍 |
| 银行主表/汇总表未匹配公司行数 | 0 / 0 |
| 银行主链路/汇总四来源双向差异 | 0 / 0 |
| 主营收入DWS / ADS行数 | 19 / 19 |
| 兼容总营收银行DWS / ADS行数 | 38 / 203 |
| 总费用DWS / ADS行数 | 114 / 114 |
| 主营成本DWS / ADS行数 | 19 / 19 |
| 兼容四套ADS未匹配公司行数 | 0 / 0 / 0 / 0 |
| 兼容四套DWS/ADS双向差异 | 0 / 0 / 0 / 0 |

平台银行汇总ADS日期范围为2026-01-02至2026-07-23，其中银行数据在1月，
平台主营收入和平台费用主要在4月至7月，独立推广费在6月至7月；不补零，DataEase必须按同一日期范围比较并注明来源覆盖范围。
当前主营业务收入为0是因为全部833,748.88元主营业务收入分类均属于已明确排除的平台提现。

## 9.11 八个平台达人佣金（旧版独立链路，已停用）

本节保留旧版独立 DWD/DWS/ADS、计算口径和历史验收信息用于审计，不再由文件上传、手动全量或夜间全量触发，也不删除现有表和历史结果。当前 DataEase 达人佣金使用`ads.ads_platform_expense_company_shop_daily_category`，通过`primary_category_code = 'influencer_commission'`动态汇总，详见9.12节。

### 指标口径

- 指标编码：`influencer_commission`，统一按费用为正、退款或冲回为负展示。
- 抖音来源：`ods.ods_douyin_fund_raw`。统计日期严格使用`动账时间`；佣金与招商服务费均取资金单最终动账事实，正常支出为负，因此标准化后取反。结算单不参与该指标，避免资金未到齐时产生不完整暂算值。
- 快手来源：`ods.ods_ks_settlement_raw`。统计日期严格使用`实际结算时间`；全部佣金模式、结算规则及退款记录纳入。当前22条订单退款记录中21条产生达人佣金，纳入金额285.53元，另1条三个组成金额均为0。
- 视频号来源：`ods.ods_wechat_channels_settlement_raw`。统计日期严格使用`记账时间`；仅选择动帐类型`达人佣金`和`带货机构服务费`。支出方向为正费用，未来同类型收入冲回按负费用保留。
- 银行来源：财务成功且已提交批次的`dwd.dwd_statement_split`与`ods.ods_bank_statement`。统计日期使用`transaction_date`；仅纳入`销售费用 / EXP006 -> 入账-达人佣金费用 / ACC006`。借方流出为正费用、贷方冲回为负费用；交易摘要仅用于审计，不参与排除。
- 天猫、京东、小红书和拼多多当前没有达人佣金来源，按各自订单ODS的标准店铺和订单自然日生成金额、纳入明细数均为0的店铺日占位行，仅用于DataEase公司、平台、店铺和日期筛选器联动。
- 四个补零平台分别取天猫`订单创建时间`、京东`下单时间`、小红书`订单创建时间`、拼多多`订单成交时间`；拼多多成交时间缺失时由订单号前六位解析日期。补零不按订单或售后状态筛选，也不复用达人业绩等其他指标层。

```text
抖音达人佣金 = -(资金单源佣金 + 资金单源招商服务费)
快手达人佣金 = 达人佣金(元) + 团长佣金(元) + 其他收费
视频号达人佣金 = 达人佣金动账带符号金额 + 带货机构服务费动账带符号金额
银行达人佣金 = 销售费用下入账-达人佣金费用的净流出
天猫/京东/小红书/拼多多达人佣金 = 0
```

### 当前链路

```text
ods.ods_douyin_fund_raw
  -> dwd.dwd_douyin_influencer_commission_event_detail
  -> dws.dws_douyin_influencer_commission_shop_daily

ods.ods_ks_settlement_raw
  -> dwd.dwd_ks_influencer_commission_event_detail
  -> dws.dws_ks_influencer_commission_shop_daily

ods.ods_wechat_channels_settlement_raw
  -> dwd.dwd_wechat_channels_influencer_commission_event_detail
  -> dws.dws_wechat_channels_influencer_commission_shop_daily

ods.ods_bank_statement + dwd.dwd_statement_split（财务已提交）
  -> dwd.dwd_bank_influencer_commission_statement_split_detail
  -> dws.dws_bank_influencer_commission_account_daily

ods.ods_tmall_order_raw
  -> dwd.dwd_tmall_influencer_commission_zero_order_detail
  -> dws.dws_tmall_influencer_commission_shop_daily_zero

ods.ods_jd_order_raw
  -> dwd.dwd_jd_influencer_commission_zero_order_detail
  -> dws.dws_jd_influencer_commission_shop_daily_zero

ods.ods_xhs_order_raw
  -> dwd.dwd_xhs_influencer_commission_zero_order_detail
  -> dws.dws_xhs_influencer_commission_shop_daily_zero

ods.ods_pdd_order_raw
  -> dwd.dwd_pdd_influencer_commission_zero_order_detail
  -> dws.dws_pdd_influencer_commission_shop_daily_zero

八个平台DWS
  -> dim.dim_platform_shop_company
  -> ads.ads_influencer_commission_company_platform_daily
  -> DataEase 达人佣金指标卡 + 按平台日趋势折线图
```

银行没有店铺粒度，共享ADS统一采用公司、平台、日期粒度，不为银行虚构店铺。七个电商平台先在DWS保留店铺日粒度，再由ADS按统计日期通过DIM汇总到公司平台日；四个补零平台的ADS金额和纳入明细数始终为0。

保留的手工审计命令（生产自动化已停用）：

```powershell
python etl/influencer_commission/run_influencer_commission_etl.py
```

### 旧版DataEase配置（已停用）

- 数据集：`ads.ads_influencer_commission_company_platform_daily`。
- 指标卡：`SUM(influencer_commission_amount)`，金额保留两位小数。
- 日趋势折线图：横轴`stat_date`，纵轴`SUM(influencer_commission_amount)`，系列`platform_name`。
- 公共筛选器：`company_name`、`platform_name`、`stat_date`。
- 指标卡汇总必须等于ADS总额，折线图所有点之和必须等于指标卡。
- 当前银行数据在1月、抖音在6月至7月、快手在5月至6月、视频号在5至7月；天猫新格式单文件补零日期为6月25日至7月5日，京东、小红书和拼多多补零日期为6至7月。正式补导历史文件后日期范围会扩展；跨平台比较必须使用同一日期筛选范围，不能把全量总额解释为同期平台对比。

### 停用时保留的数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 抖音资金ODS/DWD行数、DWS行数 | 11,046 / 11,046 / 41 |
| 抖音佣金/招商服务费/指标总额 | 138,449.58 / 230,981.59 / 369,431.17 |
| 快手ODS/DWD行数、DWS行数 | 3,211 / 3,211 / 61 |
| 快手达人佣金/团长佣金/其他收费 | 110,727.45 / 4,413.58 / 3,847.31 |
| 快手指标总额、纳入明细、退款有金额记录 | 118,988.34 / 3,141 / 48 |
| 视频号ODS/DWD行数、DWS行数 | 4,206 / 4,206 / 41 |
| 视频号达人佣金/带货机构服务费/指标总额 | 35,011.83 / 3,304.27 / 38,316.10 |
| 银行已提交ODS/指标DWD/DWS行数 | 58 / 65 / 8 |
| 银行纳入拆分明细/达人佣金 | 9 / 382,332.27 |
| 天猫ODS/DWD、补零DWS行数与日期范围 | 2,196 / 1,098 / 11 / 2026-06-25至2026-07-05 |
| 京东ODS/DWD、补零DWS行数与日期范围 | 35 / 35 / 11 / 2026-06-25至2026-07-05 |
| 小红书ODS/DWD、补零DWS行数与日期范围 | 12 / 12 / 6 / 2026-06-25至2026-07-05 |
| 拼多多ODS/DWD、补零DWS行数与日期范围 | 1,116 / 1,116 / 11 / 2026-06-25至2026-07-05 |
| 四个补零平台金额/纳入明细数 | 0.00 / 0 |
| ADS行数与日期范围 | 190 / 2026-01-06至2026-07-05 |
| 达人佣金总额 | 909,067.88 |
| ADS未匹配公司 / DWS与ADS双向差异 / 重复主键组 | 0 / 0 / 0 |
| 连续两次全量刷新 | 结果一致 |

天猫一行使用新格式单文件正式切换后的当前实际值。天猫补零日期变化不影响达人佣金总额。
旧抖音结算单暂算结果已从达人佣金链路删除，正确的历史结算 ODS 未修改。抖音资金 DWD 按`店铺 + 动账流水号`选择最新导入版本；资金与结算分开或乱序上传不改变最终结果。

## 9.12 平台费用人工一级分类与原始二级分类

### 指标口径

- 当前平台：抖音、快手、京东、天猫、拼多多、视频号和小红书；七个平台共用人工映射维表，但各自拥有独立DWD和DWS。
- 来源：抖音使用`ods.ods_douyin_settlement_raw`和`ods.ods_douyin_fund_raw`；快手使用`ods.ods_ks_settlement_raw`和`ods.ods_ks_fund_raw`；京东使用`ods.ods_jd_settlement_raw`和`ods.ods_jd_fund_raw`。
- 天猫不使用结算单，来源为`ods.ods_tmall_aggregate_fund_raw`和`ods.ods_tmall_alipay_fund_raw`，分别保存聚合账户和支付宝账户明细。
- 拼多多和视频号只使用各自结算ODS；小红书使用订单结算和其他服务款两张结算ODS，不读取资金单。
- 最小粒度：抖音结算一条ODS记录拆为七个原始费用字段；快手结算一条ODS记录拆为八个候选字段，其中`支付营销回退（元）`映射为不计费用；资金来源一条ODS流水保留一个平台原始场景。
- 天猫聚合账户按支付流水号、支付宝账户按账务流水号选择最新版本；当前两个来源业务流水均唯一。
- 统计日期：抖音结算取`结算时间`、资金取`动账时间`；快手结算取`实际结算时间`、资金取`入账时间`；京东结算取`账单日期`、资金补充费用取`入账时间`，均无日期兜底。
- 天猫聚合账户取`入帐日期`，支付宝账户取`发生时间`日期；两个账户均不统一减一天。
- 金额方向：抖音结算费用字段取反，正常费用为正、退回为负；快手结算费用字段直接作为正费用候选；京东结算和三个平台资金均统一为支出正费用、收入负费用。
- 天猫聚合账户使用`收入金额(元)-支出金额(元)`还原带符号金额，支付宝账户使用`收入金额（+元）+支出金额（-元）`；平台费用统一取相反数，使扣款为正费用、返还为负费用。
- 二级分类：严格保留平台原始费用字段名或动账场景名。快手资金二级分类固定为平台原始`业务类型 + 描述`；京东资金二级分类固定为完整`资金动账备注`，均不改写描述中的订单号。
- 天猫二级分类按用户确认固定为`业务类型 + 标准化备注`；订单号、付款方、邮箱、tradeid、memberid和batchno只保留在DWD原始备注审计字段，不进入二级分类。
- 一级分类：由财务在`dim.dim_platform_fee_mapping`人工维护；一个二级分类只能存在一条有效映射，多个二级分类可以映射到同一个一级分类。
- 纳入规则：仅汇总有效映射中`include_in_platform_expense = TRUE`的场景。货款结算、退款勾稽和提现虽然也必须配置映射，但默认不计平台费用。
- 完整性规则：任何新出现的平台原始费用场景如果没有有效映射，DWS刷新立即失败，不得静默丢弃。
- 来源职责规则：`dim.dim_platform_fee_mapping`除财务维护的一级、二级分类外，还由系统维护`source_role`、`metric_role`和`dedup_rule_code`。计入平台费用的场景只能使用`PRIMARY`、`SUPPLEMENT`或`EXPENSE_OFFSET`；结算到账、退款勾稽、账户划转和跨表重复事实分别标记为`RECONCILIATION`、`ACCOUNT_TRANSFER`或`DUPLICATE`，即使资金方向为支出也不得进入费用。
- 当前稳定来源策略：抖音、快手、京东和小红书以结算单费用组件为主、资金单独有经营事项为补充；天猫使用双资金账户；拼多多和视频号的当前规范账务明细同时具有结算/资金语义，只保留一份事实。抖音资金组件若未来替代结算组件，必须按店铺和覆盖期间建立互斥来源锁，并先完成逐日逐分类等价验证。
- 公司和店铺：DWD只通过`common.v_ingest_batch_shop_context`获得标准店铺，ADS按日期关联`dim.dim_platform_shop_company`生成公司。

```text
二级分类费用 = SUM(来源方向标准化金额)
WHERE 平台费用映射有效
  AND include_in_platform_expense = TRUE

一级分类费用 = SUM(该一级分类下全部二级分类费用)

抖音一级分类“达人佣金”
  = 二级分类“达人佣金”
  + 二级分类“招商服务费”

快手一级分类“达人佣金”
  = 结算二级分类“达人佣金(元)”
  + 结算二级分类“团长佣金(元)”
  + 资金二级分类中的达人/团长佣金返还

京东一级分类“推广费”
  = 资金二级分类“消费订单”
  + 资金二级分类“京东联盟扣款”
  - 资金二级分类“京东联盟补款”

天猫一级分类“推广费”
  = 品牌新享首单拉新净费用
  + 淘宝内容推广服务费净费用
  + 淘宝客佣金
  + 淘宝联盟佣金净费用
```

种子映射只在原始场景尚不存在时插入，不覆盖财务后续人工调整。财务修改一级分类时必须同时维护`primary_category_code`、`primary_category_name`和`updated_by`，数据库触发器自动刷新`updated_at`；场景不属于费用时应保留有效映射并将`include_in_platform_expense`设为`FALSE`，而不是删除映射。

快手和京东资金描述经常携带订单号。映射表通过`source_business_type`保留业务类型，并用`source_description_match_type`配置`exact`、`prefix`、`contains`或`any`规则；规则只负责命中人工分类，DWD、DWS和ADS展示的`secondary_category_name`仍是完整原文。多条规则同时命中时取`mapping_priority`最高的一条。

### 当前链路

```text
ods.ods_douyin_settlement_raw
ods.ods_douyin_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_douyin_platform_expense_source_detail
  -> dim.dim_platform_fee_mapping
  -> dws.dws_douyin_platform_expense_shop_daily_category

ods.ods_ks_settlement_raw
ods.ods_ks_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_ks_platform_expense_source_detail
  -> dim.dim_platform_fee_mapping
  -> dws.dws_ks_platform_expense_shop_daily_category

ods.ods_jd_settlement_raw
ods.ods_jd_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_jd_platform_expense_source_detail
  -> dim.dim_platform_fee_mapping
  -> dws.dws_jd_platform_expense_shop_daily_category

ods.ods_tmall_aggregate_fund_raw
ods.ods_tmall_alipay_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_tmall_platform_expense_source_detail
  -> dim.dim_platform_fee_mapping
  -> dws.dws_tmall_platform_expense_shop_daily_category

ods.ods_pdd_settlement_raw
ods.ods_wechat_channels_settlement_raw
ods.ods_xhs_settlement_income_raw
ods.ods_xhs_settlement_expense_raw
  -> common.v_ingest_batch_shop_context
  -> 三个平台各自的平台费用DWD
  -> dim.dim_platform_fee_mapping
  -> 三个平台各自的平台费用店铺日分类DWS

七个平台DWS
  -> dim.dim_platform_shop_company
  -> ads.ads_platform_expense_company_shop_daily_category
  -> DataEase 平台总费用指标卡 + 一级/二级费用下钻图
```

刷新命令：

```powershell
python etl/douyin/run_douyin_platform_expense_etl.py
python etl/ks/run_ks_platform_expense_etl.py
python etl/jd/run_jd_main_business_finance_etl.py
python etl/tmall/run_tmall_main_business_finance_etl.py
python etl/platform_finance/run_pdd_main_business_finance_etl.py
python etl/platform_finance/run_wechat_channels_main_business_finance_etl.py
python etl/platform_finance/run_xhs_main_business_finance_etl.py
```

当前确认数据专项验收：

```powershell
python etl/douyin/run_douyin_platform_expense_etl.py --enforce-current-baseline
python etl/ks/run_ks_platform_expense_etl.py --enforce-current-baseline
python etl/jd/run_jd_main_business_finance_etl.py --enforce-current-baseline
python etl/tmall/run_tmall_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_pdd_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_wechat_channels_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_xhs_main_business_finance_etl.py --enforce-current-baseline
```

### DataEase配置

- 数据集：`ads.ads_platform_expense_company_shop_daily_category`。
- 平台总费用指标卡：`SUM(expense_amount)`。
- 一级费用分类构成：类别`primary_category_name`，指标`SUM(expense_amount)`。
- 一级到二级下钻：层级`primary_category_name -> secondary_category_name`，指标`SUM(expense_amount)`。
- 达人佣金指标卡：过滤`primary_category_code = 'influencer_commission'`后汇总`expense_amount`，不再手工相加达人佣金与招商服务费。
- 日趋势：横轴`stat_date`，纵轴`SUM(expense_amount)`，系列`primary_category_name`。
- 公共筛选器：`company_name`、`stat_date`、`platform_name`、`shop_name`。

### 当前实际数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 平台费用映射数 | 129（抖音20、快手28、京东15、天猫30、拼多多21、视频号11、小红书4） |
| 抖音结算ODS / 资金ODS | 34,654 / 11,046 |
| 快手结算ODS / 资金ODS | 3,211 / 2,241 |
| 抖音平台费用DWD | 253,624 |
| 快手平台费用DWD | 27,929 |
| 京东平台费用DWD | 1,819 |
| 天猫平台费用DWD | 15,983 |
| 拼多多平台费用DWD | 21,704 |
| 视频号平台费用DWD | 4,206 |
| 小红书平台费用组件DWD | 1,032 |
| 共享平台费用ADS | 2,147 |
| ADS日期范围 | 2026-04-01 至 2026-07-05 |
| 抖音全量平台费用 | 482,787.03 |
| 快手全量结算费用 / 资金净费用 | 129,782.65 / 1,215.70 |
| 快手全量平台费用 | 130,998.35 |
| 京东全量平台费用 | 11,320.09 |
| 天猫全量平台费用 | 31,341.61 |
| 七个平台全量费用 | 714,659.81 |
| ADS未匹配公司 / DWS与ADS双向差异 | 0 / 0 |
| 连续两次刷新 | 结果一致 |

2026-08-10完成双来源职责控制改造：129条有效映射中，62条`PRIMARY/PLATFORM_EXPENSE`、16条`SUPPLEMENT/PLATFORM_EXPENSE`、13条`EXPENSE_OFFSET/EXPENSE_OFFSET`，合计91条计费规则；其余38条为主营收入/退款、勾稽、账户划转或重复事实，`UNMAPPED=0`。改造前后两张共享ADS的逐平台行数、日期、金额及有序行摘要完全一致，主营业务收入仍为1,209行、6,302,003.85元，平台费用仍为2,147行、714,659.81元。完整方案与验收基准见`docs/platform_finance_dual_source_control_plan_20260810.md`。

`250769954 / MOCK咖啡旗舰店`在2026年6月的专项基准为：结算费用382,377.53元、资金额外费用5,479.38元、平台总费用387,856.91元；一级分类达人佣金368,216.15元，其中二级分类达人佣金137,234.56元、招商服务费230,981.59元。补全的结算文件和原始资金文件分别作为批次42、43追加导入，历史ODS未清空或覆盖。

`3527127781 / MOCK陌时专卖店`在2026年6月的专项基准为：结算费用81,713.85元、资金净费用1,215.70元、平台总费用82,929.55元。一级分类为达人佣金73,861.49元、平台服务费6,116.85元、其他平台费用1,534.15元、集运物流费178.00元、退货物流费713.40元、小额打款425.66元、违约金100.00元。`支付营销回退（元）`不计平台费用；正常货款结算、退款补结算、已在结算单体现的10.00元结算后退款、余额提现和退款冻结/解冻/扣减勾稽均有映射但不重复计费。补全的快手6月结算文件作为批次44追加导入，原有5月结算批次和6月资金批次均未清空或覆盖。

`123572735 / MOCK饮品旗舰店`在2026年6月的平台费用专项基准为：结算费用842.09元、资金净费用9,300.97元、平台总费用10,143.06元。一级分类为推广费9,308.72元、平台佣金473.81元、商品保险149.15元、运费保险105.58元、平台服务费82.72元、售后赔付17.00元、京豆费用6.08元。结算货款、钱包商户结算和钱包售后退款质保金扣除均保留映射但不计平台费用。京东6月结算和资金文件分别作为批次46、47追加导入；与历史资金批次重叠的12条业务流水在DWD按业务键选择最新版本，不重复统计。

`549820088 / MOCK旗舰店`在2026年6月的平台费用专项基准为31,341.61元。一级分类为推广费14,582.13元、营销优惠费6,581.85元、平台佣金5,263.36元、平台服务费3,803.93元、履约保险费632.47元、小额打款366.87元、物流费用111.00元。聚合账户和支付宝账户分别作为批次48、49追加导入；提现265,000元、订单收款和销售退款均保留映射但不计平台费用，销售退款只冲减主营业务收入。

2026年5月新增三个结算单平台专项基准：拼多多平台费用6,356.68元，提现184,000元和转账广告账户83,210元不计费用；视频号平台费用36,969.22元，提现和极速退款垫资勾稽不计费用；小红书平台费用10,828.45元，其中买手佣金10,384.84元、平台佣金323.43元、运费宝120.18元。

## 9.13 京东主营业务收入

### 指标口径

- 来源：`ods.ods_jd_settlement_raw`和`ods.ods_jd_fund_raw`，两个来源使用独立业务键选择最新版本。
- 统计日期：结算单取`账单日期`；资金结算后退款取`入账时间`。资金商户结算不参与主营业务收入。
- 订单收入：结算单`费用项='货款' AND 单据类型='订单'`的带符号金额。
- 结算退款：结算单`费用项='货款' AND 单据类型 IN ('取消退款单','售后服务单')`的负金额。
- 资金补充退款：`交易类型='转账-售后退款质保金扣除'`的负金额；从资金备注解析对应订单号，只有结算单不存在同一订单退款货款时才纳入。
- 明细：一级分类为商品销售收入和销售退款；结算二级分类保留`货款`，资金退款二级分类保留完整资金动账备注。
- 零值日期：结算来源存在但没有任何收入或退款事件的自然日写入0值占位，保证日趋势不断点。

```text
京东主营业务收入
  = 结算单订单货款
  + 结算单退款货款
  + 跨表去重后的资金结算后退款
```

### 当前链路

```text
ods.ods_jd_settlement_raw
ods.ods_jd_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_jd_main_business_income_source_detail
  -> dws.dws_jd_main_business_income_shop_daily_category
  -> dim.dim_platform_shop_company
  -> ads.ads_platform_main_business_income_company_shop_daily_category
  -> DataEase 主营业务收入指标卡 + 日趋势 + 收入/退款分类图
```

刷新及专项验收命令：

```powershell
python etl/jd/run_jd_main_business_finance_etl.py
python etl/jd/run_jd_main_business_finance_etl.py --enforce-current-baseline
```

### DataEase配置

- 数据集：`ads.ads_platform_main_business_income_company_shop_daily_category`。
- 主营业务收入指标卡：`SUM(income_amount)`。
- 日趋势：横轴`stat_date`，纵轴`SUM(income_amount)`，系列`primary_category_name`。
- 收入明细：一级类别`primary_category_name`，二级下钻`secondary_category_name`，指标`SUM(income_amount)`。
- 公共筛选器：`company_name`、`stat_date`、`platform_name`、`shop_name`。

### 当前实际数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 结算ODS原始/唯一单据 | 1,753 / 1,753 |
| 资金ODS原始/唯一事件 | 78 / 66 |
| 收入DWD | 1,819 |
| 收入ADS | 75 |
| 全量日期范围 | 2026-05-01 至 2026-07-05 |
| 2026年6月自然日覆盖 | 30 |
| 2026年6月订单收入 | 15,518.76 |
| 2026年6月结算退款 / 资金补充退款 | -1,511.00 / -404.00 |
| 2026年6月主营业务收入 | 13,603.76 |
| 跨表重复退款 / 公司未匹配 / DWS与ADS差异 | 0 / 0 / 0 |
| 6月结算批次对账 | 30 / 30匹配，13,165.67 = 13,165.67 |
| 连续全量刷新 | 结果一致 |

## 9.14 天猫双资金账户主营业务收入

### 指标口径

- 来源：`ods.ods_tmall_aggregate_fund_raw`和`ods.ods_tmall_alipay_fund_raw`，分别按支付流水号和账务流水号选择最新版本。
- 统计日期：聚合账户取`入帐日期`；支付宝账户取`发生时间`日期，均无日期兜底。
- 订单收入：聚合账户`入帐类型='交易收款'`和支付宝账户`业务类型='交易付款'`的带符号正金额。
- 销售退款：聚合账户`入帐类型='交易退款(售后)'`和支付宝账户`业务类型='交易退款'`的带符号负金额。
- 提现：两个账户合计265,000元，属于资金转出，不进入主营业务收入或平台费用。
- 费用：其他扣款、分账、转账、其它及其返还按平台费用人工映射进入天猫平台费用DWS，不冲减主营业务收入。
- 二级收入分类固定为平台原始业务类型加标准化场景，例如`交易付款 + 订单收款`和`交易退款 + 销售退款`。

```text
天猫主营业务收入
  = 聚合账户交易收款
  + 支付宝账户交易付款
  + 聚合账户交易退款(售后)
  + 支付宝账户交易退款

两账户资金勾稽
  = 主营业务收入 - 主营业务支出 - 提现
  = 两账户原始带符号资金净变动
```

### 当前链路

```text
ods.ods_tmall_aggregate_fund_raw
ods.ods_tmall_alipay_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_tmall_main_business_income_source_detail
  -> dws.dws_tmall_main_business_income_shop_daily_category
  -> dim.dim_platform_shop_company
  -> ads.ads_platform_main_business_income_company_shop_daily_category
  -> DataEase 主营业务收入指标卡 + 日趋势 + 收入/退款分类图
```

刷新及专项验收命令：

```powershell
python etl/tmall/run_tmall_main_business_finance_etl.py
python etl/tmall/run_tmall_main_business_finance_etl.py --enforce-current-baseline
```

### 当前实际数据库验收基准

| 验收项 | 实际值 |
| --- | ---: |
| 聚合账户ODS / 唯一支付流水 | 775 / 775 |
| 支付宝账户ODS / 唯一账务流水 | 15,208 / 15,208 |
| 收入DWD / 费用DWD | 15,983 / 15,983 |
| 收入DWS / 天猫收入ADS | 72 / 72 |
| 日期范围 / 自然日覆盖 | 2026-06-01至2026-06-30 / 30 |
| 商品销售收入 | 264,960.54 |
| 销售退款 | -1,478.16 |
| 主营业务收入 | 263,482.38 |
| 主营业务支出 | 31,341.61 |
| 提现 / 原始资金净变动 | 265,000.00 / -32,859.23 |
| 资金勾稽差额 | 0.00 |
| 跨账户重复 / 公司未匹配 / DWS与ADS差异 | 0 / 0 / 0 |

### 天猫新增费用场景处理

- DWD仍完整保留两账户的每一条资金流水，并用与原始费用页面相同的规则生成`业务类型 + 标准化场景`二级分类。订单号、流水号、付款方等实例信息只在`source_description`中保留审计，不参与场景名称。
- 新出现的标准化场景不会自动继承已有业务类型的一级分类，也不会写入费用映射表；它会出现在经营配置中心的“原始费用”列表，状态为“未映射”，由财务选择一级分类、计入费用与描述匹配方式。
- 天猫费用DWS只汇总已命中有效映射且`include_in_platform_expense = TRUE`的记录。未映射记录暂不计入平台费用，但不从DWD或原始费用列表删除。
- ETL遇到未映射场景时完成DWD、DWS、ADS刷新并提交事务，输出警告数量、场景名称和未纳入费用金额；备注为空等新场景质量问题也以警告保留。只有来源字段、店铺批次、公司映射、主键或资金勾稽等硬性校验失败才回滚并报错。
- 描述匹配规则由映射维表控制：`none`按标准二级分类匹配，`exact`精确匹配原始描述，`prefix`匹配描述前缀，`contains`匹配描述包含文本，`any`匹配同一业务类型的全部描述。多个规则命中时使用`mapping_priority`较高者；`exact/prefix/contains`必须填写非空匹配值。

## 9.15 拼多多、视频号和小红书主营业务收入与平台费用

### 指标口径

- 拼多多来源`ods.ods_pdd_settlement_raw`。主营业务收入为订单收入、优惠券结算收入及对应退款的带符号合计；平台费用为其余经营费用取反。提现和转账广告账户属于资金划转，不计平台费用。
- 视频号来源`ods.ods_wechat_channels_settlement_raw`。主营业务收入为订单支付、先用后付订单、平台优惠补贴净额和订单退款的带符号合计；平台费用为达人佣金、带货机构服务费、技术服务费和运费险。提现、极速退款垫资及回补只作勾稽。
- 小红书收入来源`ods.ods_xhs_settlement_income_raw`，通过`动账金额-平台佣金-买手佣金-花呗分期手续费`还原订单佣金前收入；`ods.ods_xhs_settlement_expense_raw`中的`申诉调账`按平台补偿收入直接纳入，其他服务款中的费用类场景才进入平台费用。
- 日期分别取拼多多`发生时间`、视频号`记账时间`和小红书`结算时间`，无日期兜底。
- 费用正常扣款为正、费用退款或补回为负；`申诉调账`收入保留正负号且不进入费用。一级分类由财务维护，二级分类保留平台原始账务场景。

### 当前链路

```text
三个平台结算ODS
  -> common.v_ingest_batch_shop_context
  -> 各平台主营业务收入DWD / 平台费用DWD
  -> dim.dim_platform_fee_mapping
  -> 各平台收入店铺日分类DWS / 费用店铺日分类DWS
  -> 两张共享ADS
  -> DataEase 收入、费用指标卡及分类下钻
```

刷新及专项验收：

```powershell
python etl/platform_finance/run_pdd_main_business_finance_etl.py
python etl/platform_finance/run_wechat_channels_main_business_finance_etl.py
python etl/platform_finance/run_xhs_main_business_finance_etl.py
python etl/platform_finance/run_pdd_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_wechat_channels_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_xhs_main_business_finance_etl.py --enforce-current-baseline
```

### 2026年5月专项基准

| 平台 | 主营业务收入 | 平台费用 | 收入减平台费用 |
| --- | ---: | ---: | ---: |
| 拼多多 | 315,100.14 | 6,356.68 | 308,743.46 |
| 视频号 | 115,536.56 | 36,969.22 | 78,567.34 |
| 小红书 | 25,808.05 | 10,828.45 | 14,979.60 |
| 合计 | 456,444.75 | 54,154.35 | 402,290.40 |

三平台批次店铺全部映射，新增费用场景未映射数为0，收入与费用DWS到共享ADS双向差异为0，结算资金勾稽差额均为0.00。完整明细见`docs/pdd_wechat_xhs_main_business_finance_analysis_202605.md`。

## 9.16 抖音、快手主营业务收入接入七平台共享ADS

### 指标口径

- 抖音来源`ods.ods_douyin_settlement_raw`，统计日期严格使用`结算时间`。
- 抖音主营业务收入直接使用平台结算后的十项收入组成，十项合计逐行必须等于源`收入合计`。`结算单类型`以“结算后退款”开头的负收入归入销售退款；结算前退款已经体现在平台结算净收入中，不再额外冲减。
- 抖音一级分类为商品销售收入、平台补贴和销售退款，二级分类保留用户实付、平台补贴等十个源字段名。
- 快手来源`ods.ods_ks_settlement_raw`和`ods.ods_ks_fund_raw`。结算统计日期取`实际结算时间`，补充退款统计日期取资金`入账时间`。
- 快手结算主营业务收入为订单实付、政府补贴、支付营销补贴、平台补贴和达人补贴之和，减商家补贴与订单退款。源`合计收入(元)`没有扣除订单退款，不能直接作为指标。
- 快手资金只补充`业务类型='资金扣减' AND 描述='快手小店退款'`的超售后期最终扣减；资金冻结、临时解冻和资金解冻均不进入收入。
- 快手资金退款通过`关联业务单号`与结算订单号查重。订单`2615400613213943`的10.00元退款已在结算单体现，资金`结算后退款 + 退现金金额`只用于勾稽，不再重复冲减。

```text
抖音主营业务收入
  = 用户实付
  + 九类平台/达人/支付补贴
  = 源收入合计

快手主营业务收入
  = 订单实付
  + 政府补贴
  + 支付营销补贴
  + 平台补贴
  + 达人补贴
  - 商家补贴
  - 订单退款
  - 跨表去重后的超售后期实际资金扣减
```

### 当前链路

```text
ods.ods_douyin_settlement_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_douyin_main_business_income_source_detail
  -> dws.dws_douyin_main_business_income_shop_daily_category

ods.ods_ks_settlement_raw
ods.ods_ks_fund_raw
  -> common.v_ingest_batch_shop_context
  -> dwd.dwd_ks_main_business_income_source_detail
  -> dws.dws_ks_main_business_income_shop_daily_category

抖音、快手及原五个平台主营收入DWS
  -> dim.dim_platform_shop_company
  -> ads.ads_platform_main_business_income_company_shop_daily_category
  -> DataEase 主营业务收入指标卡 + 日趋势 + 一级/二级分类下钻
```

刷新及专项验收：

```powershell
python etl/platform_finance/run_douyin_ks_main_business_income_etl.py
python etl/platform_finance/run_douyin_ks_main_business_income_etl.py --enforce-current-baseline
```

### 当前实际数据库验收基准

| 验收项 | 抖音 | 快手 |
| --- | ---: | ---: |
| 结算ODS/DWD | 34,654 / 34,654 | 3,211 / 3,211 |
| 资金ODS/DWD | 不使用 | 2,241 / 2,241 |
| DWS/共享ADS行数 | 533 / 533 | 219 / 219 |
| 日期范围 | 2026-04-01至2026-06-30 | 2026-05-01至2026-06-30 |
| 结算主营业务收入 | 5,167,898.42 | 341,727.99 |
| 资金补充退款 | 0.00 | -521.01 |
| 主营业务收入 | 5,167,898.42 | 341,206.98 |
| DWS到ADS双向差异 | 0 | 0 |

抖音2026年6月主营业务收入为705,729.76元，其中商品销售收入
709,888.78元、平台补贴10,071.67元、销售退款-14,230.69元。
快手2026年6月主营业务收入为200,193.49元，其中结算口径
200,714.50元、超售后期资金补充退款-521.01元。

共享主营业务收入ADS当前共1,209行，日期范围为2026-04-01至2026-07-05，
已覆盖抖音、快手、京东、天猫、拼多多、视频号和小红书七个平台；
未匹配公司数为0。连续两次全量刷新结果完全一致。

## 9.17 七平台结算收入、支出和结算净额月度透视表

### 指标口径与链路

该月度表不新增ODS来源，也不改变各平台结算收入、支出和净额的业务口径，
直接把七平台共享结算净额日ADS按自然月汇总。`stat_month`为自然月首日，
月度结算净额继续使用收入减支出，源结算金额和核验差额仅用于审计。

```text
ads.ads_settlement_net_company_shop_daily
  -> ads.ads_settlement_net_company_shop_monthly
  -> ads.v_settlement_net_company_shop_monthly_metric
  -> DataEase月度透视表
```

月度底表粒度为`stat_month + platform_code + company_code + shop_code`，
主键为上述四个字段；金额字段为`income_amount`、`expense_amount`和
`settlement_net_amount`。月度展开视图使用固定的三类指标：
`income/收入`、`expense/支出`、`settlement_net/结算净额`，并保留
`metric_order`用于稳定排序。

### DataEase配置

- 数据集：`ads.v_settlement_net_company_shop_monthly_metric`。
- 透视表行维度：`platform_name -> shop_name -> metric_name`。
- 透视表列维度：`stat_month`，显示格式建议为`yyyy年M月`或`yyyy-MM`。
- 透视表指标：`SUM(amount)`，金额保留两位小数。
- 行排序：按`platform_name`、`shop_name`，指标按`metric_order`升序；
  `metric_order`可作为隐藏排序字段。
- 公共筛选器：`company_name`、`platform_name`、`shop_name`和`stat_month`。

这样可以得到“平台 / 店铺 / 收入、支出、结算净额”作为行，月份和总计作为列的
透视效果。不要在DataEase中分别关联收入、支出和净额三张日表，否则会产生
多表关联重复；只读取上述月度视图。

### 刷新命令与当前验收

七个平台结算任务完成后由共享收口ETL统一刷新月度底表和视图；也可以在各平台
DWS已更新后手工执行：

```powershell
.\.venv\Scripts\python.exe -m etl.platform_finance.run_settlement_shared_ads_etl
```

该任务在同一事务内依次刷新三张共享日ADS、月度底表并重建视图，校验日ADS到
月度底表双向差异、三类指标总额和视图行数。当前数据库验收结果为：月度底表
6行、视图18行，月份为2026-08-01，收入2,913,660.54元，支出482,860.14元，
结算净额2,430,800.40元，源金额核验差额0.00元，未匹配公司0行；连续两次刷新
结果一致。

### 拼多多结算退款归属和支出展示

拼多多结算收入保留全部原收入；原始账务类型为“退款”的流水（包含该类型下的运费补偿），
以及“优惠券结算”中业务编码为`0020005`的退款，按来源负号移入收入侧冲减。
`0010005`优惠券收入继续计入收入。移入收入的退款不再重复计入支出，提现和广告账户转账
仍保留在结算支出中。该规则在拼多多结算DWS执行，与资金经营归属及费用分类映射独立。

共用底表的`expense_amount`继续使用正向支出，内部净额为`income_amount - expense_amount`。
拼多多DWS另输出`display_expense_amount = -expense_amount`；日ADS和月ADS只传递并汇总此字段。
月度透视视图的支出`amount`优先使用来源指定的展示金额；来源未指定时沿用原支出金额，
因此其他平台展示保持原有口径。DataEase继续读取同一视图的`SUM(amount)`，净额读取独立
`settlement_net`指标，不从展示金额重算内部公式。

养颜轻食2026年9月已确认的验收基准：结算收入234,878.24元、展示支出-236,893.79元、
结算净额-2,015.55元。该月1,322条退款流水共-120,432.21元从支出移至收入，原始15,819条
流水全部保留。拼多多结算ETL会同步刷新月度底表，并校验退款日类型归属、事件数量、
日/月双向差异和视图金额。

## 10. 新指标交付清单

- 指标口径与 ODS 探查结果。
- 三层表结构、刷新 SQL 和一键 ETL。
- 表注释及全字段注释。
- DWD抽样结果、DWS筛选数量、ADS最终汇总和主键检查。
- DataEase 数据集、指标卡和图表字段配置。
- 文档中的刷新命令、基准值和后续平台扩展位置。
