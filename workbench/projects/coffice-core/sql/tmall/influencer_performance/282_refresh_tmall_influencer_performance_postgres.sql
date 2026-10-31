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
        RAISE EXCEPTION '天猫订单ODS存在%个未映射、空批次或冲突批次，停止刷新达人DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_tmall_order_raw
    WHERE NULLIF(BTRIM("子订单编号", E' \t\r\n'), '') IS NULL
       OR NULLIF(BTRIM("主订单编号", E' \t\r\n'), '') IS NULL
       OR NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '天猫订单ODS有%条记录缺少订单键或创建时间，停止刷新达人DWD', missing_key_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_tmall_influencer_sales_order_detail;

INSERT INTO dwd.dwd_tmall_influencer_sales_order_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, main_order_no, sub_order_no, stat_date,
    order_submitted_at, order_status, product_title, influencer_name_raw,
    influencer_marker, product_quantity, order_pay_amount, source_id,
    source_batch_id, source_file_name, source_sheet_name, source_row_no,
    source_updated_at, updated_at
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
        o.*,
        NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::TIMESTAMP
            AS order_created_at,
        REGEXP_MATCH(COALESCE(o."商品标题", ''), '【([^】]+)(专属|推荐)】')
            AS influencer_match,
        NULLIF(REGEXP_REPLACE(
            BTRIM(COALESCE(o."购买数量", '')), '[,\s￥¥元]', '', 'g'
        ), '') AS quantity_raw,
        NULLIF(REGEXP_REPLACE(
            BTRIM(COALESCE(o."买家应付货款", '')), '[,\s￥¥元]', '', 'g'
        ), '') AS pay_raw
    FROM latest_source o
)
SELECT
    'tmall',
    '天猫',
    p.shop_code,
    p.shop_name,
    p.shop_identity_key,
    p.shop_mapping_source,
    BTRIM(p."主订单编号", E' \t\r\n'),
    BTRIM(p."子订单编号", E' \t\r\n'),
    p.order_created_at::DATE,
    p.order_created_at,
    NULLIF(BTRIM(p."订单状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."商品标题", E' \t\r\n'), ''),
    CASE WHEN p.influencer_match IS NULL
        THEN NULL ELSE BTRIM(p.influencer_match[1]) END,
    CASE WHEN p.influencer_match IS NULL
        THEN NULL ELSE BTRIM(p.influencer_match[2]) END,
    ROUND(CASE WHEN p.quantity_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.quantity_raw::NUMERIC ELSE 0 END, 2),
    ROUND(CASE WHEN p.pay_raw ~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
        THEN p.pay_raw::NUMERIC ELSE 0 END, 2),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_sheet_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p;

TRUNCATE TABLE dws.dws_tmall_influencer_sales_order;

INSERT INTO dws.dws_tmall_influencer_sales_order (
    stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
    main_order_no, sub_order_no, order_status, influencer_id, influencer_name,
    influencer_key, influencer_marker, order_pay_amount, gmv_amount,
    refund_amount, is_closed_refund, included_sub_order_count, source_id,
    source_batch_id, source_updated_at, updated_at
)
WITH normalized AS (
    SELECT
        d.*,
        REGEXP_REPLACE(
            BTRIM(d.influencer_name_raw),
            '^加购[！!\s]*',
            '',
            'g'
        ) AS influencer_name,
        SUM(d.order_pay_amount) OVER (
            PARTITION BY d.platform_code, d.shop_code, d.main_order_no
        ) AS main_order_pay_amount
    FROM dwd.dwd_tmall_influencer_sales_order_detail d
    WHERE d.influencer_name_raw IS NOT NULL
), identified AS (
    SELECT n.*, identity.influencer_id
    FROM normalized n
    JOIN LATERAL (
        SELECT a.influencer_id
        FROM dim.dim_influencer_business_assignment_monthly a
        WHERE a.platform_code = 'tmall'
          AND BTRIM(a.influencer_name) = n.influencer_name
        ORDER BY a.effective_month DESC, a.updated_at DESC
        LIMIT 1
    ) identity ON TRUE
    WHERE n.main_order_pay_amount <= 2000
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
    d.influencer_id,
    d.influencer_name,
    d.platform_code || '|' || d.influencer_id,
    d.influencer_marker,
    d.order_pay_amount,
    d.order_pay_amount,
    CASE WHEN d.order_status = '交易关闭' THEN d.order_pay_amount ELSE 0 END,
    d.order_status = '交易关闭',
    1,
    d.source_id,
    d.source_batch_id,
    d.source_updated_at,
    NOW()
FROM identified d;
