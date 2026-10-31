TRUNCATE TABLE dws.dws_tmall_main_business_income_shop_daily_category;

INSERT INTO dws.dws_tmall_main_business_income_shop_daily_category (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    primary_category_code,
    primary_category_name,
    secondary_category_code,
    secondary_category_name,
    source_document_type,
    income_amount,
    included_detail_count,
    source_updated_at,
    updated_at
)
SELECT
    stat_date,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    CASE standardized_note
        WHEN '订单收款' THEN 'sales_income'
        WHEN '销售退款' THEN 'sales_refund'
    END,
    CASE standardized_note
        WHEN '订单收款' THEN '商品销售收入'
        WHEN '销售退款' THEN '销售退款'
    END,
    CASE
        WHEN source_account_type = 'aggregate'
         AND standardized_note = '订单收款'
            THEN 'tmall_aggregate_order_receipt'
        WHEN source_account_type = 'alipay'
         AND standardized_note = '订单收款'
            THEN 'tmall_alipay_order_receipt'
        WHEN source_account_type = 'aggregate'
         AND standardized_note = '销售退款'
            THEN 'tmall_aggregate_sales_refund'
        WHEN source_account_type = 'alipay'
         AND standardized_note = '销售退款'
            THEN 'tmall_alipay_sales_refund'
    END,
    secondary_category_name,
    'fund',
    ROUND(SUM(signed_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_main_business_income_source_detail
WHERE standardized_note IN ('订单收款', '销售退款')
GROUP BY
    stat_date,
    platform_code,
    shop_code,
    source_account_type,
    standardized_note,
    secondary_category_name;

