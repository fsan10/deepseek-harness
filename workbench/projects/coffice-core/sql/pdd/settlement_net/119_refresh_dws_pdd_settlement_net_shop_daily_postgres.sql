TRUNCATE TABLE dws.dws_pdd_settlement_net_shop_daily;

INSERT INTO dws.dws_pdd_settlement_net_shop_daily (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    income_amount, expense_amount, display_expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount,
    included_event_count, source_updated_at, updated_at
)
WITH classified AS (
    SELECT d.*,
           CASE WHEN account_type = '退款'
                     OR (account_type = '优惠券结算'
                         AND SPLIT_PART(business_description, '|', 1) = '0020005')
                THEN source_signed_expense_amount ELSE 0
           END AS refund_amount
    FROM dwd.dwd_pdd_settlement_net_event_detail d
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    ROUND(SUM(income_amount + refund_amount), 2),
    ROUND(SUM(expense_amount + refund_amount), 2),
    ROUND(-SUM(expense_amount + refund_amount), 2),
    ROUND(SUM(income_amount) - SUM(expense_amount), 2),
    ROUND(SUM(source_settlement_amount), 2),
    ROUND(SUM(income_amount) - SUM(expense_amount) - SUM(source_settlement_amount), 2),
    COUNT(*), MAX(source_updated_at), NOW()
FROM classified
GROUP BY stat_date, platform_code, shop_code;

