-- Caller owns the product-domain advisory lock and the surrounding ETL transaction.
DO $$
DECLARE
    new_snapshot UUID := gen_random_uuid();
    previous_snapshot UUID;
    row_total BIGINT;
    unmapped_total BIGINT;
BEGIN
    SELECT (summary->>'snapshot_id')::UUID INTO previous_snapshot
    FROM ops.refresh_watermark WHERE watermark_key = 'product_code_mapping';

    INSERT INTO ads.ads_product_code_mapping_workbench (
        snapshot_id, row_key, mapping_id, source_product_code, code_pattern,
        quantity_position, mapping_kind, current_product_id, company_product_code,
        product_type, large_product_category, product_category_l2, product_name,
        mapping_is_active, product_is_active, observed_source_codes,
        observed_platform_codes, observed_platform_names, shop_count,
        component_row_count, gift_component_row_count, parsed_quantity,
        paid_quantity, gift_quantity, gmv_amount, first_seen_date, last_seen_date,
        mapping_status, code_role, mapping_source, match_rule
    )
    SELECT new_snapshot,
           CASE WHEN o.mapping_id IS NOT NULL THEN 'rule:' || o.mapping_id::TEXT
                ELSE 'unmapped:' || JSONB_BUILD_ARRAY(o.source_product_code, o.quantity_position)::TEXT END,
           o.*, m.code_role, m.mapping_source, m.match_rule
    FROM common.v_operating_sales_product_code_observation o
    LEFT JOIN dim.dim_company_product_code_mapping m ON m.mapping_id = o.mapping_id;

    SELECT COUNT(*), COUNT(*) FILTER (WHERE mapping_status = 'unmapped')
      INTO row_total, unmapped_total
    FROM ads.ads_product_code_mapping_workbench WHERE snapshot_id = new_snapshot;

    -- Check the persisted business payload, including precision and nullable sets,
    -- against the complete authoritative observation result before publishing it.
    IF EXISTS (
        WITH expected AS (
            SELECT TO_JSONB(o) || JSONB_BUILD_OBJECT('code_role', m.code_role,
                   'mapping_source', m.mapping_source, 'match_rule', m.match_rule) AS payload
            FROM common.v_operating_sales_product_code_observation o
            LEFT JOIN dim.dim_company_product_code_mapping m ON m.mapping_id = o.mapping_id
        ), actual AS (
            SELECT TO_JSONB(a) - 'snapshot_id' - 'row_key' - 'generated_at' AS payload
            FROM ads.ads_product_code_mapping_workbench a WHERE snapshot_id = new_snapshot
        )
        (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION 'Product mapping snapshot differs from observation source';
    END IF;

    INSERT INTO ops.refresh_watermark(watermark_key, last_success_at, summary)
    SELECT 'product_code_mapping', clock_timestamp(), JSONB_BUILD_OBJECT(
        'snapshot_id', new_snapshot, 'previous_snapshot_id', previous_snapshot,
        'total', row_total, 'unmapped_total', unmapped_total,
        'source_revision', requested_revision)
    FROM ops.product_mapping_refresh_state WHERE state_key = 'product_mapping'
    ON CONFLICT (watermark_key) DO UPDATE SET last_success_at = EXCLUDED.last_success_at,
        summary = EXCLUDED.summary, updated_at = clock_timestamp();

    UPDATE ops.product_mapping_refresh_state SET completed_revision = requested_revision,
        completed_at = clock_timestamp(), last_error = NULL WHERE state_key = 'product_mapping';

    -- MVCC readers keep their original complete snapshot while newer readers use
    -- the newly published pointer. Keep the previous successful version as well.
    DELETE FROM ads.ads_product_code_mapping_workbench
    WHERE snapshot_id <> new_snapshot AND snapshot_id IS DISTINCT FROM previous_snapshot;
END;
$$;
