TRUNCATE TABLE dwd.dwd_jd_main_business_income_source_detail;

WITH cleaned AS (
    SELECT
        raw.*, context.shop_identity_key AS source_shop_identity_key,
        NULLIF(
            REPLACE(REPLACE(BTRIM(raw."单据编号"), '="', ''), '"', ''),
            ''
        ) AS clean_document_no,
        NULLIF(
            REPLACE(REPLACE(BTRIM(raw."订单编号"), '="', ''), '"', ''),
            ''
        ) AS clean_order_no,
        NULLIF(
            REPLACE(REPLACE(BTRIM(raw."商户订单号"), '="', ''), '"', ''),
            ''
        ) AS clean_merchant_order_no,
        BTRIM(raw."账单日期") AS clean_bill_date,
        ROUND(REPLACE(BTRIM(raw."金额"), ',', '')::numeric, 2)
            AS parsed_signed_amount
    FROM common.v_selected_jd_settlement_raw raw
    JOIN common.v_ingest_batch_shop_context context ON context.batch_id=raw.batch_id
      AND context.platform_code='jd' AND context.target_table='ods_jd_settlement_raw'
),
latest AS (
    SELECT DISTINCT ON (source_shop_identity_key, clean_document_no) *
    FROM cleaned
    WHERE clean_document_no IS NOT NULL
    ORDER BY source_shop_identity_key, clean_document_no, ingest_time DESC, id DESC
)
INSERT INTO dwd.dwd_jd_main_business_income_source_detail (
    source_document_type,
    source_event_key,
    source_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    fee_item_name,
    document_type,
    flow_no,
    order_no,
    related_order_no,
    merchant_order_no,
    source_amount,
    signed_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'settlement',
    l.clean_document_no,
    l.id,
    'jd',
    '京东',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    CASE
        WHEN l.clean_bill_date ~ '^[0-9]{8}$'
            THEN TO_DATE(l.clean_bill_date, 'YYYYMMDD')
        WHEN l.clean_bill_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN l.clean_bill_date::date
    END,
    COALESCE(NULLIF(NULLIF(BTRIM(l."费用结算时间"), ''), '-')::timestamp,
            CASE WHEN l.clean_bill_date ~ '^[0-9]{8}$' THEN TO_DATE(l.clean_bill_date,'YYYYMMDD')
                 WHEN l.clean_bill_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN l.clean_bill_date::date END::timestamp),
    BTRIM(l."收支方向"),
    NULLIF(BTRIM(l."单据类型"), ''),
    NULL,
    NULLIF(BTRIM(l."费用项"), ''),
    NULLIF(BTRIM(l."单据类型"), ''),
    l.clean_document_no,
    l.clean_order_no,
    NULL,
    l.clean_merchant_order_no,
    ABS(l.parsed_signed_amount),
    l.parsed_signed_amount,
    l.batch_id,
    l.source_file_name,
    l.source_row_no,
    l.ingest_time,
    NOW()
FROM latest l
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = l.batch_id
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

WITH cleaned AS (
    SELECT
        raw.*, context.shop_identity_key AS source_shop_identity_key,
        MD5(
            CONCAT_WS(
                E'\x1f',
                BTRIM(COALESCE(raw."商户订单号", '')),
                BTRIM(COALESCE(raw."交易订单号", '')),
                BTRIM(COALESCE(raw."支出类型", '')),
                BTRIM(COALESCE(raw."交易金额", '')),
                BTRIM(COALESCE(raw."交易类型", '')),
                BTRIM(COALESCE(raw."入账时间", '')),
                BTRIM(COALESCE(raw."资金动账备注", ''))
            )
        ) AS event_key,
        ROUND(REPLACE(BTRIM(raw."交易金额"), ',', '')::numeric, 2)
            AS parsed_source_amount
    FROM common.v_selected_jd_fund_raw raw
    JOIN common.v_ingest_batch_shop_context context ON context.batch_id=raw.batch_id
      AND context.platform_code='jd' AND context.target_table='ods_jd_fund_raw'
),
latest AS (
    SELECT DISTINCT ON (source_shop_identity_key, event_key) *
    FROM cleaned
    ORDER BY source_shop_identity_key, event_key, ingest_time DESC, id DESC
)
INSERT INTO dwd.dwd_jd_main_business_income_source_detail (
    source_document_type,
    source_event_key,
    source_id,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    fee_item_name,
    document_type,
    flow_no,
    order_no,
    related_order_no,
    merchant_order_no,
    source_amount,
    signed_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'fund',
    l.event_key,
    l.id,
    'jd',
    '京东',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(l."入账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(l."入账时间"), ''), '-')::timestamp,
    BTRIM(l."支出类型"),
    BTRIM(l."交易类型"),
    NULLIF(BTRIM(l."资金动账备注"), ''),
    NULL,
    NULL,
    NULLIF(BTRIM(l."交易订单号"), ''),
    NULLIF(BTRIM(l."交易订单号"), ''),
    SUBSTRING(BTRIM(l."资金动账备注") FROM '对应订单号([0-9]+)'),
    NULLIF(BTRIM(l."商户订单号"), ''),
    l.parsed_source_amount,
    CASE BTRIM(l."支出类型")
        WHEN '收入' THEN l.parsed_source_amount
        WHEN '支出' THEN -l.parsed_source_amount
    END,
    l.batch_id,
    l.source_file_name,
    l.source_row_no,
    l.ingest_time,
    NOW()
FROM latest l
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = l.batch_id
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_fund_raw'
   AND ctx.shop_mapping_status = 'mapped';
