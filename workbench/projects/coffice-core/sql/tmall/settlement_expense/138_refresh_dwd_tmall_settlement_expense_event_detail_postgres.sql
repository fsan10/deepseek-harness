TRUNCATE TABLE dwd.dwd_tmall_settlement_expense_event_detail;

INSERT INTO dwd.dwd_tmall_settlement_expense_event_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, stat_date, bill_period_raw,
    funds_direction, bill_category, business_category, business_subcategory,
    expense_item, charged_at, ordered_at, confirmed_at, main_order_no,
    sub_order_no, charge_transaction_amount, gross_charge_amount, refund_amount,
    expense_amount, expense_amount_source, source_batch_id, source_file_name,
    source_row_no, source_updated_at, updated_at
)
WITH parsed AS (
    SELECT
        raw.*,
        COALESCE(
            NULLIF(NULLIF(BTRIM(raw."退款金额(元)"), ''), '-')::numeric,
            NULLIF(NULLIF(BTRIM(raw."退款金额（元）"), ''), '-')::numeric,
            0
        ) AS parsed_refund_amount,
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
        END AS parsed_expense_amount,
        CASE
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额"), ''), '-') IS NOT NULL THEN '扣费金额'
            WHEN NULLIF(NULLIF(BTRIM(raw."支出金额（元）"), ''), '-') IS NOT NULL THEN '支出金额（元）'
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额（元）"), ''), '-') IS NOT NULL THEN '扣费金额（元）-退款金额'
            WHEN NULLIF(NULLIF(BTRIM(raw."扣费金额(元)"), ''), '-') IS NOT NULL THEN '扣费金额(元)-退款金额'
            ELSE 'missing'
        END AS parsed_expense_amount_source
    FROM ods.ods_tmall_settlement_expense_raw raw
)
SELECT
    p.id, 'tmall', '天猫', ctx.shop_code, ctx.shop_name,
    ctx.shop_identity_key, ctx.shop_mapping_source,
    TO_DATE(BTRIM(p."账期"), 'YYYYMMDD'), BTRIM(p."账期"),
    NULLIF(BTRIM(p."资金方向"), ''),
    NULLIF(BTRIM(p."账单大类"), ''),
    NULLIF(BTRIM(p."业务大类"), ''),
    NULLIF(BTRIM(p."业务小类"), ''),
    NULLIF(BTRIM(p."支出项目"), ''),
    NULLIF(NULLIF(BTRIM(p."扣费日期"), ''), '-')::timestamp,
    COALESCE(
        NULLIF(NULLIF(BTRIM(p."订单日期"), ''), '-')::timestamp,
        NULLIF(NULLIF(BTRIM(p."订单日期_2"), ''), '-')::timestamp
    ),
    NULLIF(NULLIF(BTRIM(p."确认收货日期"), ''), '-')::timestamp,
    COALESCE(
        NULLIF(BTRIM(p."交易主订单号"), ''),
        NULLIF(BTRIM(p."交易主单号"), ''),
        NULLIF(BTRIM(p."交易主订单号_2"), '')
    ),
    COALESCE(
        NULLIF(BTRIM(p."交易子订单号"), ''),
        NULLIF(BTRIM(p."交易子订单号_2"), '')
    ),
    ROUND(COALESCE(
        NULLIF(NULLIF(BTRIM(p."扣费交易金额"), ''), '-')::numeric,
        NULLIF(NULLIF(BTRIM(p."扣费交易金额（元）"), ''), '-')::numeric,
        NULLIF(NULLIF(BTRIM(p."扣款交易金额"), ''), '-')::numeric,
        0
    ), 2),
    ROUND(COALESCE(
        NULLIF(NULLIF(BTRIM(p."扣费金额（元）"), ''), '-')::numeric,
        NULLIF(NULLIF(BTRIM(p."扣费金额(元)"), ''), '-')::numeric,
        NULLIF(NULLIF(BTRIM(p."扣费金额"), ''), '-')::numeric,
        NULLIF(NULLIF(BTRIM(p."支出金额（元）"), ''), '-')::numeric,
        0
    ), 2),
    ROUND(p.parsed_refund_amount, 2),
    ROUND(p.parsed_expense_amount, 2),
    p.parsed_expense_amount_source,
    p.batch_id, p.source_file_name, p.source_row_no, p.ingest_time, NOW()
FROM parsed p
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = p.batch_id
   AND ctx.platform_code = 'tmall'
   AND ctx.target_table = 'ods_tmall_settlement_expense_raw'
   AND ctx.shop_mapping_status = 'mapped';

