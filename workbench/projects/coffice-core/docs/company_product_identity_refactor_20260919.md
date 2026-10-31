# 公司商品身份与商品GMV分摊重构验收

## 业务模型

- `dim.dim_influencer_product.product_id`是不可随名称、分类或数量变化的系统商品身份。
- `company_product_code`是公司统一业务编码；平台和店铺只作为订单来源与观察维度。
- `dim.dim_company_product_code_mapping`一行表示一个全公司的去数量编码表达规则。`alias_code + quantity_position`全局唯一，不再使用平台、店铺优先级。
- 数量后缀、数量前缀和精确特殊编码分别由`suffix`、`prefix`、`none`表达。字母后缀保留，例如`M-MGNT`与`M-MGNT-XD`仍是两个商品。
- 组合编码先按`+`拆成组件。所有组件均保留、解析和映射；赠品的`paid_quantity`和`allocated_gmv_amount`为0，不进入付费数量分母。
- 产品ADS使用稳定`product_id + company_product_code`归集，保留平台、店铺和分类用于筛选与展示。

## 兼容与迁移

- 迁移脚本`sql/dim/427_refactor_company_product_identity_postgres.sql`把历史平台/店铺映射折叠为公司级规则，并把旧作用域保存到审计数组。
- `sql/dim/428_seed_company_product_alias_rules_postgres.sql`维护仓库中已确认的前缀数量缩写，包括`HB/TZ/FB/LH/BXTD/BXTF/SY/SYD/MG/MGD/ML/MLXYD`，并补充真实订单中的`MGNT`和`M-KKNT`别名。
- Excel加载器把尾部`-X`或正整数解释为数量，连续重复执行不会生成新规则。
- 购物金`A1/B2/C3`、预定有价券和红包继续作为`non_product`或`promotion`识别。本次未增加红包、购物金或优惠券扣减GMV算法。

## 页面与接口

- “商品品类配置”中的公司商品页以公司商品编码为第一列，维护名称、分类、类型和状态，并展示规则数、观察平台、店铺数、付费数量和GMV；内部稳定ID统一为`PRD-CODE-`加16位且不在业务列表展示。
- “商品编码映射”是唯一编码运营入口，同时展示编码表达、实际观察原始编码、平台、店铺、付费/赠品数量、GMV和公司商品归属。
- 原“原始商品编码”菜单已从达播运营、银行资金、数据导入和统一权限导航中删除；兼容查询接口仍返回统一工作台数据。
- 映射状态只有`mapped`、`unmapped`和`inactive`，不再产生`partial`。

## 2026-09-19数据库验收

| 验收项 | 结果 |
| --- | ---: |
| 公司商品 | 41 |
| 启用公司级编码规则 | 65 |
| 七平台商品组件 | 98,863 |
| 纯赠品组件 | 20,365 |
| 赠品非零GMV / 非零权重 | 0 / 0 |
| 商品ADS GMV | 7,791,906.12 |
| 映射状态 mapped / unmapped / partial | 66 / 1 / 0 |
| 同一编码表达命中多个商品 | 0 |

关键样例：

- `M-MGNT-1/-2/-3/-8/-10`均命中`PRD-CODE-A7E45952DD47CB46 / M-MGNT`，数量分别为1、2、3、8、10。
- 实际七个平台观察到的`M-MGNT-2`只命中上述同一个商品ID，平台不参与归属。
- `2MG`解析为`MG × 2`，经公司级别名命中同一`M-MGNT`商品。
- `M-MGNT-2+M-NXSY-3`按付费数量2:3分摊100元，结果为40元和60元。
- 真实京东组合`M-NXSY-2+M-MLXY-2+M-RYKK-1`、GMV 179元，规格含赠品时分摊为89.50、89.50、0。
- 特殊编码`A1/B2/C3`和`TMALL-PREORDER-VOUCHER`保持`non_product`，`M-MHB`保持`promotion`。

`M-CHK`已随黑咖啡公司商品创建自动归属；京东异常拼接赠品组件`M-RYKK-1M-NXSY-XD-1`已通过可维护的公司级修正规则拆为`M-RYKK-1`和`M-NXSY-XD-1`，两者均正常映射、赠品GMV均为0。当前仅剩天猫字面值`UNMAPPED`一个待处理编码族，按业务确认暂不处理。

只读回归命令：

```powershell
.\.venv\Scripts\python.exe -m etl.operating_sales.validate_product_identity
```
