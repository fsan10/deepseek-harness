DO $$
DECLARE
    invalid_batch_count BIGINT;
    missing_key_count BIGINT;
    invalid_fallback_date_count BIGINT;
BEGIN
    WITH source_batches AS (
        SELECT batch_id FROM common.v_current_pdd_order_raw GROUP BY batch_id
    ), mapping_counts AS (
        SELECT b.batch_id, COUNT(c.batch_id) AS mapped_context_count
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'pdd'
         AND c.target_table = 'ods_pdd_order_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id
    )
    SELECT COUNT(*) INTO invalid_batch_count
    FROM mapping_counts
    WHERE batch_id IS NULL OR mapped_context_count <> 1;

    IF invalid_batch_count > 0 THEN
        RAISE EXCEPTION '拼多多订单ODS存在%个未映射、空批次或冲突批次，停止刷新达人佣金补零DWD', invalid_batch_count;
    END IF;

    SELECT COUNT(*) INTO missing_key_count
    FROM common.v_current_pdd_order_raw
    WHERE NULLIF(BTRIM("订单号", E' \t\r\n'), '') IS NULL;

    IF missing_key_count > 0 THEN
        RAISE EXCEPTION '拼多多订单ODS有%条记录缺少订单号，停止刷新达人佣金补零DWD', missing_key_count;
    END IF;

    SELECT COUNT(*) INTO invalid_fallback_date_count
    FROM common.v_current_pdd_order_raw
    WHERE NULLIF(NULLIF(BTRIM("订单成交时间"), ''), '-') IS NULL
      AND (
          BTRIM("订单号") !~ '^[0-9]{6}'
          OR TO_CHAR(TO_DATE('20' || LEFT(BTRIM("订单号"), 6), 'YYYYMMDD'), 'YYMMDD')
             <> LEFT(BTRIM("订单号"), 6)
      );

    IF invalid_fallback_date_count > 0 THEN
        RAISE EXCEPTION '拼多多订单ODS有%条记录无法从成交时间或订单号解析日期，停止刷新达人佣金补零DWD', invalid_fallback_date_count;
    END IF;
END $$;

TRUNCATE TABLE dwd.dwd_pdd_influencer_commission_zero_order_detail;

INSERT INTO dwd.dwd_pdd_influencer_commission_zero_order_detail (
    platform_code, platform_name, shop_code, shop_name, shop_identity_key,
    shop_mapping_source, order_no, source_row_key, stat_date, stat_date_source,
    order_submitted_at, order_status, after_sale_status, source_id,
    source_batch_id, source_file_name, source_row_no, source_updated_at,
    updated_at
)
WITH parsed AS (
    SELECT
        o.*,
        CASE
            WHEN NULLIF(NULLIF(BTRIM(o."订单成交时间"), ''), '-') IS NOT NULL
                THEN BTRIM(o."订单成交时间")::TIMESTAMP
            ELSE TO_DATE('20' || LEFT(BTRIM(o."订单号"), 6), 'YYYYMMDD')::TIMESTAMP
        END AS submitted_at,
        CASE
            WHEN NULLIF(NULLIF(BTRIM(o."订单成交时间"), ''), '-') IS NOT NULL
                THEN 'order_completed_time'
            ELSE 'order_no_prefix'
        END AS date_source
    FROM common.v_current_pdd_order_raw o
)
SELECT
    'pdd',
    '拼多多',
    c.shop_code,
    c.shop_name,
    c.shop_identity_key,
    c.shop_mapping_source,
    BTRIM(p."订单号", E' \t\r\n'),
    p.business_detail_key,
    p.submitted_at::DATE,
    p.date_source,
    p.submitted_at,
    NULLIF(BTRIM(p."订单状态", E' \t\r\n'), ''),
    NULLIF(BTRIM(p."售后状态", E' \t\r\n'), ''),
    p.id,
    p.batch_id,
    p.source_file_name,
    p.source_row_no,
    p.ingest_time,
    NOW()
FROM parsed p
JOIN common.v_ingest_batch_shop_context c
  ON c.batch_id = p.batch_id
 AND c.platform_code = 'pdd'
 AND c.target_table = 'ods_pdd_order_raw'
 AND c.shop_mapping_status = 'mapped';

TRUNCATE TABLE dws.dws_pdd_influencer_commission_shop_daily_zero;

INSERT INTO dws.dws_pdd_influencer_commission_shop_daily_zero (
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
FROM dwd.dwd_pdd_influencer_commission_zero_order_detail
GROUP BY stat_date, platform_code, shop_code;
