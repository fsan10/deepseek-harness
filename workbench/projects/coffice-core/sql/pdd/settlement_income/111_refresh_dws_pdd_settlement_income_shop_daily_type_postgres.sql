TRUNCATE TABLE dws.dws_pdd_settlement_income_shop_daily_type;

INSERT INTO dws.dws_pdd_settlement_income_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_type_code, income_type_name, income_amount, included_event_count,
    source_updated_at, updated_at
)
WITH classified AS (
    SELECT d.*,
           income_amount + CASE
               WHEN account_type = '退款'
                 OR (account_type = '优惠券结算'
                     AND SPLIT_PART(business_description, '|', 1) = '0020005')
               THEN source_signed_expense_amount ELSE 0
           END AS settlement_income_amount
    FROM dwd.dwd_pdd_settlement_income_event_detail d
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
    ROUND(SUM(settlement_income_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM classified
WHERE settlement_income_amount <> 0
GROUP BY stat_date, platform_code, shop_code, account_type;

