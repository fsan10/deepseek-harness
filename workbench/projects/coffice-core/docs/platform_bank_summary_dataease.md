# 平台与银行经营汇总看板 DataEase 配置

## 基础数据集

直接读取`ads.ads_platform_bank_total_revenue_company_daily_type`。该表已在公司、平台、日期和分类粒度汇总，不包含店铺字段。

公共筛选器：

- 开始日期参数：`start_date`
- 结束日期参数：`end_date`
- 公司多选参数：`company_codes`，字段为`company_code`

多选公司必须使用`IN ($[company_codes])`。所有参数条件都放在`$DE_PARAM{}`中，未传参数时由DataEase跳过该条件。
参数语法参考[DataEase SQL数据集动态参数说明](https://dataease.cn/docs/v2/user_manual/dataset_description/)。

## 指标卡自定义 SQL

### 总收入

```sql
SELECT
  ROUND(COALESCE(SUM(metric_amount), 0), 2) AS total_income
FROM ads.ads_platform_bank_total_revenue_company_daily_type
WHERE financial_direction_code = 'income'
AND $DE_PARAM{ stat_date >= TO_DATE('$[start_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ stat_date <= TO_DATE('$[end_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ company_code IN ($[company_codes]) }
```

### 总支出

```sql
SELECT
  ROUND(COALESCE(SUM(metric_amount), 0), 2) AS total_expense
FROM ads.ads_platform_bank_total_revenue_company_daily_type
WHERE financial_direction_code = 'expense'
AND $DE_PARAM{ stat_date >= TO_DATE('$[start_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ stat_date <= TO_DATE('$[end_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ company_code IN ($[company_codes]) }
```

### 经营结余

```sql
SELECT
  ROUND(
    COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'income'), 0)
    - COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'expense'), 0),
    2
  ) AS operating_surplus
FROM ads.ads_platform_bank_total_revenue_company_daily_type
WHERE 1 = 1
AND $DE_PARAM{ stat_date >= TO_DATE('$[start_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ stat_date <= TO_DATE('$[end_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ company_code IN ($[company_codes]) }
```

### 支出率

查询返回0到1之间的小数，DataEase字段格式设置为百分比并保留4位小数。总收入为0时返回`NULL`。

```sql
SELECT
  ROUND(
    COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'expense'), 0)
    / NULLIF(
        COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'income'), 0),
        0
      ),
    6
  ) AS expense_ratio
FROM ads.ads_platform_bank_total_revenue_company_daily_type
WHERE 1 = 1
AND $DE_PARAM{ stat_date >= TO_DATE('$[start_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ stat_date <= TO_DATE('$[end_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ company_code IN ($[company_codes]) }
```

### ROI

ROI口径固定为`总收入 / 总支出`，不是`经营结余 / 总支出`。总支出为0时返回`NULL`，数值后缀设置为“倍”。

```sql
SELECT
  ROUND(
    COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'income'), 0)
    / NULLIF(
        COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code = 'expense'), 0),
        0
      ),
    2
  ) AS roi
FROM ads.ads_platform_bank_total_revenue_company_daily_type
WHERE 1 = 1
AND $DE_PARAM{ stat_date >= TO_DATE('$[start_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ stat_date <= TO_DATE('$[end_date]', 'YYYY-MM-DD') }
AND $DE_PARAM{ company_code IN ($[company_codes]) }
```

## 第一版图表

| 图表 | 过滤条件 | 维度 | 指标 | 推荐展示 |
| --- | --- | --- | --- | --- |
| 收入分类构成 | `financial_direction_code='income'` | `primary_category_name` | `SUM(metric_amount)` | 降序横向条形图，显示金额和占比 |
| 支出分类构成 | `financial_direction_code='expense'` | `primary_category_name` | `SUM(metric_amount)` | 降序横向条形图，显示金额和占比 |
| 收入/支出趋势 | 无 | `stat_date` | `SUM(metric_amount)`，系列`financial_direction_name` | 双系列折线图 |

退款和冲回可能为负，因此构成图不使用饼图。独立推广账户费用显示为“独立推广费”，与平台费用表中的推广分类分别计入。

## 推荐的第二版指标和图表

- 收支同比或环比：数据覆盖完整后再启用，当前各来源月份不同，不宜直接比较缺失月份。
- 来源贡献：按`metric_group_name`展示平台主营收入、平台费用、独立推广费、银行收入、银行费用和银行成本。
- 平台经营结余排行：仅过滤`source_type_code='platform'`，按`platform_name`计算收入减支出。
- 公司经营结余排行：按`company_name`计算收入减支出，适合多公司总览。

当前不补零：银行覆盖2026年1月，平台主营收入和平台费用主要覆盖2026年4月至7月，独立推广费覆盖2026年6月至7月。看板需在显著位置注明来源覆盖范围。
