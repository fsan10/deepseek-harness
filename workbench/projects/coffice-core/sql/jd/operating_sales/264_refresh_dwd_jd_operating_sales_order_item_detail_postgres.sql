DO $$
DECLARE
    invalid_batch_count BIGINT;
    missing_key_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id
        FROM common.v_current_jd_order_raw
        GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'jd'
         AND c.target_table = 'ods_jd_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '京东订单ODS存在%个未映射、空批次或冲突批次，停止刷新运营成交DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_jd_order_raw
    WHERE NULLIF(BTRIM("订单号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '京东订单ODS有%条记录缺少订单号，停止刷新运营成交DWD', missing_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_jd_operating_sales_order_item_detail;

INSERT INTO dwd.dwd_jd_operating_sales_order_item_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, source_shop_code, main_order_no, sub_order_no,
    stat_date, order_submitted_at, order_status, after_sale_status,
    product_id, merchant_code, product_name, product_spec, product_quantity,
    product_unit_price, order_pay_amount, gmv_amount, traffic_content_type,
    traffic_channel, source_id, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        o.*,
        NULLIF(NULLIF(BTRIM(o."下单时间"), ''), '-')::TIMESTAMP AS order_created_at,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."订购数量"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS quantity_value,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."京东价"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS gmv_value,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."应付金额"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS pay_value
    FROM common.v_current_jd_order_raw o
)
SELECT
    'jd',
    '京东',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    NULL,
    BTRIM(p."订单号", E' \t\r\n'),
    p.business_detail_key,
    p.order_created_at::DATE,
    p.order_created_at,
    NULLIF(BTRIM(p."订单状态"), ''),
    NULL,
    NULLIF(BTRIM(p."商品ID", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."商家SKUID", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."商品名称", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."商品名称", E' \t\r\n'), ''),
    ROUND(p.quantity_value, 2),
    ROUND(p.gmv_value, 2),
    ROUND(p.pay_value, 2),
    ROUND(p.gmv_value, 2),
    NULLIF(BTRIM(p."订单来源", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."订单渠道", E' \t\r\n'), ''),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = p.batch_id
 AND c.platform_code = 'jd'
 AND c.target_table = 'ods_jd_order_raw'
 AND c.shop_mapping_status = 'mapped';
