TRUNCATE TABLE dwd.dwd_douyin_gsv_order_detail;

INSERT INTO dwd.dwd_douyin_gsv_order_detail (
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    main_order_no,
    sub_order_no,
    stat_date,
    order_submitted_at,
    payment_completed_at,
    order_status,
    after_sale_status,
    order_pay_amount,
    discount_total_amount,
    merchant_actual_discount_amount,
    merchant_discount_source,
    source_id,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
WITH latest_source AS (
    SELECT DISTINCT ON (NULLIF(BTRIM("子订单编号"), ''))
        id,
        batch_id,
        source_file_name,
        source_row_no,
        ingest_time,
        NULLIF(BTRIM("主订单编号"), '') AS main_order_no,
        NULLIF(BTRIM("子订单编号"), '') AS sub_order_no,
        NULLIF(NULLIF(BTRIM("订单提交时间"), ''), '-')::timestamp AS order_submitted_at,
        NULLIF(NULLIF(BTRIM("支付完成时间"), ''), '-')::timestamp AS payment_completed_at,
        NULLIF(BTRIM("订单状态"), '') AS order_status,
        NULLIF(BTRIM("售后状态"), '') AS after_sale_status,
        NULLIF(NULLIF(BTRIM("订单应付金额"), ''), '-') AS order_pay_raw,
        NULLIF(NULLIF(BTRIM("优惠总金额"), ''), '-') AS discount_total_raw,
        NULLIF(NULLIF(BTRIM("商家实际承担优惠金额"), ''), '-') AS merchant_actual_raw,
        NULLIF(NULLIF(BTRIM("商家优惠"), ''), '-') AS merchant_text_raw
    FROM common.v_current_douyin_order_raw
    WHERE NULLIF(BTRIM("子订单编号"), '') IS NOT NULL
    ORDER BY NULLIF(BTRIM("子订单编号"), ''), ingest_time DESC, id DESC
),
parsed AS (
    SELECT
        *,
        ((regexp_match(order_pay_raw, '(-?[0-9]+(?:\.[0-9]+)?)\s*$'))[1])::numeric AS order_pay_value,
        ABS(((regexp_match(discount_total_raw, '(-?[0-9]+(?:\.[0-9]+)?)\s*$'))[1])::numeric) AS discount_total_value,
        ABS(((regexp_match(merchant_actual_raw, '(-?[0-9]+(?:\.[0-9]+)?)\s*$'))[1])::numeric) AS merchant_actual_value,
        ABS(((regexp_match(merchant_text_raw, '(-?[0-9]+(?:\.[0-9]+)?)\s*$'))[1])::numeric) AS merchant_text_value
    FROM latest_source
)
SELECT
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    p.main_order_no,
    p.sub_order_no,
    COALESCE(p.payment_completed_at::date, p.order_submitted_at::date),
    p.order_submitted_at,
    p.payment_completed_at,
    p.order_status,
    p.after_sale_status,
    ROUND(COALESCE(p.order_pay_value, 0), 2),
    ROUND(COALESCE(p.discount_total_value, 0), 2),
    ROUND(COALESCE(p.merchant_actual_value, p.merchant_text_value, 0), 2),
    CASE
        WHEN p.merchant_actual_value IS NOT NULL THEN 'merchant_actual'
        WHEN p.merchant_text_value IS NOT NULL THEN 'merchant_text'
        ELSE 'default_zero'
    END,
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_order_raw'
   AND ctx.shop_mapping_status = 'mapped';
