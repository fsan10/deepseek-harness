# 七平台双来源职责控制实施验收报告

验收日期：2026-08-10  
数据库：PostgreSQL `mock_coffice`  
数据范围：仅数据库现有 ODS；未导入 `C:\Users\win\Desktop\data` 或其他新样本，未修改、删除或覆盖 ODS。

## 1. 实施内容

- 新增`sql/dim/373_dim_platform_finance_source_policy_postgres.sql`，为`dim.dim_platform_fee_mapping`增加`source_role`、`metric_role`、`dedup_rule_code`。
- 七个平台费用DWS仅允许`PRIMARY`、`SUPPLEMENT`、`EXPENSE_OFFSET`且`include_in_platform_expense=true`的映射进入计算。
- 五组平台财务ETL显式执行来源职责SQL；一级、二级分类仍由财务维护，系统职责字段不覆盖财务分类。
- 共享主营业务收入ADS与平台费用ADS表结构、筛选字段和DataEase取数方式不变。

## 2. 来源职责验收

| 来源职责 | 计算角色 | 映射数 | 计入费用 |
|---|---|---:|---:|
| `PRIMARY` | `PLATFORM_EXPENSE` | 62 | 62 |
| `SUPPLEMENT` | `PLATFORM_EXPENSE` | 16 | 16 |
| `EXPENSE_OFFSET` | `EXPENSE_OFFSET` | 13 | 13 |
| `PRIMARY` | `MAIN_REVENUE` | 7 | 0 |
| `PRIMARY` | `MAIN_REFUND` | 5 | 0 |
| `REFUND_SUPPLEMENT` | `MAIN_REFUND` | 2 | 0 |
| `RECONCILIATION` | `RECONCILIATION` | 14 | 0 |
| `DUPLICATE` | `RECONCILIATION` | 2 | 0 |
| `ACCOUNT_TRANSFER` | `ACCOUNT_TRANSFER` | 6 | 0 |
| `PRIMARY` | `EXCLUDE` | 2 | 0 |
| **合计** | — | **129** | **91** |

校验结果：明确排除38条，`UNMAPPED=0`，计费规则使用非法来源职责为0，计费开关与计算角色冲突为0。

## 3. DWD粒度

| 指标 | 平台 | DWD行数 | 主键重复 | 日期范围 |
|---|---|---:|---:|---|
| 平台费用 | 抖音 | 253,624 | 0 | 2026-04-01～2026-07-05 |
| 平台费用 | 快手 | 27,929 | 0 | 2026-05-01～2026-06-30 |
| 平台费用 | 京东 | 1,819 | 0 | 2026-05-01～2026-07-05 |
| 平台费用 | 天猫 | 15,983 | 0 | 2026-06-01～2026-06-30 |
| 平台费用 | 拼多多 | 21,704 | 0 | 2026-05-01～2026-05-31 |
| 平台费用 | 视频号 | 4,206 | 0 | 2026-05-01～2026-07-02 |
| 平台费用 | 小红书 | 1,032 | 0 | 2026-05-01～2026-05-31 |
| 主营收入 | 抖音 | 34,654 | 0 | 2026-04-01～2026-06-30 |
| 主营收入 | 快手 | 5,452 | 0 | 2026-05-01～2026-06-30 |
| 主营收入 | 京东 | 1,819 | 0 | 2026-05-01～2026-07-05 |
| 主营收入 | 天猫 | 15,983 | 0 | 2026-06-01～2026-06-30 |
| 主营收入 | 拼多多 | 21,704 | 0 | 2026-05-01～2026-05-31 |
| 主营收入 | 视频号 | 4,206 | 0 | 2026-05-01～2026-07-02 |
| 主营收入 | 小红书 | 287 | 0 | 2026-05-01～2026-05-31 |

## 4. ADS改造前后比对

### 主营业务收入

| 平台 | 行数 | 金额 | 改造后有序行摘要 | 与改造前 |
|---|---:|---:|---|:---:|
| 抖音 | 533 | 5,167,898.42 | `ed70039ffcecca56090994976435acfe` | 一致 |
| 快手 | 219 | 341,206.98 | `9f9c373ece03466621b5fe1793f15df9` | 一致 |
| 京东 | 75 | 31,434.32 | `dff6c8b8f7baad406f1f3bc91f773a6b` | 一致 |
| 天猫 | 72 | 263,482.38 | `98a4d34af980b803e8f86d87315da871` | 一致 |
| 拼多多 | 124 | 315,100.14 | `fdff1cadfc8ac38b2a97d7881e0d33f6` | 一致 |
| 视频号 | 139 | 157,073.56 | `5f042523655ea48a05d038901e2273c5` | 一致 |
| 小红书 | 47 | 25,808.05 | `b53bfe9f3879580c0ea27759bd83046a` | 一致 |
| **合计** | **1,209** | **6,302,003.85** | — | **一致** |

### 平台费用

| 平台 | 行数 | 金额 | 改造后有序行摘要 | 与改造前 |
|---|---:|---:|---|:---:|
| 抖音 | 283 | 482,787.03 | `e233f04dd70eed2f5a751029d98d4330` | 一致 |
| 快手 | 549 | 130,998.35 | `47b6f69d002203ee61855cb6a9a4601f` | 一致 |
| 京东 | 311 | 11,320.09 | `e552942f85a1184b1fda99f46d3bd835` | 一致 |
| 天猫 | 553 | 31,341.61 | `7a9b2206be3fabdedb6361073595ccfc` | 一致 |
| 拼多多 | 192 | 6,356.68 | `24422f070153d54f59af9aa4b7c5dcb0` | 一致 |
| 视频号 | 145 | 41,027.60 | `7098422f592a6ec6d28053159fcefb92` | 一致 |
| 小红书 | 114 | 10,828.45 | `8e248930d0bbfba78d1c1f29d397c0ac` | 一致 |
| **合计** | **2,147** | **714,659.81** | — | **一致** |

两张ADS日期范围均保持2026-04-01～2026-07-05；主营收入和平台费用DWS到ADS双向差异均为0，ADS重复主键均为0，公司未匹配均为0。

## 5. 追溯抽样

| 职责 | 平台与场景 | 样例金额 | 处理结果 |
|---|---|---:|---|
| `PRIMARY` | 抖音结算单达人佣金，订单6951559520231429549 | 2.95 | 计入费用 |
| `SUPPLEMENT` | 抖音资金单小额打款，订单6927124656498310506 | 3.00 | 计入费用 |
| `EXPENSE_OFFSET` | 京东挽单补偿险理赔 | -5.50 | 冲减运费保险 |
| `REFUND_SUPPLEMENT` | 京东订单3540436016871273结算后退款 | -85.34 | 冲减主营收入 |
| `DUPLICATE` | 快手订单2615400613213943结算后退款 | -10.00 | 结算单已体现，只作勾稽 |
| `RECONCILIATION` | 京东商户结算批次202607050000011432890400031 | 161.15 | 只作结算到账对账 |
| `ACCOUNT_TRANSFER` | 拼多多提现申请 | 44,000.00 | 不计平台费用 |
| 零值组件 | 快手快赚客佣金 | 0.00 | DWD保留，ADS不产生金额行 |

## 6. 执行与幂等性

以下ETL均使用数据库现有ODS并启用专项基准校验，连续执行两轮成功：

```powershell
python etl/douyin/run_douyin_platform_expense_etl.py --enforce-current-baseline
python etl/ks/run_ks_platform_expense_etl.py --enforce-current-baseline
python etl/jd/run_jd_main_business_finance_etl.py --enforce-current-baseline
python etl/tmall/run_tmall_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_pdd_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_wechat_channels_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_xhs_main_business_finance_etl.py --enforce-current-baseline
python etl/platform_finance/run_douyin_ks_main_business_income_etl.py --enforce-current-baseline
```

第二轮两张ADS的逐平台行数、日期、金额和有序行摘要与第一轮及改造前完全相同。新增DIM字段、两张共享ADS及其全部字段注释均完整。

## 7. 结论

双来源职责控制已生效：两张原始单据仍完整保留，但只有主来源、明确补充和费用冲减可进入平台费用；结算到账、重复退款、勾稽资金过程和账户划转不会因资金方向被误计。当前DataEase继续读取原两张ADS，无需修改现有指标卡或筛选器，且所有现有指标结果保持不变。
