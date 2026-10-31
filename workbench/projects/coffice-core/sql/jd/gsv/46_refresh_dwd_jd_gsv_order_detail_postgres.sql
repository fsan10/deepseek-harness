TRUNCATE TABLE dwd.dwd_jd_gsv_order_detail;

INSERT INTO dwd.dwd_jd_gsv_order_detail (
    platform_code,
    platform_name,
    source_fulfillment_shop_code,
    source_order_shop_code,
    source_shop_name,
    shop_code,
    shop_name,
    shop_code_source,
    shop_identity_key,
    order_no,
    stat_date,
    stat_date_source,
    order_created_at,
    payment_confirmed_at,
    order_status,
    order_type,
    payable_amount,
    order_amount,
    merchant_receivable_amount,
    source_line_count,
    source_ids,
    source_batch_ids,
    source_file_names,
    source_sheet_names,
    source_row_nos,
    source_updated_at,
    updated_at
)
WITH source_normalized AS (
    SELECT
        id,
        batch_id,
        source_file_name,
        source_sheet_name,
        source_row_no,
        ingest_time,
        NULLIF(BTRIM("订单号"), '') AS order_no,
        NULLIF(NULLIF(BTRIM("履约门店ID"), ''), '-') AS source_fulfillment_shop_code,
        NULLIF(NULLIF(BTRIM("下单门店Id"), ''), '-') AS source_order_shop_code,
        NULLIF(NULLIF(BTRIM("门店名称"), ''), '-') AS source_shop_name,
        NULLIF(NULLIF(BTRIM("下单时间"), ''), '-')::timestamp AS order_created_at,
        NULLIF(NULLIF(BTRIM("付款确认时间"), ''), '-')::timestamp AS payment_confirmed_at,
        NULLIF(BTRIM("订单状态"), '') AS order_status,
        NULLIF(BTRIM("订单类型"), '') AS order_type,
        NULLIF(regexp_replace(BTRIM("应付金额"), '[,\s￥¥元]', '', 'g'), '')::numeric AS payable_amount,
        NULLIF(regexp_replace(BTRIM("订单金额"), '[,\s￥¥元]', '', 'g'), '')::numeric AS order_amount,
        ((regexp_match(BTRIM("商家应收"), '^[+-]?[0-9]+(?:\.[0-9]+)?'))[1])::numeric AS merchant_receivable_amount
    FROM common.v_current_jd_order_raw
    WHERE NULLIF(BTRIM("订单号"), '') IS NOT NULL
),
order_grain AS (
    SELECT
        s.order_no,
        MAX(s.source_fulfillment_shop_code) AS source_fulfillment_shop_code,
        MAX(s.source_order_shop_code) AS source_order_shop_code,
        MAX(s.source_shop_name) AS source_shop_name,
        MAX(s.order_created_at) AS order_created_at,
        MAX(s.payment_confirmed_at) AS payment_confirmed_at,
        MAX(s.order_status) AS order_status,
        MAX(s.order_type) AS order_type,
        MAX(s.payable_amount) AS payable_amount,
        MAX(s.order_amount) AS order_amount,
        MAX(s.merchant_receivable_amount) AS merchant_receivable_amount,
        COUNT(*)::integer AS source_line_count,
        ARRAY_AGG(s.id ORDER BY s.id) AS source_ids,
        ARRAY_AGG(DISTINCT s.batch_id ORDER BY s.batch_id) AS source_batch_ids,
        ARRAY_AGG(DISTINCT s.source_file_name ORDER BY s.source_file_name) AS source_file_names,
        ARRAY_AGG(DISTINCT s.source_sheet_name ORDER BY s.source_sheet_name) AS source_sheet_names,
        ARRAY_AGG(s.source_row_no ORDER BY s.source_row_no) AS source_row_nos,
        MAX(s.ingest_time) AS source_updated_at
    FROM source_normalized s
    GROUP BY s.order_no
),
dated AS (
    SELECT
        *,
        COALESCE(payment_confirmed_at::date, order_created_at::date) AS stat_date,
        CASE
            WHEN payment_confirmed_at IS NOT NULL THEN 'payment_confirmation_time'
            WHEN order_created_at IS NOT NULL THEN 'order_time'
            ELSE 'missing'
        END AS stat_date_source
    FROM order_grain
)
SELECT
    'jd',
    '京东',
    d.source_fulfillment_shop_code,
    d.source_order_shop_code,
    d.source_shop_name,
    ctx.shop_code,
    ctx.shop_name,
    'batch_context',
    ctx.shop_identity_key,
    d.order_no,
    d.stat_date,
    d.stat_date_source,
    d.order_created_at,
    d.payment_confirmed_at,
    d.order_status,
    d.order_type,
    ROUND(d.payable_amount, 2),
    ROUND(d.order_amount, 2),
    ROUND(COALESCE(d.merchant_receivable_amount, 0), 2),
    d.source_line_count,
    d.source_ids,
    d.source_batch_ids,
    d.source_file_names,
    d.source_sheet_names,
    d.source_row_nos,
    d.source_updated_at,
    NOW()
FROM dated d
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = d.source_batch_ids[1]
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_order_raw'
   AND ctx.shop_mapping_status = 'mapped';
