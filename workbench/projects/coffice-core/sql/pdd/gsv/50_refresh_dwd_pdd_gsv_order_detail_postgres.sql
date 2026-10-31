TRUNCATE TABLE dwd.dwd_pdd_gsv_order_detail;

INSERT INTO dwd.dwd_pdd_gsv_order_detail (
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_code_source,
    shop_identity_key,
    order_no,
    stat_date,
    order_deal_at,
    order_status,
    after_sale_status,
    merchant_received_amount,
    store_discount_amount,
    user_paid_amount,
    source_id,
    source_batch_id,
    source_file_name,
    source_sheet_name,
    source_row_no,
    source_updated_at,
    updated_at
)
WITH latest_source AS (
    SELECT DISTINCT ON (NULLIF(BTRIM("订单号"), ''))
        id,
        batch_id,
        source_file_name,
        source_sheet_name,
        source_row_no,
        ingest_time,
        NULLIF(BTRIM("订单号"), '') AS order_no,
        NULLIF(NULLIF(BTRIM("订单成交时间"), ''), '-')::timestamp AS order_deal_at,
        NULLIF(BTRIM("订单状态"), '') AS order_status,
        NULLIF(BTRIM("售后状态"), '') AS after_sale_status,
        NULLIF(regexp_replace(BTRIM("商家实收金额(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric AS merchant_received_amount,
        NULLIF(regexp_replace(BTRIM("店铺优惠折扣(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric AS store_discount_amount,
        NULLIF(regexp_replace(BTRIM("用户实付金额(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric AS user_paid_amount
    FROM common.v_current_pdd_order_raw
    WHERE NULLIF(BTRIM("订单号"), '') IS NOT NULL
    ORDER BY NULLIF(BTRIM("订单号"), ''), ingest_time DESC, id DESC
)
SELECT
    'pdd',
    '拼多多',
    ctx.shop_code,
    ctx.shop_name,
    'batch_context',
    ctx.shop_identity_key,
    o.order_no,
    o.order_deal_at::date,
    o.order_deal_at,
    o.order_status,
    o.after_sale_status,
    ROUND(o.merchant_received_amount, 2),
    ROUND(o.store_discount_amount, 2),
    ROUND(o.user_paid_amount, 2),
    o.id,
    o.batch_id,
    o.source_file_name,
    o.source_sheet_name,
    o.source_row_no,
    o.ingest_time,
    NOW()
FROM latest_source o
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = o.batch_id
   AND ctx.platform_code = 'pdd'
   AND ctx.target_table = 'ods_pdd_order_raw'
   AND ctx.shop_mapping_status = 'mapped';
