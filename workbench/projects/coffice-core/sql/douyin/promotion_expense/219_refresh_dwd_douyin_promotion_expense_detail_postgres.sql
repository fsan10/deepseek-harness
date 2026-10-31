DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ods.ods_douyin_qianchuan_finance_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'douyin'
           AND ctx.target_table = 'ods_douyin_qianchuan_finance_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
    ) THEN
        RAISE EXCEPTION '抖音千川ODS存在未映射、冲突或未成功的来源批次，停止刷新DWD';
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_douyin_promotion_expense_detail;

INSERT INTO dwd.dwd_douyin_promotion_expense_detail (
    source_record_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    expense_date,
    non_gift_spend_amount,
    gift_spend_amount,
    source_date_text,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    raw.id,
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN NULLIF(BTRIM(raw."日期"), '') ~ '^\d{4}-\d{2}-\d{2}$'
            THEN BTRIM(raw."日期")::date
        ELSE NULL
    END,
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."非赠款消耗(元)"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."非赠款消耗(元)"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."赠款消耗(元)"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."赠款消耗(元)"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    raw."日期",
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_douyin_qianchuan_finance_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_qianchuan_finance_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success';
