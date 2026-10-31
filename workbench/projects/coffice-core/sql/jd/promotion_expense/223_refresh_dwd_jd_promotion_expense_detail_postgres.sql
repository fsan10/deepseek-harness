DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ods.ods_jd_tong_promotion_expense_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'jd'
           AND ctx.target_table = 'ods_jd_tong_promotion_expense_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
           OR (
                NULLIF(BTRIM(raw."投放账户ID"), '') IS NOT NULL
                AND BTRIM(raw."投放账户ID") <> ctx.shop_code
           )
    ) OR EXISTS (
        SELECT 1
        FROM ods.ods_jd_union_promotion_expense_raw raw
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
           AND ctx.platform_code = 'jd'
           AND ctx.target_table = 'ods_jd_union_promotion_expense_raw'
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
           OR (
                SUBSTRING(BTRIM(raw."流水单号") FROM '_([0-9]+)_') IS NOT NULL
                AND SUBSTRING(BTRIM(raw."流水单号") FROM '_([0-9]+)_') <> ctx.shop_code
           )
    ) THEN
        RAISE EXCEPTION '京东推广费ODS存在未映射、冲突、未成功批次或来源账号冲突，停止刷新DWD';
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_jd_promotion_expense_detail;

INSERT INTO dwd.dwd_jd_promotion_expense_detail (
    source_type,
    source_record_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    expense_date,
    transaction_id,
    transaction_type,
    settlement_status,
    settlement_type,
    source_amount,
    source_account_name,
    source_account_id,
    source_description,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'jd_tong',
    raw.id,
    'jd',
    '京东',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN LEFT(BTRIM(raw."结算时间"), 10) ~ '^\d{4}-\d{2}-\d{2}$'
            THEN LEFT(BTRIM(raw."结算时间"), 10)::date
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."流水单号"), ''),
    NULLIF(BTRIM(raw."交易类型"), ''),
    NULL,
    NULLIF(BTRIM(raw."开票方式"), ''),
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."支出"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."支出"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."投放账户名称"), ''),
    NULLIF(BTRIM(raw."投放账户ID"), ''),
    NULLIF(BTRIM(raw."投放日期"), ''),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_jd_tong_promotion_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_tong_promotion_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success'

UNION ALL

SELECT
    'jd_union',
    raw.id,
    'jd',
    '京东',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN LEFT(BTRIM(raw."结算时间"), 10) ~ '^\d{4}-\d{2}-\d{2}$'
            THEN LEFT(BTRIM(raw."结算时间"), 10)::date
        ELSE NULL
    END,
    NULLIF(BTRIM(raw."流水单号"), ''),
    '京东联盟结算',
    NULLIF(BTRIM(raw."状态"), ''),
    NULLIF(BTRIM(raw."结算类型"), ''),
    CASE
        WHEN REPLACE(NULLIF(NULLIF(BTRIM(raw."结算金额"), ''), '-'), ',', '')
             ~ '^-?[0-9]+(\.[0-9]+)?$'
            THEN ROUND(REPLACE(BTRIM(raw."结算金额"), ',', '')::numeric, 2)
        ELSE NULL
    END,
    NULL,
    SUBSTRING(BTRIM(raw."流水单号") FROM '_([0-9]+)_'),
    NULLIF(BTRIM(raw."费用时间"), ''),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM ods.ods_jd_union_promotion_expense_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_union_promotion_expense_raw'
   AND ctx.shop_mapping_status = 'mapped'
   AND ctx.ingest_status = 'success';
