DO $$
DECLARE
    invalid_batch_count BIGINT;
    missing_key_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id FROM common.v_current_ks_order_raw GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'ks'
         AND c.target_table = 'ods_ks_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '快手订单ODS存在%个未映射、空批次或冲突批次，停止刷新达人业绩DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_ks_order_raw
    WHERE NULLIF(BTRIM("订单号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '快手订单ODS有%条记录缺少订单号，停止刷新达人业绩DWD', missing_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_ks_influencer_sales_order_item_detail;

INSERT INTO dwd.dwd_ks_influencer_sales_order_item_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, main_order_no, sub_order_no, stat_date,
    order_submitted_at, order_status, after_sale_status, influencer_id_raw,
    influencer_name_raw, sales_channel, order_carrier, product_unit_price,
    order_pay_amount, source_id, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        o.*,
        NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::TIMESTAMP AS order_created_at,
        ((REGEXP_MATCH(
            REPLACE(REPLACE(REPLACE(BTRIM(o."商品单价"), '¥', ''), '￥', ''), ',', ''),
            '^(-?[0-9]+(?:\.[0-9]+)?)$'
        ))[1])::NUMERIC AS unit_price_value,
        ((REGEXP_MATCH(
            REPLACE(REPLACE(REPLACE(BTRIM(o."实付款"), '¥', ''), '￥', ''), ',', ''),
            '^(-?[0-9]+(?:\.[0-9]+)?)$'
        ))[1])::NUMERIC AS pay_value
    FROM common.v_current_ks_order_raw o
)
SELECT
    'ks',
    '快手',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    BTRIM(p."订单号", E' \t\r\n'),
    p.business_detail_key,
    p.order_created_at::DATE,
    p.order_created_at,
    NULLIF(BTRIM(p."订单状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."售后状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."CPS达人ID", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."CPS达人昵称", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."渠道", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."订单载体", E' \t\r\n'), ''),
    ROUND(p.unit_price_value, 2),
    ROUND(p.pay_value, 2),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = p.batch_id
 AND c.platform_code = 'ks'
 AND c.target_table = 'ods_ks_order_raw'
 AND c.shop_mapping_status = 'mapped';

TRUNCATE TABLE dws.dws_ks_influencer_sales_order_item;

INSERT INTO dws.dws_ks_influencer_sales_order_item (
    stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
    main_order_no, sub_order_no, order_status, after_sale_status,
    influencer_id, influencer_name, influencer_key, product_unit_price,
    order_pay_amount, gmv_amount, refund_amount, is_closed_refund,
    included_sub_order_count, source_id, source_batch_id, source_updated_at,
    updated_at
)
SELECT
    d.stat_date,
    DATE_TRUNC('month', d.stat_date)::DATE,
    d.platform_code,
    d.platform_name,
    d.shop_code,
    d.shop_name,
    d.main_order_no,
    d.sub_order_no,
    d.order_status,
    d.after_sale_status,
    d.influencer_id_raw,
    COALESCE(NULLIF(d.influencer_name_raw, '-'), '其他'),
    d.platform_code || '|' || d.influencer_id_raw,
    d.product_unit_price,
    d.order_pay_amount,
    d.product_unit_price,
    CASE WHEN d.order_status = '交易关闭' THEN d.product_unit_price ELSE 0 END,
    d.order_status = '交易关闭',
    1,
    d.source_id,
    d.source_batch_id,
    d.source_updated_at,
    NOW()
FROM dwd.dwd_ks_influencer_sales_order_item_detail d
WHERE d.influencer_id_raw IS NOT NULL
  AND d.influencer_id_raw NOT IN ('', '-', '0')
  AND NOT EXISTS (
      SELECT 1
      FROM dwd.dwd_ks_influencer_sales_order_item_detail brush
      WHERE brush.platform_code = d.platform_code
        AND brush.shop_code = d.shop_code
        AND brush.main_order_no = d.main_order_no
        AND brush.order_pay_amount > 2000
  );
