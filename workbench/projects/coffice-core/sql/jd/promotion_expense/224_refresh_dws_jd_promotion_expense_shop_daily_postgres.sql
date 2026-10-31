TRUNCATE TABLE dws.dws_jd_promotion_expense_shop_daily;

INSERT INTO dws.dws_jd_promotion_expense_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    jd_tong_spend_amount,
    jd_union_spend_amount,
    promotion_expense_amount,
    included_detail_count,
    excluded_detail_count,
    source_updated_at,
    updated_at
)
SELECT
    expense_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    ROUND(COALESCE(SUM(source_amount) FILTER (
        WHERE source_type = 'jd_tong' AND transaction_type = '全站营销扣费'
    ), 0), 2),
    ROUND(COALESCE(SUM(source_amount) FILTER (
        WHERE source_type = 'jd_union'
    ), 0), 2),
    ROUND(COALESCE(SUM(source_amount) FILTER (
        WHERE source_type = 'jd_union'
           OR (source_type = 'jd_tong' AND transaction_type = '全站营销扣费')
    ), 0), 2),
    COUNT(*) FILTER (
        WHERE source_type = 'jd_union'
           OR (source_type = 'jd_tong' AND transaction_type = '全站营销扣费')
    ),
    COUNT(*) FILTER (
        WHERE source_type = 'jd_tong' AND transaction_type IS DISTINCT FROM '全站营销扣费'
    ),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_jd_promotion_expense_detail
WHERE expense_date IS NOT NULL
  AND source_amount IS NOT NULL
GROUP BY expense_date, platform_code, platform_name, shop_code, shop_name;
