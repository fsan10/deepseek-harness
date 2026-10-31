TRUNCATE TABLE dws.dws_wechat_channels_settlement_expense_shop_daily_type;

INSERT INTO dws.dws_wechat_channels_settlement_expense_shop_daily_type (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    expense_type_code, expense_type_name, expense_amount, included_event_count,
    source_updated_at, updated_at
)
SELECT
    stat_date, platform_code, MAX(platform_name), shop_code, MAX(shop_name),
    CASE movement_type
        WHEN '订单支付' THEN 'order_payment'
        WHEN '订单交易｜先用后付' THEN 'pay_later_order_transaction'
        WHEN '订单退款' THEN 'order_refund'
        WHEN '达人佣金' THEN 'creator_commission'
        WHEN '技术服务费' THEN 'technical_service_fee'
        WHEN '运费险' THEN 'shipping_insurance'
        WHEN '提现' THEN 'withdrawal'
        WHEN '极速退款垫资' THEN 'fast_refund_advance'
        WHEN '回补极速退款垫资' THEN 'fast_refund_advance_repayment'
        WHEN '平台优惠补贴' THEN 'platform_discount_subsidy'
        WHEN '带货机构服务费' THEN 'agency_service_fee'
        ELSE 'wechat_channels_' || MD5(movement_type)
    END,
    movement_type, ROUND(SUM(expense_amount), 2), COUNT(*),
    MAX(source_updated_at), NOW()
FROM dwd.dwd_wechat_channels_settlement_expense_event_detail
WHERE expense_amount <> 0
GROUP BY stat_date, platform_code, shop_code, movement_type;

