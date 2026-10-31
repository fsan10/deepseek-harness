DO $$
DECLARE
    invalid_batch_count BIGINT;
    source_shop_conflict_count BIGINT;
    missing_key_count BIGINT;
    missing_date_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id FROM common.v_current_xhs_order_raw GROUP BY batch_id
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
        RAISE EXCEPTION '小红书订单ODS存在%个未映射、空批次或冲突批次，停止刷新达人佣金补零DWD', invalid_batch_count;
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
        RAISE EXCEPTION '小红书订单ODS有%条源店铺名称与批次标准店铺冲突，停止刷新达人佣金补零DWD', source_shop_conflict_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_xhs_order_raw
    WHERE NULLIF(BTRIM("订单号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '小红书订单ODS有%条记录缺少订单号，停止刷新达人佣金补零DWD', missing_key_count;
    END IF;

    SELECT COUNT(*) INTO missing_date_count
    FROM common.v_current_xhs_order_raw
    WHERE NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-') IS NULL;

    IF missing_date_count > 0 THEN
        RAISE EXCEPTION '小红书订单ODS有%条记录缺少订单创建时间，停止刷新达人佣金补零DWD', missing_date_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_xhs_influencer_commission_zero_order_detail;

INSERT INTO dwd.dwd_xhs_influencer_commission_zero_order_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, source_shop_name, order_no, source_row_key,
    stat_date, order_submitted_at, order_status, after_sale_status, source_id,
    source_batch_id, source_file_name, source_row_no, source_updated_at,
    updated_at
)
SELECT
    'xhs',
    '小红书',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    NULLIF(BTRIM(o."店铺名称", E' \t\r\n'), ''),
    BTRIM(o."订单号", E' \t\r\n'),
    o.business_detail_key,
    NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::TIMESTAMP::DATE,
    NULLIF(NULLIF(BTRIM(o."订单创建时间"), ''), '-')::TIMESTAMP,
    NULLIF(BTRIM(o."订单状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(o."售后状态", E' \t\r\n'), ''),
    o.id,
    o.batch_id,
    o.source_file_name,
    o.source_row_no,
    o.ingest_time,
    NOW()
FROM common.v_current_xhs_order_raw o
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = o.batch_id
 AND c.platform_code = 'xhs'
 AND c.target_table = 'ods_xhs_order_raw'
 AND c.shop_mapping_status = 'mapped';

TRUNCATE TABLE dws.dws_xhs_influencer_commission_shop_daily_zero;

INSERT INTO dws.dws_xhs_influencer_commission_shop_daily_zero (
    stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
    influencer_commission_amount, included_detail_count, source_updated_at,
    updated_at
)
SELECT
    stat_date,
    DATE_TRUNC('month', stat_date)::DATE,
    platform_code,
    MAX(platform_name),
    shop_code,
    MAX(shop_name),
    0,
    0,
    MAX(source_updated_at),
    NOW()
FROM dwd.dwd_xhs_influencer_commission_zero_order_detail
GROUP BY stat_date, platform_code, shop_code;
