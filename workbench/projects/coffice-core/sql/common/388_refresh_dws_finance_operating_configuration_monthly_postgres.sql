TRUNCATE TABLE dws.dws_finance_operating_shop_monthly;
INSERT INTO dws.dws_finance_operating_shop_monthly
(budget_month,platform_code,platform_name,company_code,company_name,shop_code,shop_name,promotion_budget_amount,gsv_target_amount,recharge_amount,pending_recharge_amount,over_recharge_amount,recharge_count,source_updated_at)
WITH months AS (
    SELECT DISTINCT budget_month
    FROM dwd.dwd_finance_operating_configuration_detail
    UNION
    SELECT DATE_TRUNC('month', CURRENT_DATE)::date
), dim_rows AS (
    SELECT m.budget_month,d.platform_code,d.platform_name,d.company_code,d.company_name,
           d.shop_code,d.shop_name,d.updated_at AS dim_updated_at
    FROM months m
    JOIN dim.dim_platform_shop_company d
      ON (d.is_active OR m.budget_month < DATE_TRUNC('month', CURRENT_DATE)::date)
     AND (CASE WHEN m.budget_month=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE m.budget_month END)>=d.valid_from
     AND (d.valid_to IS NULL OR (CASE WHEN m.budget_month=DATE_TRUNC('month', CURRENT_DATE)::date THEN CURRENT_DATE ELSE m.budget_month END)<=d.valid_to)
), plans AS (
    SELECT budget_month,platform_code,company_code,shop_code,
           SUM(promotion_budget_amount) AS promotion_budget_amount,
           SUM(gsv_target_amount) AS gsv_target_amount,
           MAX(source_updated_at) AS source_updated_at
    FROM dwd.dwd_finance_operating_configuration_detail
    WHERE event_type='shop_plan'
    GROUP BY 1,2,3,4
), recharges AS (
    SELECT budget_month,platform_code,company_code,shop_code,
           SUM(recharge_amount) AS recharge_amount,
           COUNT(*) AS recharge_count,
           MAX(source_updated_at) AS source_updated_at
    FROM dwd.dwd_finance_operating_configuration_detail
    WHERE event_type='recharge'
    GROUP BY 1,2,3,4
)
SELECT d.budget_month,d.platform_code,d.platform_name,d.company_code,d.company_name,d.shop_code,d.shop_name,
       COALESCE(p.promotion_budget_amount,0),COALESCE(p.gsv_target_amount,0),COALESCE(r.recharge_amount,0),
       COALESCE(p.promotion_budget_amount,0)-COALESCE(r.recharge_amount,0),
       GREATEST(COALESCE(r.recharge_amount,0)-COALESCE(p.promotion_budget_amount,0),0),
       COALESCE(r.recharge_count,0),GREATEST(d.dim_updated_at,p.source_updated_at,r.source_updated_at)
FROM dim_rows d
LEFT JOIN plans p ON p.budget_month=d.budget_month AND p.platform_code=d.platform_code
                 AND p.company_code=d.company_code AND p.shop_code=d.shop_code
LEFT JOIN recharges r ON r.budget_month=d.budget_month AND r.platform_code=d.platform_code
                      AND r.company_code=d.company_code AND r.shop_code=d.shop_code;
TRUNCATE TABLE dws.dws_finance_operating_global_monthly;
INSERT INTO dws.dws_finance_operating_global_monthly
(budget_month,gsv_target_amount,initial_promotion_budget_amount,approved_adjustment_amount,effective_promotion_budget_amount,allocated_promotion_budget_amount,unallocated_promotion_budget_amount,recharge_amount,pending_recharge_amount,marketing_budget_amount,marketing_expense_amount,marketing_remaining_amount,source_updated_at)
SELECT m.budget_month,COALESCE(c.gsv_target_amount,0),COALESCE(c.promotion_budget_amount,0),COALESCE(a.adjustment_amount,0),COALESCE(c.promotion_budget_amount,0)+COALESCE(a.adjustment_amount,0),COALESCE(s.allocated_amount,0),COALESCE(c.promotion_budget_amount,0)+COALESCE(a.adjustment_amount,0)-COALESCE(s.allocated_amount,0),COALESCE(s.recharge_amount,0),COALESCE(c.promotion_budget_amount,0)+COALESCE(a.adjustment_amount,0)-COALESCE(s.recharge_amount,0),COALESCE(c.marketing_budget_amount,0),COALESCE(e.expense_amount,0),COALESCE(c.marketing_budget_amount,0)-COALESCE(e.expense_amount,0),GREATEST(c.source_updated_at,a.source_updated_at,s.source_updated_at,e.source_updated_at)
FROM (SELECT DISTINCT budget_month FROM dwd.dwd_finance_operating_configuration_detail UNION SELECT DATE_TRUNC('month',CURRENT_DATE)::date) m
LEFT JOIN (SELECT budget_month,SUM(gsv_target_amount) gsv_target_amount,SUM(promotion_budget_amount) promotion_budget_amount,SUM(marketing_budget_amount) marketing_budget_amount,MAX(source_updated_at) source_updated_at FROM dwd.dwd_finance_operating_configuration_detail WHERE event_type='monthly_control' GROUP BY 1)c USING(budget_month)
LEFT JOIN (SELECT budget_month,SUM(promotion_adjustment_amount) adjustment_amount,MAX(source_updated_at) source_updated_at FROM dwd.dwd_finance_operating_configuration_detail WHERE event_type='promotion_adjustment' GROUP BY 1)a USING(budget_month)
LEFT JOIN (SELECT budget_month,SUM(promotion_budget_amount) allocated_amount,SUM(recharge_amount) recharge_amount,MAX(source_updated_at) source_updated_at FROM dws.dws_finance_operating_shop_monthly GROUP BY 1)s USING(budget_month)
LEFT JOIN (SELECT budget_month,SUM(marketing_expense_amount) expense_amount,MAX(source_updated_at) source_updated_at FROM dwd.dwd_finance_operating_configuration_detail WHERE event_type='marketing_expense' GROUP BY 1)e USING(budget_month);
