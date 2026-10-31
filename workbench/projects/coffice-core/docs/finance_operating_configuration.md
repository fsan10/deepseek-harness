# 经营预算、目标、充值与营销费用方案

## 已实现口径

- 实际 GSV 继续由订单指标 `ads.ads_gsv_company_daily` 计算，不分配、不封顶；实际值可以高于或低于目标。
- 月度 GSV、实际平台推广费和 ROI 统一由 `ads.ads_gsv_promotion_expense_company_shop_monthly` 提供；月度 ROI 按月度 GSV 除以月度实际推广费计算，不对日 ROI 或月 ROI 求和。
- 财务只手工维护月度 GSV 目标。目标粒度为月份 × 平台 × 公司 × 店铺，其中平台和公司由 `dim.dim_platform_shop_company` 根据店铺和日期取得。
- 推广预算由财务维护月度总额，部门或运营把预算维护到店铺。额外预算通过调整流水记录，只有“已通过”状态计入有效预算。
- 已充值额度按每次充值登记到店铺。店铺待充值额度 = 店铺推广预算 − 店铺累计充值；整体待充值额度 = 有效推广预算总额 − 全部店铺累计充值。结果允许为负，以暴露超预算充值。
- 实际推广费仍来自 `ads.ads_promotion_expense_company_shop_daily`，与预算、充值是三个独立概念。
- 营销预算与营销费用是公司整体口径，不拆平台、公司、部门或店铺；营销费用由财务手工登记，不等于平台费用映射中的“营销优惠费”。

## 数据链路

配置来源位于 `config`：

- `config.finance_budget_monthly`
- `config.finance_shop_plan_monthly`
- `config.finance_promotion_recharge_detail`
- `config.finance_promotion_budget_adjustment`
- `config.finance_marketing_expense_detail`

指标链路：

`config -> dwd.dwd_finance_operating_configuration_detail -> dws.dws_finance_operating_*_monthly -> ads.ads_finance_*_monthly`

DataEase 使用两张配置 ADS：

- `ads.ads_finance_promotion_budget_company_shop_monthly`：店铺预算、GSV 目标、累计充值、待充值。
- `ads.ads_finance_budget_global_monthly`：整体推广总控、预算调整、整体营销预算和营销费用。

DataEase 的 GSV 与实际推广费月度明细使用 `ads.ads_gsv_promotion_expense_company_shop_monthly`，粒度为“月份 × 平台 × 公司 × 店铺”，字段为：

- 月份：`stat_month`（自然月首日）
- 平台：`platform_name`
- 公司：`company_name`
- 店铺：`shop_name`
- 月度销售额：`gsv_amount`
- 实际推广费：`actual_promotion_expense_amount`
- ROI：`roi`（月度 GSV ÷ 月度实际推广费，单位为倍）

表格直接展示月度 `roi`。如果制作跨月份、跨平台或跨店铺的指标卡，ROI 使用 `SUM(gsv_amount) / SUM(actual_promotion_expense_amount)`，不要对 `roi` 字段使用 `SUM` 或 `AVG`。

## DataEase 店铺月度执行数据集（预算联动）

以下 SQL 直接关联月度实际指标和月度预算，避免日表 JOIN 导致月度金额或目标重复累加。筛选器使用编码。

```sql
WITH actual AS (
    SELECT stat_month AS budget_month,
           platform_code, platform_name,
           company_code, company_name,
           shop_code, shop_name,
           gsv_amount AS actual_gsv_amount,
           actual_promotion_expense_amount,
           roi
    FROM ads.ads_gsv_promotion_expense_company_shop_monthly
), keys AS (
    SELECT budget_month,platform_code,company_code,shop_code FROM ads.ads_finance_promotion_budget_company_shop_monthly
    UNION
    SELECT budget_month,platform_code,company_code,shop_code FROM actual
)
SELECT k.budget_month,
       COALESCE(b.platform_code,a.platform_code) AS platform_code,
       COALESCE(b.platform_name,a.platform_name) AS platform_name,
       COALESCE(b.company_code,a.company_code) AS company_code,
       COALESCE(b.company_name,a.company_name) AS company_name,
       COALESCE(b.shop_code,a.shop_code) AS shop_code,
       COALESCE(b.shop_name,a.shop_name) AS shop_name,
       COALESCE(b.promotion_budget_amount,0) AS promotion_budget_amount,
       COALESCE(b.gsv_target_amount,0) AS gsv_target_amount,
       COALESCE(b.recharge_amount,0) AS recharge_amount,
       COALESCE(b.pending_recharge_amount,0) AS pending_recharge_amount,
       COALESCE(a.actual_gsv_amount,0) AS actual_gsv_amount,
       COALESCE(a.actual_promotion_expense_amount,0) AS actual_promotion_expense_amount,
       a.roi,
       CASE WHEN COALESCE(b.gsv_target_amount,0)=0 THEN 0
            ELSE COALESCE(a.actual_gsv_amount,0)/b.gsv_target_amount END AS gsv_completion_rate
FROM keys k
LEFT JOIN ads.ads_finance_promotion_budget_company_shop_monthly b USING(budget_month,platform_code,company_code,shop_code)
LEFT JOIN actual a USING(budget_month,platform_code,company_code,shop_code)
WHERE
$DE_PARAM{ k.budget_month >= DATE_TRUNC('month',to_date('$[start_date]','yyyy-MM-dd'))::date }
AND $DE_PARAM{ k.budget_month <= DATE_TRUNC('month',to_date('$[end_date]','yyyy-MM-dd'))::date }
AND $DE_PARAM{ k.platform_code = '$[platform_code]' }
AND $DE_PARAM{ k.company_code = '$[company_code]' }
AND $DE_PARAM{ k.shop_code = '$[shop_code]' }
```

跨店铺指标卡必须使用 `SUM(actual_gsv_amount) / SUM(gsv_target_amount)`，不能平均各店铺完成率。ROI 指标卡必须使用 `SUM(actual_gsv_amount) / SUM(actual_promotion_expense_amount)`，不能平均或求和各行 `roi`。完成率允许超过 100%。整体营销指标只读取 `ads.ads_finance_budget_global_monthly`，不要关联店铺表，也不要绑定平台、公司或店铺筛选器。
