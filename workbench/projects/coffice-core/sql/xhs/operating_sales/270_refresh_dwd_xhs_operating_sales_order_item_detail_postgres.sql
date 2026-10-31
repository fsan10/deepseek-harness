DO $$
DECLARE
    invalid_batch_count BIGINT;
    source_shop_conflict_count BIGINT;
    missing_key_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id
        FROM common.v_current_xhs_order_raw
        GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'xhs'
         AND c.target_table = 'ods_xhs_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '小红书订单ODS存在%个未映射、空批次或冲突批次，停止刷新运营成交DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO source_shop_conflict_count
    FROM common.v_current_xhs_order_raw o
    JOIN common.v_ingest_batch_shop_context c
      ON c.batch_id = o.batch_id
     AND c.platform_code = 'xhs'
     AND c.target_table = 'ods_xhs_order_raw'
     AND c.shop_mapping_status = 'mapped'
    WHERE NULLIF(BTRIM(o."店铺名称", E' \t\r\n'), '') IS NOT NULL
      AND NULLIF(BTRIM(o."店铺名称", E' \t\r\n'), '') <> c.shop_name;

    IF source_shop_conflict_count > 0 THEN
        RAISE EXCEPTION '小红书订单ODS有%条源店铺名称与批次标准店铺冲突，停止刷新运营成交DWD', source_shop_conflict_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_xhs_order_raw
    WHERE NULLIF(BTRIM("订单号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '小红书订单ODS有%条记录缺少订单号，停止刷新运营成交DWD', missing_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_xhs_operating_sales_order_item_detail;

INSERT INTO dwd.dwd_xhs_operating_sales_order_item_detail (
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
        NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::TIMESTAMP AS order_created_at,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."SKU件数"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS quantity_value,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."商品总价(元)"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS gmv_value,
        ((REGEXP_MATCH(REPLACE(BTRIM(o."用户应付金额(元)"), ',', ''), '^(-?[0-9]+(?:\.[0-9]+)?)$'))[1])::NUMERIC AS pay_value
    FROM common.v_current_xhs_order_raw o
)
SELECT
    'xhs',
    '小红书',
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
    NULLIF(BTRIM(p."售后状态"), ''),
    NULLIF(BTRIM(p."商品ID", E' \t\r\n'), ''),
    /*
       小红书少量历史订单会缺失商家编码。仅在DIM中存在唯一产品名称匹配、
       且规格可解析数量时生成标准编码；ODS原始字段保持不变，无法唯一匹配
       的空编码仍由产品分摊校验阻断，避免静默猜测。
    */
    COALESCE(
        NULLIF(BTRIM(p."商家编码", E' \t\r\n'), ''),
        fallback.code_prefix || fallback.component_quantity::TEXT
    ),
    NULLIF(BTRIM(p."SKU名称", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."SKU规格", E' \t\r\n'), ''),
    ROUND(p.quantity_value, 2),
    ROUND(p.gmv_value, 2),
    ROUND(p.pay_value, 2),
    ROUND(p.gmv_value, 2),
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
    SELECT q.code_prefix, q.component_quantity
    FROM (
        SELECT candidate.code_prefix,
               candidate.mapping_id,
               COALESCE(
                   ((REGEXP_MATCH(COALESCE(p."SKU规格", ''), '([0-9]+)\s*盒'))[1])::NUMERIC,
                   1::NUMERIC
               ) AS component_quantity,
               COUNT(*) OVER () AS match_count,
               CASE
                   WHEN NULLIF(BTRIM(p."商品名称", E' \t\r\n'), '') = candidate.legacy_product_name THEN 0
                   ELSE 1
               END AS match_rank
        FROM dim.dim_company_product_code_mapping candidate
        JOIN dim.dim_influencer_product product
          ON product.product_id = candidate.product_id
         AND product.is_active
        WHERE candidate.is_active
          AND candidate.match_rule = 'suffix_quantity'
          AND candidate.code_prefix IS NOT NULL
          AND NULLIF(BTRIM(p."商家编码", E' \\t\\r\\n'), '') IS NULL
          AND NULLIF(BTRIM(p."商品名称", E' \t\r\n'), '') IS NOT NULL
          AND (
              NULLIF(BTRIM(p."商品名称", E' \t\r\n'), '') = candidate.legacy_product_name
              OR POSITION(candidate.legacy_product_name IN BTRIM(p."商品名称", E' \t\r\n')) > 0
              OR POSITION(product.product_name IN BTRIM(p."商品名称", E' \t\r\n')) > 0
              OR POSITION(
                     NULLIF(
                         REGEXP_REPLACE(
                             BTRIM(p."SKU规格", E' \t\r\n'),
                             '^【[0-9]+(盒|袋|包|杯)|】$',
                             '',
                             'g'
                         ),
                         ''
                     )
                     IN candidate.legacy_product_name
                 ) > 0
              OR POSITION(
                     candidate.legacy_product_name IN NULLIF(
                         REGEXP_REPLACE(
                         BTRIM(p."SKU规格", E' \t\r\n'),
                             '^【[0-9]+(盒|袋|包|杯)|】$',
                             '',
                             'g'
                         ),
                         ''
                     )
                 ) > 0
          )
    ) q
    WHERE q.match_count = 1
    ORDER BY q.match_rank, q.mapping_id
    LIMIT 1
) fallback ON TRUE
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = p.batch_id
 AND c.platform_code = 'xhs'
 AND c.target_table = 'ods_xhs_order_raw'
 AND c.shop_mapping_status = 'mapped';
