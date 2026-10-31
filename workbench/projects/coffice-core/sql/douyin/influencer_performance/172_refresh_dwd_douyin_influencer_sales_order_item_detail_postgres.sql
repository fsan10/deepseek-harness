DO $$
DECLARE
    invalid_batch_count BIGINT;
    source_shop_conflict_count BIGINT;
    missing_order_key_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id
        FROM common.v_current_douyin_order_raw
        GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'douyin'
         AND c.target_table = 'ods_douyin_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '抖音订单ODS存在%个未映射、空批次或冲突批次，停止刷新达人业绩DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO source_shop_conflict_count
    FROM common.v_current_douyin_order_raw o
    JOIN common.v_ingest_batch_shop_context c
      ON c.batch_id = o.batch_id
     AND c.platform_code = 'douyin'
     AND c.target_table = 'ods_douyin_order_raw'
     AND c.shop_mapping_status = 'mapped'
    WHERE NULLIF(NULLIF(BTRIM(o."所属门店ID", E' \t\r\n'), ''), '-') IS NOT NULL
      AND NULLIF(NULLIF(BTRIM(o."所属门店ID", E' \t\r\n'), ''), '-') <> c.shop_code;

    IF source_shop_conflict_count > 0 THEN
        RAISE EXCEPTION '抖音订单ODS有%条源门店ID与批次标准店铺冲突，停止刷新达人业绩DWD', source_shop_conflict_count;
    END IF;

    SELECT COUNT(*) INTO missing_order_key_count
    FROM common.v_current_douyin_order_raw
    WHERE NULLIF(BTRIM("主订单编号", E' \t\r\n'), '') IS NULL
       OR NULLIF(BTRIM("子订单编号", E' \t\r\n'), '') IS NULL;

    IF missing_order_key_count > 0 THEN
        RAISE EXCEPTION '抖音订单ODS有%条记录缺少主订单或子订单编号，停止刷新达人业绩DWD', missing_order_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_douyin_influencer_sales_order_item_detail;

INSERT INTO dwd.dwd_douyin_influencer_sales_order_item_detail (
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    source_shop_code,
    main_order_no,
    sub_order_no,
    stat_date,
    order_submitted_at,
    traffic_source,
    order_status,
    after_sale_status,
    influencer_id_raw,
    influencer_name_raw,
    traffic_channel,
    product_unit_price,
    order_pay_amount,
    source_id,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
WITH latest_source AS (
    SELECT DISTINCT ON (NULLIF(BTRIM("子订单编号", E' \t\r\n'), ''))
        id,
        batch_id,
        source_file_name,
        source_row_no,
        ingest_time,
        NULLIF(NULLIF(BTRIM("所属门店ID", E' \t\r\n'), ''), '-') AS source_shop_code,
        NULLIF(BTRIM("主订单编号", E' \t\r\n'), '') AS main_order_no,
        NULLIF(BTRIM("子订单编号", E' \t\r\n'), '') AS sub_order_no,
        NULLIF(NULLIF(BTRIM("订单提交时间"), ''), '-') AS order_submitted_raw,
        NULLIF(BTRIM("流量来源", E' \t\r\n'), '') AS traffic_source,
        NULLIF(BTRIM("订单状态", E' \t\r\n'), '') AS order_status,
        NULLIF(BTRIM("售后状态", E' \t\r\n'), '') AS after_sale_status,
        NULLIF(BTRIM("达人ID", E' \t\r\n'), '') AS influencer_id_raw,
        NULLIF(BTRIM("达人昵称", E' \t\r\n'), '') AS influencer_name_raw,
        NULLIF(BTRIM("流量渠道", E' \t\r\n'), '') AS traffic_channel,
        NULLIF(NULLIF(BTRIM("商品单价"), ''), '-') AS product_unit_price_raw,
        NULLIF(NULLIF(BTRIM("订单应付金额"), ''), '-') AS order_pay_raw
    FROM common.v_current_douyin_order_raw
    ORDER BY
        NULLIF(BTRIM("子订单编号", E' \t\r\n'), ''),
        ingest_time DESC,
        id DESC
), parsed AS (
    SELECT
        *,
        order_submitted_raw::timestamp AS order_submitted_at,
        ((regexp_match(REPLACE(BTRIM(product_unit_price_raw, E' \t\r\n'), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::numeric AS product_unit_price_value,
        ((regexp_match(REPLACE(BTRIM(order_pay_raw, E' \t\r\n'), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::numeric AS order_pay_value
    FROM latest_source
)
SELECT
    'douyin',
    '抖音',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    p.source_shop_code,
    p.main_order_no,
    p.sub_order_no,
    p.order_submitted_at::date,
    p.order_submitted_at,
    p.traffic_source,
    p.order_status,
    p.after_sale_status,
    p.influencer_id_raw,
    p.influencer_name_raw,
    p.traffic_channel,
    ROUND(p.product_unit_price_value, 2),
    ROUND(p.order_pay_value, 2),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = p.batch_id
 AND c.platform_code = 'douyin'
 AND c.target_table = 'ods_douyin_order_raw'
 AND c.shop_mapping_status = 'mapped';

