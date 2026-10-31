DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ods.ods_tmall_taobao_union_promotion_expense_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'tmall'
           AND ctx.target_table = 'ods_tmall_taobao_union_promotion_expense_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
    ) OR EXISTS (
        SELECT 1
        FROM ods.ods_tmall_wanxiangtai_promotion_expense_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'tmall'
           AND ctx.target_table = 'ods_tmall_wanxiangtai_promotion_expense_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
    ) THEN
        RAISE EXCEPTION '天猫推广费ODS存在未映射、冲突或未成功的来源批次，停止刷新DWD';
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_tmall_promotion_expense_detail;

INSERT INTO dwd.dwd_tmall_promotion_expense_detail (
    source_type,
    source_record_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    expense_date,
    receipts_type,
    transaction_type,
    source_amount,
    source_description,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'taobao_union',
    raw.id,
    'tmall',
    '天猫',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN REPLACE(BTRIM(raw."日期"), E'\t', '') ~ '^\d{8}$'
            THEN TO_DATE(REPLACE(BTRIM(raw."日期"), E'\t', ''), 'YYYYMMDD')
        ELSE NULL
    END,
    NULL,
    '淘宝联盟结算',
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."结算支出费用(元)"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."结算支出费用(元)"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."结算笔数"), ''),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_tmall_taobao_union_promotion_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_taobao_union_promotion_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success'

UNION ALL

SELECT
    'wanxiangtai',
    raw.id,
    'tmall',
    '天猫',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN LEFT(BTRIM(raw."记账时间"), 10) ~ '^\d{4}-\d{2}-\d{2}$'
            THEN LEFT(BTRIM(raw."记账时间"), 10)::date
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."收支类型"), ''),
    NULLIF(BTRIM(raw."交易类型"), ''),
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."操作金额(元)"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."操作金额(元)"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    raw."备注",
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_tmall_wanxiangtai_promotion_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_wanxiangtai_promotion_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success';
