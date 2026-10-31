TRUNCATE TABLE dws.dws_wechat_channels_main_business_income_shop_daily_category;
TRUNCATE TABLE dws.dws_wechat_channels_platform_expense_shop_daily_category;

INSERT INTO dws.dws_wechat_channels_main_business_income_shop_daily_category (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    primary_category_code, primary_category_name, secondary_category_code,
    secondary_category_name, source_document_type, income_amount,
    included_detail_count, source_updated_at, updated_at
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name), d.shop_code,
    MAX(d.shop_name),
    CASE d.source_business_type
        WHEN '订单支付' THEN 'sales_income'
        WHEN '订单交易｜先用后付' THEN 'sales_income'
        WHEN '平台优惠补贴' THEN 'platform_subsidy'
        WHEN '订单退款' THEN 'sales_refund'
    END,
    CASE d.source_business_type
        WHEN '订单支付' THEN '商品销售收入'
        WHEN '订单交易｜先用后付' THEN '商品销售收入'
        WHEN '平台优惠补贴' THEN '平台补贴'
        WHEN '订单退款' THEN '销售退款'
    END,
    m.secondary_category_code,
    d.secondary_category_name,
    'settlement',
    ROUND(SUM(d.signed_amount), 2),
    COUNT(*),
    MAX(d.source_updated_at),
    NOW()
FROM dwd.dwd_wechat_channels_main_business_income_source_detail d
INNER JOIN dim.dim_platform_fee_mapping m
    ON m.platform_code=d.platform_code
   AND m.source_component_code IS NULL
   AND m.source_document_type='settlement'
   AND m.secondary_category_name=d.secondary_category_name

WHERE d.source_business_type IN (
    '订单支付', '订单交易｜先用后付', '平台优惠补贴', '订单退款'
)
GROUP BY d.stat_date, d.platform_code, d.shop_code,
         CASE d.source_business_type
            WHEN '订单支付' THEN 'sales_income'
            WHEN '订单交易｜先用后付' THEN 'sales_income'
            WHEN '平台优惠补贴' THEN 'platform_subsidy'
            WHEN '订单退款' THEN 'sales_refund'
         END,
         CASE d.source_business_type
            WHEN '订单支付' THEN '商品销售收入'
            WHEN '订单交易｜先用后付' THEN '商品销售收入'
            WHEN '平台优惠补贴' THEN '平台补贴'
            WHEN '订单退款' THEN '销售退款'
         END,
         m.secondary_category_code, d.secondary_category_name;

DO $$
DECLARE missing_scenes TEXT;
BEGIN
    SELECT STRING_AGG(d.secondary_category_name, E'\n' ORDER BY d.secondary_category_name)
    INTO missing_scenes
    FROM (SELECT DISTINCT secondary_category_name
          FROM dwd.dwd_wechat_channels_platform_expense_source_detail) d
    LEFT JOIN dim.dim_platform_fee_mapping m
      ON m.platform_code='wechat_channels'
     AND m.source_document_type='settlement'
     AND m.secondary_category_name=d.secondary_category_name

    WHERE m.mapping_id IS NULL;
    IF missing_scenes IS NOT NULL THEN
        RAISE EXCEPTION '视频号平台费用存在未映射场景：% ', E'\n' || missing_scenes;
    END IF;
END $$;

INSERT INTO dws.dws_wechat_channels_platform_expense_shop_daily_category (
    stat_date, platform_code, platform_name, shop_code, shop_name,
    primary_category_code, primary_category_name, secondary_category_code,
    secondary_category_name, source_document_type, expense_amount,
    included_detail_count, source_detail_count, source_updated_at,
    mapping_updated_at, updated_at
)
SELECT
    d.stat_date, d.platform_code, MAX(d.platform_name), d.shop_code,
    MAX(d.shop_name), m.primary_category_code, MAX(m.primary_category_name),
    m.secondary_category_code, d.secondary_category_name, 'settlement',
    ROUND(SUM(d.directional_expense_amount), 2),
    COUNT(*) FILTER (WHERE d.directional_expense_amount <> 0),
    COUNT(*), MAX(d.source_updated_at), MAX(m.updated_at), NOW()
FROM dwd.dwd_wechat_channels_platform_expense_source_detail d
INNER JOIN dim.dim_platform_fee_mapping m
    ON m.platform_code=d.platform_code
   AND m.source_component_code IS NULL
   AND m.source_document_type='settlement'
   AND m.secondary_category_name=d.secondary_category_name

WHERE m.include_in_platform_expense
  AND m.source_role IN ('PRIMARY', 'SUPPLEMENT', 'EXPENSE_OFFSET')
GROUP BY d.stat_date, d.platform_code, d.shop_code,
         m.primary_category_code, m.secondary_category_code,
         d.secondary_category_name;
