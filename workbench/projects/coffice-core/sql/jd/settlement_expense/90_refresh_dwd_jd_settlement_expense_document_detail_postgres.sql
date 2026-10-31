TRUNCATE TABLE dwd.dwd_jd_settlement_expense_document_detail;

INSERT INTO dwd.dwd_jd_settlement_expense_document_detail (
    source_id, platform_code, platform_name, shop_code, shop_name,
    shop_identity_key, shop_mapping_source, source_shop_code, stat_date,
    bill_date_raw, document_no, order_no, merchant_order_no, document_type,
    fee_item_name, currency_code, income_expense_direction,
    merchant_receivable_payable, source_amount, expense_amount, source_batch_id,
    source_file_name, source_row_no, source_updated_at, updated_at
)
WITH cleaned AS (
    SELECT raw.*,
        NULLIF(REPLACE(REPLACE(BTRIM(raw."单据编号"), '="', ''), '"', ''), '') AS clean_document_no,
        NULLIF(REPLACE(REPLACE(BTRIM(raw."订单编号"), '="', ''), '"', ''), '') AS clean_order_no,
        NULLIF(REPLACE(REPLACE(BTRIM(raw."商户订单号"), '="', ''), '"', ''), '') AS clean_merchant_order_no,
        BTRIM(raw."账单日期") AS clean_bill_date,
        BTRIM(raw."金额")::numeric AS parsed_source_amount
    FROM common.v_selected_jd_settlement_raw raw
), latest AS (
    SELECT DISTINCT ON (clean_document_no) *
    FROM cleaned
    WHERE clean_document_no IS NOT NULL
    ORDER BY clean_document_no, ingest_time DESC, id DESC
)
SELECT
    l.id, 'jd', '京东', ctx.shop_code, ctx.shop_name, ctx.shop_identity_key,
    ctx.shop_mapping_source, NULLIF(BTRIM(l."店铺号"), ''),
    CASE
        WHEN l.clean_bill_date ~ '^[0-9]{8}$' THEN TO_DATE(l.clean_bill_date, 'YYYYMMDD')
        WHEN l.clean_bill_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN l.clean_bill_date::date
    END,
    l.clean_bill_date, l.clean_document_no, l.clean_order_no,
    l.clean_merchant_order_no, NULLIF(BTRIM(l."单据类型"), ''),
    NULLIF(BTRIM(l."费用项"), ''), NULLIF(BTRIM(l."币种"), ''),
    BTRIM(l."收支方向"), NULLIF(BTRIM(l."商家应收/应付"), ''),
    ROUND(l.parsed_source_amount, 2),
    ROUND(CASE WHEN BTRIM(l."收支方向") = '支出' THEN -l.parsed_source_amount ELSE 0 END, 2),
    l.batch_id, l.source_file_name, l.source_row_no, l.ingest_time, NOW()
FROM latest l
INNER JOIN common.v_ingest_batch_shop_context ctx
    ON ctx.batch_id = l.batch_id
   AND ctx.platform_code = 'jd'
   AND ctx.target_table = 'ods_jd_settlement_raw'
   AND ctx.shop_mapping_status = 'mapped';

