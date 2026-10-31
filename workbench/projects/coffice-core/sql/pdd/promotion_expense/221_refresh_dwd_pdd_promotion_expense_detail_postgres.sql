DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ods.ods_pdd_promotion_expense_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'pdd'
           AND ctx.target_table = 'ods_pdd_promotion_expense_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
           OR (
                NULLIF(BTRIM(raw."店铺名称"), '') IS NOT NULL
                AND BTRIM(raw."店铺名称") <> ctx.shop_name
           )
    ) THEN
        RAISE EXCEPTION '拼多多推广费ODS存在未映射、冲突、未成功批次或源店铺名称冲突，停止刷新DWD';
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_pdd_promotion_expense_detail;

INSERT INTO dwd.dwd_pdd_promotion_expense_detail (
    source_record_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    expense_date,
    fund_type,
    flow_type,
    source_shop_name,
    transaction_amount,
    balance_amount,
    transaction_summary,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    raw.id,
    'pdd',
    '拼多多',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN LEFT(BTRIM(raw."时间"), 10) ~ '^\d{4}-\d{2}-\d{2}$'
            THEN LEFT(BTRIM(raw."时间"), 10)::date
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."资金类型"), ''),
    NULLIF(BTRIM(raw."流水类型"), ''),
    NULLIF(BTRIM(raw."店铺名称"), ''),
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."交易金额"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."交易金额"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."余额"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."余额"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    raw."交易摘要",
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_pdd_promotion_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'pdd'
   AND ctx.target_table = 'ods_pdd_promotion_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success';
