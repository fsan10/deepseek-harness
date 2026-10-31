TRUNCATE TABLE dws.dws_pdd_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_pdd_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE account_type
        WHEN '交易收入' THEN 'transaction_income'
        WHEN '优惠券结算' THEN 'coupon_settlement'
        WHEN '技术服务费' THEN 'technical_service_fee'
        WHEN '其他服务' THEN 'other_service'
        WHEN '退款' THEN 'refund'
        WHEN '扣款' THEN 'deduction'
        WHEN '其他' THEN 'other'
        WHEN '转账' THEN 'transfer'
        WHEN '提现' THEN 'withdrawal'
        WHEN '分账' THEN 'profit_sharing'
        WHEN '多多进宝' THEN 'duoduo_promotion'
        ELSE 'pdd_' || MD5(account_type)
    END,
    account_type,
    ROUND(SUM(expense_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM dwd.dwd_pdd_settlement_expense_event_detail
WHERE expense_amount <> 0
  AND NOT (
      account_type = '退款'
      OR (account_type = '优惠券结算'
          AND COALESCE(SPLIT_PART(business_description, '|', 1), '') = '0020005')
  )
GROUP BY stat_date, platform_code, shop_code, account_type;

