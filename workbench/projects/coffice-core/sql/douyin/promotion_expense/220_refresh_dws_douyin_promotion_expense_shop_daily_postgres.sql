TRUNCATE TABLE dws.dws_douyin_promotion_expense_shop_daily;

INSERT INTO dws.dws_douyin_promotion_expense_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    qianchuan_non_gift_spend_amount,
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
    ROUND(SUM(COALESCE(non_gift_spend_amount, 0)), 2),
    ROUND(SUM(COALESCE(non_gift_spend_amount, 0)), 2),
    COUNT(*) FILTER (WHERE non_gift_spend_amount IS NOT NULL),
    COUNT(*) FILTER (WHERE non_gift_spend_amount IS NULL),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_douyin_promotion_expense_detail
WHERE expense_date IS NOT NULL
GROUP BY expense_date, platform_code, platform_name, shop_code, shop_name;
