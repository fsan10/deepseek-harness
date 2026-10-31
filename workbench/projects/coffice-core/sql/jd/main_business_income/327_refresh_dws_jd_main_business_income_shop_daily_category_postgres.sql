TRUNCATE TABLE dws.dws_jd_main_business_income_shop_daily_category;

WITH income_event AS (
    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        'product_sales_income'::VARCHAR(64) AS primary_category_code,
        '商品销售收入'::VARCHAR(128) AS primary_category_name,
        'settlement_goods_order'::VARCHAR(128) AS secondary_category_code,
        d.fee_item_name::VARCHAR(768) AS secondary_category_name,
        d.source_document_type,
        d.signed_amount AS income_amount,
        d.source_updated_at
    FROM dwd.dwd_jd_main_business_income_source_detail d
    WHERE d.source_document_type = 'settlement'
      AND d.fee_item_name = '货款'
      AND d.document_type = '订单'

    UNION ALL

    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        'sales_refund'::VARCHAR(64),
        '销售退款'::VARCHAR(128),
        (
            'settlement_goods_refund_'
            || LEFT(MD5(d.document_type), 12)
        )::VARCHAR(128),
        d.fee_item_name::VARCHAR(768),
        d.source_document_type,
        d.signed_amount,
        d.source_updated_at
    FROM dwd.dwd_jd_main_business_income_source_detail d
    WHERE d.source_document_type = 'settlement'
      AND d.fee_item_name = '货款'
      AND d.document_type IN ('取消退款单', '售后服务单')

    UNION ALL

    SELECT
        d.stat_date,
        d.platform_code,
        d.platform_name,
        d.shop_code,
        d.shop_name,
        'sales_refund'::VARCHAR(64),
        '销售退款'::VARCHAR(128),
        (
            'fund_post_settlement_refund_'
            || LEFT(MD5(d.source_description), 12)
        )::VARCHAR(128),
        d.source_description::VARCHAR(768),
        d.source_document_type,
        d.signed_amount,
        d.source_updated_at
    FROM dwd.dwd_jd_main_business_income_source_detail d
    WHERE d.source_document_type = 'fund'
      AND d.source_business_type = '转账-售后退款质保金扣除'
      AND d.related_order_no IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM dwd.dwd_jd_main_business_income_source_detail settlement
          WHERE settlement.source_document_type = 'settlement'
            AND settlement.fee_item_name = '货款'
            AND settlement.document_type IN ('取消退款单', '售后服务单')
            AND settlement.order_no = d.related_order_no
            AND settlement.shop_identity_key = d.shop_identity_key
            AND settlement.signed_amount < 0
      )
)
INSERT INTO dws.dws_jd_main_business_income_shop_daily_category (
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
    secondary_category_name,
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
    secondary_category_name,
    source_document_type;

INSERT INTO dws.dws_jd_main_business_income_shop_daily_category (
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
    d.stat_date,
    d.platform_code,
    MAX(d.platform_name),
    d.shop_code,
    MAX(d.shop_name),
    'product_sales_income',
    '商品销售收入',
    'settlement_goods_order',
    '货款',
    'settlement',
    0,
    0,
    MAX(d.source_updated_at),
    NOW()
FROM dwd.dwd_jd_main_business_income_source_detail d
WHERE d.source_document_type = 'settlement'
  AND NOT EXISTS (
      SELECT 1
      FROM dws.dws_jd_main_business_income_shop_daily_category existing
      WHERE existing.stat_date = d.stat_date
        AND existing.platform_code = d.platform_code
        AND existing.shop_code = d.shop_code
  )
GROUP BY d.stat_date, d.platform_code, d.shop_code;
