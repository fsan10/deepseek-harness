CREATE TABLE IF NOT EXISTS ads.ads_finance_promotion_budget_company_shop_monthly (LIKE dws.dws_finance_operating_shop_monthly INCLUDING ALL);
CREATE TABLE IF NOT EXISTS ads.ads_finance_budget_global_monthly (LIKE dws.dws_finance_operating_global_monthly INCLUDING ALL);
ALTER TABLE ads.ads_finance_budget_global_monthly
    ADD COLUMN IF NOT EXISTS gsv_target_amount NUMERIC(18,2) NOT NULL DEFAULT 0;
COMMENT ON TABLE ads.ads_finance_promotion_budget_company_shop_monthly IS 'DataEase经营预算店铺月ADS；包含推广预算、GSV目标、充值和待充值额度，不重复存储实际GSV或实际推广费。';
COMMENT ON TABLE ads.ads_finance_budget_global_monthly IS 'DataEase经营预算整体月ADS；包含财务推广总控、整体营销预算与费用，不响应平台或店铺筛选。';
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN SELECT column_name FROM information_schema.columns WHERE table_schema='ads' AND table_name='ads_finance_promotion_budget_company_shop_monthly' LOOP
    EXECUTE format('COMMENT ON COLUMN ads.ads_finance_promotion_budget_company_shop_monthly.%I IS %L',r.column_name,
      CASE r.column_name WHEN 'budget_month' THEN '预算月份，月初日期，用作DataEase月度时间筛选。' WHEN 'promotion_budget_amount' THEN '店铺当月推广预算，单位元。' WHEN 'gsv_target_amount' THEN '财务设定的店铺当月GSV目标，单位元；实际GSV来自订单ADS。' WHEN 'recharge_amount' THEN '店铺当月累计已充值，单位元。' WHEN 'pending_recharge_amount' THEN '待充值额度=推广预算-累计充值，单位元，可为负。' ELSE '字段口径继承经营预算店铺月DWS；维度来自DIM，金额单位元。' END);
  END LOOP;
  FOR r IN SELECT column_name FROM information_schema.columns WHERE table_schema='ads' AND table_name='ads_finance_budget_global_monthly' LOOP
    EXECUTE format('COMMENT ON COLUMN ads.ads_finance_budget_global_monthly.%I IS %L',r.column_name,
      CASE r.column_name WHEN 'budget_month' THEN '预算月份，月初日期，用作DataEase月度时间筛选。' WHEN 'gsv_target_amount' THEN '财务设定的当月整体GSV总目标，单位元，不从店铺明细汇总。' WHEN 'effective_promotion_budget_amount' THEN '财务有效推广预算总额=月初预算+已审批调整，单位元。' WHEN 'pending_recharge_amount' THEN '整体待充值额度=有效预算-累计充值，单位元。' WHEN 'marketing_budget_amount' THEN '公司整体营销预算，单位元，不拆平台店铺。' WHEN 'marketing_expense_amount' THEN '公司整体手工营销费用，单位元，不含平台费用映射中的营销优惠。' ELSE '字段口径继承经营预算整体月DWS；金额单位元。' END);
  END LOOP;
END $$;
