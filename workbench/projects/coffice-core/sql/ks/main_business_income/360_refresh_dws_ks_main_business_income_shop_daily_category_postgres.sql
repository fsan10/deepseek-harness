TRUNCATE TABLE dws.dws_ks_main_business_income_shop_daily_category;

WITH settlement_income_event AS (
    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        component.primary_category_code,
        component.primary_category_name,
        component.secondary_category_code,
        component.secondary_category_name,
        'settlement'::VARCHAR(32) AS source_document_type,
        component.income_amount,
        d.source_updated_at
    FROM dwd.dwd_ks_main_business_income_source_detail d
    CROSS JOIN LATERAL (
        VALUES
            (
                'product_sales_income'::VARCHAR(64),
                '商品销售收入'::VARCHAR(128),
                'order_paid'::VARCHAR(128),
                '订单实付(元)'::VARCHAR(768),
                d.order_paid_amount
            ),
            (
                'platform_subsidy',
                '平台补贴',
                'government_subsidy',
                '政府补贴',
                d.government_subsidy_amount
            ),
            (
                'platform_subsidy',
                '平台补贴',
                'payment_marketing_subsidy',
                '支付营销补贴',
                d.payment_marketing_subsidy_amount
            ),
            (
                'platform_subsidy',
                '平台补贴',
                'platform_subsidy',
                '平台补贴',
                d.platform_subsidy_amount
            ),
            (
                'platform_subsidy',
                '平台补贴',
                'talent_subsidy',
                '达人补贴',
                d.talent_subsidy_amount
            ),
            (
                'merchant_subsidy',
                '商家补贴',
                'merchant_subsidy',
                '商家补贴(元)',
                -d.merchant_subsidy_amount
            ),
            (
                'sales_refund',
                '销售退款',
                'order_refund',
                '订单退款(元)',
                -d.order_refund_amount
            )
    ) component(
        primary_category_code,
        primary_category_name,
        secondary_category_code,
        secondary_category_name,
        income_amount
    )
    WHERE d.source_document_type = 'settlement'
      AND component.income_amount <> 0
),
fund_refund_event AS (
    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        'sales_refund'::VARCHAR(64) AS primary_category_code,
        '销售退款'::VARCHAR(128) AS primary_category_name,
        'fund_deduction_shop_refund'::VARCHAR(128)
            AS secondary_category_code,
        (
            d.source_business_type || ' + ' || d.source_description
        )::VARCHAR(768) AS secondary_category_name,
        'fund'::VARCHAR(32) AS source_document_type,
        d.signed_fund_amount AS income_amount,
        d.source_updated_at
    FROM dwd.dwd_ks_main_business_income_source_detail d
    WHERE d.source_document_type = 'fund'
      AND d.source_direction = '支'
      AND d.source_business_type = '资金扣减'
      AND d.source_description = '快手小店退款'
      AND d.related_order_no IS NOT NULL
      AND d.signed_fund_amount < 0
      AND NOT EXISTS (
          SELECT 1
          FROM dwd.dwd_ks_main_business_income_source_detail settlement
          WHERE settlement.source_document_type = 'settlement'
            AND settlement.order_no = d.related_order_no
            AND settlement.shop_identity_key = d.shop_identity_key
            AND settlement.order_refund_amount > 0
      )
),
income_event AS (
    SELECT * FROM settlement_income_event
    UNION ALL
    SELECT * FROM fund_refund_event
)
INSERT INTO dws.dws_ks_main_business_income_shop_daily_category (
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
