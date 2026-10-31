TRUNCATE TABLE dwd.dwd_xhs_gsv_order_item_detail;

INSERT INTO dwd.dwd_xhs_gsv_order_item_detail (
    platform_code, platform_name, source_shop_name, shop_code, shop_name,
    shop_identity_key, shop_code_source, order_no, specification_id, product_id,
    product_name, sku_name, sku_quantity, stat_date, stat_date_source,
    order_created_at, order_paid_at, order_status, after_sale_status,
    merchant_receivable_amount, shop_discount_amount, user_payable_amount,
    platform_discount_amount, source_id, source_batch_id, source_file_name,
    source_sheet_name, source_row_no, source_updated_at, updated_at
)
SELECT
    'xhs', '小红书', NULLIF(BTRIM(o."店铺名称"), ''),
    ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, 'batch_context',
    NULLIF(BTRIM(o."订单号"), ''), NULLIF(BTRIM(o."规格ID"), ''),
    NULLIF(BTRIM(o."商品ID"), ''), NULLIF(BTRIM(o."商品名称"), ''),
    NULLIF(BTRIM(o."SKU名称"), ''),
    ROUND(COALESCE(NULLIF(regexp_replace(BTRIM(o."SKU件数"), '[,\s]', '', 'g'), '')::numeric, 0), 2),
    COALESCE(
        NULLIF(NULLIF(BTRIM(o."支付时间"), ''), '-')::timestamp::date,
        NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::timestamp::date
    ),
    CASE
        WHEN NULLIF(NULLIF(BTRIM(o."支付时间"), ''), '-') IS NOT NULL THEN 'payment_time'
        WHEN NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-') IS NOT NULL THEN 'creation_time'
        ELSE 'missing'
    END,
    NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::timestamp,
    NULLIF(NULLIF(BTRIM(o."支付时间"), ''), '-')::timestamp,
    NULLIF(BTRIM(o."订单状态"), ''), NULLIF(BTRIM(o."售后状态"), ''),
    ROUND(COALESCE(NULLIF(regexp_replace(BTRIM(o."商家应收金额(元)（支付金额）"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(regexp_replace(BTRIM(o."店铺优惠(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(regexp_replace(BTRIM(o."用户应付金额(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0), 2),
    ROUND(COALESCE(NULLIF(regexp_replace(BTRIM(o."平台优惠(元)"), '[,\s￥¥元]', '', 'g'), '')::numeric, 0), 2),
    o.id, o.batch_id, o.source_file_name, o.source_sheet_name, o.source_row_no,
    o.ingest_time, NOW()
FROM common.v_current_xhs_order_raw o
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = o.batch_id
   AND ctx.platform_code = 'xhs'
   AND ctx.target_table = 'ods_xhs_order_raw'
   AND ctx.shop_mapping_status = 'mapped'
WHERE NULLIF(BTRIM(o."订单号"), '') IS NOT NULL;

