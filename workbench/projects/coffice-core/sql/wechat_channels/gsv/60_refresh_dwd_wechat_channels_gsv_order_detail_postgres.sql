TRUNCATE TABLE dwd.dwd_wechat_channels_gsv_order_detail;

INSERT INTO dwd.dwd_wechat_channels_gsv_order_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_code_source, order_no, stat_date, stat_date_source, order_created_at,
    order_paid_at, order_status, after_sale_statuses, actual_received_amount,
    activity_merchant_subsidy_amount, actual_paid_amount, platform_coupon_amount,
    refunded_amount, source_line_count, source_ids, source_batch_ids,
    source_file_names, source_sheet_names, source_row_nos, source_updated_at, updated_at
)
WITH source_normalized AS (
    SELECT
        id, batch_id, source_file_name, source_sheet_name, source_row_no, ingest_time,
        NULLIF(BTRIM("订单号"), '') AS order_no,
        NULLIF(NULLIF(BTRIM("订单下单时间"), ''), '-')::timestamp AS order_created_at,
        NULLIF(NULLIF(BTRIM("支付时间"), ''), '-')::timestamp AS order_paid_at,
        NULLIF(BTRIM("订单状态"), '') AS order_status,
        NULLIF(BTRIM("商品售后"), '') AS after_sale_status,
        NULLIF(regexp_replace(BTRIM("订单实际收款金额"), '[,\s￥¥元]', '', 'g'), '')::numeric AS actual_received_amount,
        COALESCE(NULLIF(regexp_replace(BTRIM("活动商家补贴"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0) AS activity_merchant_subsidy_amount,
        NULLIF(regexp_replace(BTRIM("订单实际支付金额"), '[,\s￥¥元]', '', 'g'), '')::numeric AS actual_paid_amount,
        COALESCE(NULLIF(regexp_replace(BTRIM("商品平台券优惠"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0) AS platform_coupon_amount,
        COALESCE(NULLIF(regexp_replace(BTRIM("商品已退款金额"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0) AS refunded_amount
    FROM common.v_current_wechat_channels_order_raw
    WHERE NULLIF(BTRIM("订单号"), '') IS NOT NULL
),
order_grain AS (
    SELECT
        s.order_no,
        MAX(s.order_created_at) AS order_created_at,
        MAX(s.order_paid_at) AS order_paid_at,
        MAX(s.order_status) AS order_status,
        COALESCE(
            ARRAY_AGG(DISTINCT s.after_sale_status ORDER BY s.after_sale_status)
                FILTER (WHERE s.after_sale_status IS NOT NULL),
            ARRAY[]::TEXT[]
        ) AS after_sale_statuses,
        MAX(s.actual_received_amount) AS actual_received_amount,
        SUM(s.activity_merchant_subsidy_amount) AS activity_merchant_subsidy_amount,
        MAX(s.actual_paid_amount) AS actual_paid_amount,
        SUM(s.platform_coupon_amount) AS platform_coupon_amount,
        SUM(s.refunded_amount) AS refunded_amount,
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
    SELECT *,
        COALESCE(order_paid_at::date, order_created_at::date) AS stat_date,
        CASE
            WHEN order_paid_at IS NOT NULL THEN 'payment_time'
            WHEN order_created_at IS NOT NULL THEN 'order_time'
            ELSE 'missing'
        END AS stat_date_source
    FROM order_grain
)
SELECT
    'wechat_channels', '视频号', ctx.shop_code, ctx.shop_name, ctx.shop_identity_key,
    'batch_context', d.order_no, d.stat_date, d.stat_date_source, d.order_created_at,
    d.order_paid_at, d.order_status, d.after_sale_statuses,
    ROUND(d.actual_received_amount, 2), ROUND(d.activity_merchant_subsidy_amount, 2),
    ROUND(d.actual_paid_amount, 2), ROUND(d.platform_coupon_amount, 2),
    ROUND(d.refunded_amount, 2), d.source_line_count, d.source_ids, d.source_batch_ids,
    d.source_file_names, d.source_sheet_names, d.source_row_nos, d.source_updated_at, NOW()
FROM dated d
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = d.source_batch_ids[1]
   AND ctx.platform_code = 'wechat_channels'
   AND ctx.target_table = 'ods_wechat_channels_order_raw'
   AND ctx.shop_mapping_status = 'mapped';

