TRUNCATE TABLE dwd.dwd_douyin_platform_expense_source_detail;

INSERT INTO dwd.dwd_douyin_platform_expense_source_detail (
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
    source_event_type,
    flow_no,
    order_no,
    sub_order_no,
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
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."结算时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."结算时间"), ''), '-')::timestamp,
    '支出',
    NULLIF(BTRIM(raw."结算单类型"), ''),
    NULL,
    NULLIF(REPLACE(BTRIM(raw."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."子订单号"), '''', ''), ''),
    NULLIF(BTRIM(raw."商户主体名称"), ''),
    ROUND(
        COALESCE(
            NULLIF(
                NULLIF(REPLACE(BTRIM(component.source_amount_text), ',', ''), ''),
                '-'
            )::numeric,
            0
        ),
        2
    ),
    ROUND(
        -COALESCE(
            NULLIF(
                NULLIF(REPLACE(BTRIM(component.source_amount_text), ',', ''), ''),
                '-'
            )::numeric,
            0
        ),
        2
    ),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM common.v_current_douyin_settlement_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped'
CROSS JOIN LATERAL (VALUES
    ('平台服务费', raw."平台服务费"),
    ('达人佣金', raw."达人佣金"),
    ('服务商佣金', raw."服务商佣金"),
    ('渠道分成', raw."渠道分成"),
    ('招商服务费', raw."招商服务费"),
    ('站外推广费', raw."站外推广费"),
    ('其他分成', raw."其他分成")
) AS component(secondary_category_name, source_amount_text);

INSERT INTO dwd.dwd_douyin_platform_expense_source_detail (
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
    source_event_type,
    flow_no,
    order_no,
    sub_order_no,
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
    BTRIM(raw."动账场景"),
    'douyin',
    '抖音',
    ctx.shop_code,
    ctx.shop_name,
    ctx.shop_identity_key,
    ctx.shop_mapping_source,
    NULLIF(NULLIF(BTRIM(raw."动账时间"), ''), '-')::timestamp::date,
    NULLIF(NULLIF(BTRIM(raw."动账时间"), ''), '-')::timestamp,
    BTRIM(raw."动账方向"),
    NULLIF(BTRIM(raw."计费类型"), ''),
    NULLIF(REPLACE(BTRIM(raw."动帐流水号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."订单号"), '''', ''), ''),
    NULLIF(REPLACE(BTRIM(raw."子订单号"), '''', ''), ''),
    NULLIF(BTRIM(raw."商户主体名称"), ''),
    ROUND(
        COALESCE(
            NULLIF(
                NULLIF(REPLACE(BTRIM(raw."动账金额"), ',', ''), ''),
                '-'
            )::numeric,
            0
        ),
        2
    ),
    ROUND(
        CASE BTRIM(raw."动账方向")
            WHEN '出账' THEN
                COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."动账金额"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                )
            WHEN '入账' THEN
                -COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM(raw."动账金额"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                )
        END,
        2
    ),
    raw.batch_id,
    raw.source_file_name,
    raw.source_row_no,
    raw.ingest_time,
    NOW()
FROM common.v_current_douyin_fund_raw raw
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = raw.batch_id
   AND ctx.platform_code = 'douyin'
   AND ctx.target_table = 'ods_douyin_fund_raw'
   AND ctx.shop_mapping_status = 'mapped';
