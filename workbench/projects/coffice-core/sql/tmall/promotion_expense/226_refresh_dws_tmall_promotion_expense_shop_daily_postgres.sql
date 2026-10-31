TRUNCATE TABLE dws.dws_tmall_promotion_expense_shop_daily;

INSERT INTO dws.dws_tmall_promotion_expense_shop_daily (
    stat_date,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    taobao_union_spend_amount,
    wanxiangtai_spend_amount,
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
        WHERE source_type = 'taobao_union'
    ), 0), 2),
    ROUND(COALESCE(SUM(source_amount) FILTER (
        WHERE source_type = 'wanxiangtai'
          AND receipts_type = '支出'
          AND transaction_type = '扣款'
    ), 0), 2),
    ROUND(COALESCE(SUM(source_amount) FILTER (
        WHERE source_type = 'taobao_union'
           OR (
                source_type = 'wanxiangtai'
                AND receipts_type = '支出'
                AND transaction_type = '扣款'
           )
    ), 0), 2),
    COUNT(*) FILTER (
        WHERE source_type = 'taobao_union'
           OR (
                source_type = 'wanxiangtai'
                AND receipts_type = '支出'
                AND transaction_type = '扣款'
           )
    ),
    COUNT(*) FILTER (
        WHERE source_type = 'wanxiangtai'
          AND (
                receipts_type IS DISTINCT FROM '支出'
                OR transaction_type IS DISTINCT FROM '扣款'
          )
    ),
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_tmall_promotion_expense_detail
WHERE expense_date IS NOT NULL
  AND source_amount IS NOT NULL
GROUP BY expense_date, platform_code, platform_name, shop_code, shop_name;
