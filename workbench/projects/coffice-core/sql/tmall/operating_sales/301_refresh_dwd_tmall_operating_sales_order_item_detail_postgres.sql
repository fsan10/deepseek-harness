DO $$
DECLARE
    invalid_batch_count BIGINT;
    missing_key_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id FROM common.v_current_tmall_order_raw GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'tmall'
         AND c.target_table = 'ods_tmall_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '天猫订单ODS存在%个未映射、空批次或冲突批次，停止刷新运营成交DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_tmall_order_raw
    WHERE NULLIF(BTRIM("子订单编号", E' \t\r\n'), '') IS NULL
       OR NULLIF(BTRIM("主订单编号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '天猫订单ODS有%条记录缺少主订单或子订单编号，停止刷新运营成交DWD', missing_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_tmall_operating_sales_order_item_detail;

INSERT INTO dwd.dwd_tmall_operating_sales_order_item_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, source_shop_code, main_order_no, sub_order_no,
    stat_date, order_submitted_at, order_status, after_sale_status,
    product_id, merchant_code, product_name, product_spec, product_quantity,
    product_unit_price, order_pay_amount, gmv_amount, traffic_content_type,
    traffic_channel, source_id, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH source_context AS (
    SELECT o.*, c.shop_code, c.shop_name, c.shop_identity_key, c.shop_mapping_source
    FROM common.v_current_tmall_order_raw o
    JOIN common.v_ingest_batch_shop_context c
      ON c.batch_id = o.batch_id
     AND c.platform_code = 'tmall'
     AND c.target_table = 'ods_tmall_order_raw'
     AND c.shop_mapping_status = 'mapped'
), latest_source AS (
    SELECT DISTINCT ON (
        shop_code,
        NULLIF(BTRIM("子订单编号", E' \t\r\n'), '')
    ) *
    FROM source_context
    ORDER BY
        shop_code,
        NULLIF(BTRIM("子订单编号", E' \t\r\n'), ''),
        ingest_time DESC,
        id DESC
), parsed AS (
    SELECT
        s.*,
        NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-')::TIMESTAMP
            AS order_created_at,
        NULLIF(REGEXP_REPLACE(
            BTRIM(COALESCE("购买数量", '')), '[,\s￥¥元]', '', 'g'
        ), '') AS quantity_raw,
        NULLIF(REGEXP_REPLACE(
            BTRIM(COALESCE("买家应付货款", '')), '[,\s￥¥元]', '', 'g'
        ), '') AS pay_raw
    FROM latest_source s
)
SELECT
    'tmall',
    '天猫',
    p.shop_code,
    p.shop_name,
    p.shop_identity_key,
    p.shop_mapping_source,
    NULL,
    BTRIM(p."主订单编号", E' \t\r\n'),
    BTRIM(p."子订单编号", E' \t\r\n'),
    p.order_created_at::DATE,
    p.order_created_at,
    NULLIF(BTRIM(p."订单状态", E' \t\r\n'), ''),
    NULL,
    NULL,
    COALESCE(
        NULLIF(BTRIM(p."商家编码", E' \t\r\n'), ''),
        fallback.code_pattern
    ),
    NULLIF(BTRIM(p."商品标题", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."商品属性", E' \t\r\n'), ''),
    ROUND(CASE WHEN p.quantity_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.quantity_raw::NUMERIC ELSE 0 END, 2),
    ROUND(CASE WHEN p.pay_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.pay_raw::NUMERIC ELSE 0 END, 2),
    ROUND(CASE WHEN p.pay_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.pay_raw::NUMERIC ELSE 0 END, 2),
    ROUND(CASE WHEN p.pay_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.pay_raw::NUMERIC ELSE 0 END, 2),
    '未提供',
    '未提供',
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
LEFT JOIN LATERAL (
    SELECT q.code_pattern
    FROM (
        SELECT candidate.code_pattern,
               COUNT(*) OVER () AS match_count
        FROM dim.dim_company_product_code_mapping candidate
        JOIN dim.dim_influencer_product product
          ON product.product_id = candidate.product_id
         AND product.is_active
        WHERE candidate.is_active
          AND candidate.match_rule = 'exact'
          AND NULLIF(BTRIM(p."商家编码", E' \t\r\n'), '') IS NULL
          AND NULLIF(BTRIM(p."商品标题", E' \t\r\n'), '') = product.product_name
    ) q
    WHERE q.match_count = 1
    LIMIT 1
) fallback ON TRUE;
