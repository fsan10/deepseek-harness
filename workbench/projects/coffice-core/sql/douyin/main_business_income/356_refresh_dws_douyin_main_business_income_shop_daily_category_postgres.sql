TRUNCATE TABLE dws.dws_douyin_main_business_income_shop_daily_category;

WITH income_event AS (
    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        CASE
            WHEN d.settlement_type LIKE '结算后退款%'
                THEN 'sales_refund'
            WHEN component.component_code = 'user_payment'
                THEN 'product_sales_income'
            ELSE 'platform_subsidy'
        END::VARCHAR(64) AS primary_category_code,
        CASE
            WHEN d.settlement_type LIKE '结算后退款%'
                THEN '销售退款'
            WHEN component.component_code = 'user_payment'
                THEN '商品销售收入'
            ELSE '平台补贴'
        END::VARCHAR(128) AS primary_category_name,
        CASE
            WHEN d.settlement_type LIKE '结算后退款%'
                THEN ('refund_' || component.component_code)
            ELSE component.component_code
        END::VARCHAR(128) AS secondary_category_code,
        component.component_name::VARCHAR(768) AS secondary_category_name,
        'settlement'::VARCHAR(32) AS source_document_type,
        component.component_amount AS income_amount,
        d.source_updated_at
    FROM dwd.dwd_douyin_main_business_income_source_detail d
    CROSS JOIN LATERAL (
        VALUES
            ('user_payment', '用户实付', d.user_payment_amount),
            ('platform_subsidy', '平台补贴', d.platform_subsidy_amount),
            ('other_platform_subsidy', '其他平台补贴', d.other_platform_subsidy_amount),
            ('government_platform_advance', '政府补贴平台垫资', d.government_platform_advance_amount),
            ('talent_subsidy', '达人补贴', d.talent_subsidy_amount),
            ('douyin_pay_subsidy', '抖音支付补贴', d.douyin_pay_subsidy_amount),
            ('douyin_monthly_pay_subsidy', '抖音月付营销补贴', d.douyin_monthly_pay_subsidy_amount),
            ('bank_subsidy', '银行补贴', d.bank_subsidy_amount),
            ('trade_in_deduction', '以旧换新抵扣', d.trade_in_deduction_amount),
            ('platform_shipping_subsidy', '平台补贴运费', d.platform_shipping_subsidy_amount)
    ) component(component_code, component_name, component_amount)
    WHERE component.component_amount <> 0
)
INSERT INTO dws.dws_douyin_main_business_income_shop_daily_category (
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
    primary_category_code,
    MAX(primary_category_name),
    secondary_category_code,
    MAX(secondary_category_name),
    source_document_type,
    ROUND(SUM(income_amount), 2),
    COUNT(*),
    MAX(source_updated_at),
    NOW()
FROM income_event
GROUP BY
    stat_date,
    platform_code,
    shop_code,
    primary_category_code,
    secondary_category_code,
    source_document_type;
