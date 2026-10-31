TRUNCATE TABLE dwd.dwd_tmall_settlement_net_event_detail;

INSERT INTO dwd.dwd_tmall_settlement_net_event_detail (
    source_event_key, source_table, source_id, platform_code, platform_name,
    shop_code, shop_name, shop_identity_key, shop_mapping_source, stat_date,
    bill_period_raw, event_direction, event_type, order_no, source_amount,
    income_amount, expense_amount, settlement_net_amount,
    source_settlement_amount, validation_difference_amount, source_batch_id,
    source_file_name, source_row_no, source_updated_at, updated_at
)
WITH income_events AS (
    SELECT
        'income:' || raw.id::text AS source_event_key,
        'ods_tmall_settlement_income_raw'::varchar AS source_table,
        raw.id AS source_id,
        ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, ctx.shop_mapping_source,
        TO_DATE(BTRIM(raw."账期"), 'YYYYMMDD') AS stat_date,
        BTRIM(raw."账期") AS bill_period_raw,
        '收入'::varchar AS event_direction,
        NULLIF(BTRIM(raw."账单大类"), '') AS event_type,
        NULLIF(BTRIM(raw."订单号"), '') AS order_no,
        ROUND(COALESCE(NULLIF(NULLIF(BTRIM(raw."订单实际金额（元）"), ''), '-')::numeric, 0), 2) AS event_amount,
        raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time
    FROM ods.ods_tmall_settlement_income_raw raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'tmall'
       AND ctx.target_table = 'ods_tmall_settlement_income_raw'
       AND ctx.shop_mapping_status = 'mapped'
), expense_parsed AS (
    SELECT
        raw.*,
        CASE
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额"), ''), '-') IS NOT NULL
                THEN NULLIF(NULLIF(BTRIM(raw."扣费金额"), ''), '-')::numeric
            WHEN NULLIF(NULLIF(BTRIM(raw."支出金额（元）"), ''), '-') IS NOT NULL
                THEN NULLIF(NULLIF(BTRIM(raw."支出金额（元）"), ''), '-')::numeric
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额（元）"), ''), '-') IS NOT NULL
                THEN NULLIF(NULLIF(BTRIM(raw."扣费金额（元）"), ''), '-')::numeric
                   - COALESCE(
                        NULLIF(NULLIF(BTRIM(raw."退款金额(元)"), ''), '-')::numeric,
                        NULLIF(NULLIF(BTRIM(raw."退款金额（元）"), ''), '-')::numeric,
                        0
                     )
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额(元)"), ''), '-') IS NOT NULL
                THEN NULLIF(NULLIF(BTRIM(raw."扣费金额(元)"), ''), '-')::numeric
                   - COALESCE(
                        NULLIF(NULLIF(BTRIM(raw."退款金额(元)"), ''), '-')::numeric,
                        NULLIF(NULLIF(BTRIM(raw."退款金额（元）"), ''), '-')::numeric,
                        0
                     )
            ELSE 0
        END AS event_amount
    FROM ods.ods_tmall_settlement_expense_raw raw
), expense_events AS (
    SELECT
        'expense:' || raw.id::text AS source_event_key,
        'ods_tmall_settlement_expense_raw'::varchar AS source_table,
        raw.id AS source_id,
        ctx.shop_code, ctx.shop_name, ctx.shop_identity_key, ctx.shop_mapping_source,
        TO_DATE(BTRIM(raw."账期"), 'YYYYMMDD') AS stat_date,
        BTRIM(raw."账期") AS bill_period_raw,
        '支出'::varchar AS event_direction,
        NULLIF(BTRIM(raw."支出项目"), '') AS event_type,
        COALESCE(
            NULLIF(BTRIM(raw."交易主订单号"), ''),
            NULLIF(BTRIM(raw."交易主单号"), ''),
            NULLIF(BTRIM(raw."交易主订单号_2"), '')
        ) AS order_no,
        ROUND(raw.event_amount, 2) AS event_amount,
        raw.batch_id, raw.source_file_name, raw.source_row_no, raw.ingest_time
    FROM expense_parsed raw
    INNER JOIN common.v_ingest_batch_shop_context ctx
        ON ctx.batch_id = raw.batch_id
       AND ctx.platform_code = 'tmall'
       AND ctx.target_table = 'ods_tmall_settlement_expense_raw'
       AND ctx.shop_mapping_status = 'mapped'
), all_events AS (
    SELECT *, event_amount AS income_amount, 0::numeric AS expense_amount
    FROM income_events
    UNION ALL
    SELECT *, 0::numeric AS income_amount, event_amount AS expense_amount
    FROM expense_events
)
SELECT
    source_event_key, source_table, source_id, 'tmall', '天猫',
    shop_code, shop_name, shop_identity_key, shop_mapping_source, stat_date,
    bill_period_raw, event_direction, event_type, order_no, event_amount,
    income_amount, expense_amount,
    ROUND(income_amount - expense_amount, 2),
    ROUND(income_amount - expense_amount, 2),
    0::numeric,
    batch_id, source_file_name, source_row_no, ingest_time, NOW()
FROM all_events;

