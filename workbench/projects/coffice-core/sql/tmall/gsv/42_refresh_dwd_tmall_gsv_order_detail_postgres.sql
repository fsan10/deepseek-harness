DO $$
DECLARE
    invalid_batch_count BIGINT;
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
        RAISE EXCEPTION '天猫订单ODS存在%个未映射、空批次或冲突批次，停止刷新GSV DWD', invalid_batch_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_tmall_gsv_order_detail;

INSERT INTO dwd.dwd_tmall_gsv_order_detail (
    platform_code, platform_name, shop_code, shop_name, shop_code_source,
    shop_identity_key, main_order_no, sub_order_no, product_title, stat_date,
    stat_date_source, order_created_at, order_paid_at, order_status,
    refund_status, refund_amount, buyer_paid_amount,
    source_id, source_batch_id, source_file_name,
    source_sheet_name, source_row_no, source_updated_at, updated_at
)
WITH source_context AS (
    SELECT
        o.*,
        c.shop_code,
        c.shop_name,
        c.shop_identity_key
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
    )
        *
    FROM source_context
    WHERE NULLIF(BTRIM("子订单编号", E' \t\r\n'), '') IS NOT NULL
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
        NULLIF(NULLIF(BTRIM("订单付款时间"), ''), '-')::TIMESTAMP
            AS order_paid_at,
        NULLIF(
            REGEXP_REPLACE(
                BTRIM(COALESCE("买家实付金额", '')),
                '[,\s￥¥元]',
                '',
                'g'
            ),
            ''
        ) AS buyer_paid_raw,
        NULLIF(
            REGEXP_REPLACE(
                BTRIM(COALESCE("退款金额", '')),
                '[,\s￥¥元]',
                '',
                'g'
            ),
            ''
        ) AS refund_amount_raw
    FROM latest_source s
)
SELECT
    'tmall',
    '天猫',
    p.shop_code,
    p.shop_name,
    'batch_context',
    p.shop_identity_key,
    BTRIM(p."主订单编号", E' \t\r\n'),
    BTRIM(p."子订单编号", E' \t\r\n'),
    NULLIF(BTRIM(p."商品标题", E' \t\r\n'), ''),
    COALESCE(p.order_paid_at::DATE, p.order_created_at::DATE),
    CASE
        WHEN p.order_paid_at IS NOT NULL THEN 'payment_time'
        WHEN p.order_created_at IS NOT NULL THEN 'creation_time'
        ELSE 'missing'
    END,
    p.order_created_at,
    p.order_paid_at,
    NULLIF(BTRIM(p."订单状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."退款状态", E' \t\r\n'), ''),
    ROUND(
        CASE
            WHEN p.refund_amount_raw IS NULL
              OR p.refund_amount_raw IN ('-', '无退款申请')
                THEN 0
            WHEN p.refund_amount_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
                THEN p.refund_amount_raw::NUMERIC
            ELSE 0
        END,
        2
    ),
    ROUND(
        CASE
            WHEN p.buyer_paid_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
                THEN p.buyer_paid_raw::NUMERIC
            ELSE 0
        END,
        2
    ),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_sheet_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p;
