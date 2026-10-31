TRUNCATE TABLE dwd.dwd_ks_platform_expense_source_detail;

INSERT INTO dwd.dwd_ks_platform_expense_source_detail (
    source_document_type,
    source_id,
    secondary_category_name,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    order_no,
    source_company_name,
    source_amount,
    directional_expense_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'settlement',
    raw.id,
    component.secondary_category_name,
    'ks',
    '快手',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."实际结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."实际结算时间"), ''), '-')::timestamp,
    '支出',
    NULL,
    NULL,
    NULL,
    NULLIF(BTRIM(raw."订单号", E' \t\r\n'), ''),
    NULLIF(BTRIM(raw."账户名称"), ''),
    component.amount,
    component.amount,
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM common.v_current_ks_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped'
CROSS JOIN LATERAL (
    VALUES
        (
            '支付营销回退（元）',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."支付营销回退（元）"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '技术服务费(元)',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."技术服务费(元)"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '预售增收技术服务费（元）',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(
                            REPLACE(BTRIM(raw."预售增收技术服务费（元）"), ',', ''),
                            ''
                        ),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '达人佣金(元)',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."达人佣金(元)"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '团长佣金(元)',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."团长佣金(元)"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '快赚客佣金(元)',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."快赚客佣金(元)"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '服务商佣金(元)',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."服务商佣金(元)"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        ),
        (
            '其他收费',
            ROUND(
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."其他收费"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ),
                2
            )
        )
) AS component(secondary_category_name, amount);

INSERT INTO dwd.dwd_ks_platform_expense_source_detail (
    source_document_type,
    source_id,
    secondary_category_name,
    platform_code,
    platform_name,
    shop_code,
    shop_name,
    shop_identity_key,
    shop_mapping_source,
    stat_date,
    event_at,
    source_direction,
    source_business_type,
    source_description,
    flow_no,
    order_no,
    source_company_name,
    source_amount,
    directional_expense_amount,
    source_batch_id,
    source_file_name,
    source_row_no,
    source_updated_at,
    updated_at
)
SELECT
    'fund',
    raw.id,
    CASE
        WHEN NULLIF(BTRIM(raw."描述"), '') IS NULL
            THEN BTRIM(raw."业务类型")
        ELSE BTRIM(raw."业务类型") || ' + ' || BTRIM(raw."描述")
    END,
    'ks',
    '快手',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."入账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."入账时间"), ''), '-')::timestamp,
    BTRIM(raw."账务方向"),
    BTRIM(raw."业务类型"),
    NULLIF(BTRIM(raw."描述"), ''),
    NULLIF(BTRIM(raw."账务流水号"), ''),
    NULLIF(BTRIM(raw."关联业务单号", E' \t\r\n'), ''),
    NULL,
    amount.source_amount,
    CASE BTRIM(raw."账务方向")
        WHEN '支' THEN amount.source_amount
        WHEN '收' THEN -amount.source_amount
    END,
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM common.v_current_ks_fund_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'ks'
   AND ctx.target_table = 'ods_ks_fund_raw'
   AND ctx.shop_mapping_status = 'mapped'
CROSS JOIN LATERAL (
    SELECT ROUND(
        COALESCE(
            NULLIF(
                NULLIF(REPLACE(BTRIM(raw."发生额（元）"), ',', ''), ''),
                '-'
            )::numeric,
            0
        ),
        2
    ) AS source_amount
) amount;
