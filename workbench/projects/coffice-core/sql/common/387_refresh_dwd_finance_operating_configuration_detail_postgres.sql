DO $$
DECLARE missing_count BIGINT; conflict_count BIGINT;
BEGIN
  SELECT COUNT(*) INTO missing_count FROM (SELECT DISTINCT business_date,shop_code FROM (
    SELECT budget_month business_date,shop_code FROM config.finance_shop_plan_monthly WHERE deleted_at IS NULL
    UNION ALL SELECT recharge_date,shop_code FROM config.finance_promotion_recharge_detail WHERE deleted_at IS NULL
  ) source_rows) s WHERE NOT EXISTS (
    SELECT 1 FROM dim.dim_platform_shop_company d WHERE d.shop_code=s.shop_code
      AND (d.is_active OR s.business_date < DATE_TRUNC('month', CURRENT_DATE)::date)
      AND (CASE WHEN s.business_date=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE s.business_date END)>=d.valid_from
      AND (d.valid_to IS NULL OR (CASE WHEN s.business_date=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE s.business_date END)<=d.valid_to)
  );
  IF missing_count>0 THEN RAISE EXCEPTION '经营配置存在%条未匹配DIM的店铺记录',missing_count; END IF;
  SELECT COUNT(*) INTO conflict_count FROM (
    SELECT s.business_date,s.shop_code,COUNT(*) c FROM (SELECT DISTINCT business_date,shop_code FROM (
      SELECT budget_month business_date,shop_code FROM config.finance_shop_plan_monthly WHERE deleted_at IS NULL
      UNION ALL SELECT recharge_date,shop_code FROM config.finance_promotion_recharge_detail WHERE deleted_at IS NULL
    ) source_rows) s JOIN dim.dim_platform_shop_company d ON d.shop_code=s.shop_code
      AND (d.is_active OR s.business_date < DATE_TRUNC('month', CURRENT_DATE)::date)
      AND (CASE WHEN s.business_date=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE s.business_date END)>=d.valid_from
      AND (d.valid_to IS NULL OR (CASE WHEN s.business_date=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE s.business_date END)<=d.valid_to)
    GROUP BY s.business_date,s.shop_code HAVING COUNT(*)>1
  ) x;
  IF conflict_count>0 THEN RAISE EXCEPTION '经营配置存在%组店铺日期匹配到多条DIM',conflict_count; END IF;
END $$;
TRUNCATE TABLE dwd.dwd_finance_operating_configuration_detail;
INSERT INTO dwd.dwd_finance_operating_configuration_detail
(configuration_event_key,event_type,source_id,business_date,budget_month,gsv_target_amount,promotion_budget_amount,marketing_budget_amount,source_updated_at)
SELECT 'monthly_control:'||TO_CHAR(budget_month,'YYYYMM'),'monthly_control',NULL,budget_month,budget_month,gsv_target_amount,promotion_budget_amount,marketing_budget_amount,updated_at FROM config.finance_budget_monthly;
INSERT INTO dwd.dwd_finance_operating_configuration_detail
(configuration_event_key,event_type,source_id,business_date,budget_month,platform_code,platform_name,company_code,company_name,shop_code,shop_name,promotion_budget_amount,gsv_target_amount,source_updated_at)
SELECT 'shop_plan:'||p.shop_plan_id,'shop_plan',p.shop_plan_id,p.budget_month,p.budget_month,d.platform_code,d.platform_name,d.company_code,d.company_name,p.shop_code,d.shop_name,p.promotion_budget_amount,p.gsv_target_amount,p.updated_at
 FROM config.finance_shop_plan_monthly p JOIN dim.dim_platform_shop_company d ON d.shop_code=p.shop_code
   AND (d.is_active OR p.budget_month < DATE_TRUNC('month', CURRENT_DATE)::date)
   AND (CASE WHEN p.budget_month=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE p.budget_month END)>=d.valid_from
   AND (d.valid_to IS NULL OR (CASE WHEN p.budget_month=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE p.budget_month END)<=d.valid_to)
 WHERE p.deleted_at IS NULL;
INSERT INTO dwd.dwd_finance_operating_configuration_detail
(configuration_event_key,event_type,source_id,business_date,budget_month,platform_code,platform_name,company_code,company_name,shop_code,shop_name,recharge_amount,source_updated_at)
SELECT 'recharge:'||r.recharge_id,'recharge',r.recharge_id,r.recharge_date,DATE_TRUNC('month',r.recharge_date)::date,d.platform_code,d.platform_name,d.company_code,d.company_name,r.shop_code,d.shop_name,r.recharge_amount,r.updated_at
 FROM config.finance_promotion_recharge_detail r JOIN dim.dim_platform_shop_company d ON d.shop_code=r.shop_code
   AND (d.is_active OR r.recharge_date < DATE_TRUNC('month', CURRENT_DATE)::date)
   AND r.recharge_date>=d.valid_from AND (d.valid_to IS NULL OR r.recharge_date<=d.valid_to)
 WHERE r.deleted_at IS NULL;
INSERT INTO dwd.dwd_finance_operating_configuration_detail
(configuration_event_key,event_type,source_id,business_date,budget_month,promotion_adjustment_amount,approval_status,source_updated_at)
SELECT 'promotion_adjustment:'||adjustment_id,'promotion_adjustment',adjustment_id,adjustment_date,budget_month,CASE WHEN approval_status='approved' THEN adjustment_amount ELSE 0 END,approval_status,updated_at FROM config.finance_promotion_budget_adjustment WHERE deleted_at IS NULL;
INSERT INTO dwd.dwd_finance_operating_configuration_detail
(configuration_event_key,event_type,source_id,business_date,budget_month,marketing_expense_amount,source_updated_at)
SELECT 'marketing_expense:'||marketing_expense_id,'marketing_expense',marketing_expense_id,expense_date,DATE_TRUNC('month',expense_date)::date,expense_amount,updated_at FROM config.finance_marketing_expense_detail WHERE deleted_at IS NULL;
