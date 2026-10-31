WITH confirmed_batch_shop (batch_id, shop_code) AS (
    VALUES
        (1::bigint, '114877104'), (2, '114877104'), (3, '114877104'), (4, '114877104'),
        (5, '123572735'), (6, '123572735'), (7, '123572735'),
        (8, '3527127781'), (9, '3527127781'), (10, '3527127781'),
        (11, '116694910'), (13, '116694910'),
        (14, 'wx21c4b9f6b83ef84a'), (15, 'wx21c4b9f6b83ef84a'), (16, 'wx21c4b9f6b83ef84a'),
        (17, '549820088'), (18, '549820088'), (19, '549820088'), (20, '549820088'),
        (21, '549820088'), (22, '549820088'), (23, '549820088'), (24, '549820088'),
        (25, '549820088'), (26, '549820088'), (27, '549820088'), (28, '549820088'),
        (29, '6674ec57c822d300018cf1eb'), (30, '6674ec57c822d300018cf1eb'),
        (31, '6674ec57c822d300018cf1eb'), (32, '6674ec57c822d300018cf1eb'),
        (33, '114877104'), (34, '114877104')
), resolved AS (
    SELECT
        confirmed.batch_id,
        dim.shop_code,
        dim.shop_name,
        dim.shop_identity_key,
        dim.company_code,
        dim.company_name
    FROM confirmed_batch_shop confirmed
    INNER JOIN ods.ods_file_ingest_log log
        ON log.batch_id = confirmed.batch_id
    INNER JOIN dim.dim_platform_shop_company dim
        ON dim.platform_code = log.platform_code
       AND dim.shop_code = confirmed.shop_code
       AND dim.is_active
       AND CURRENT_DATE >= dim.valid_from
       AND (dim.valid_to IS NULL OR CURRENT_DATE <= dim.valid_to)
)
UPDATE ods.ods_file_ingest_log log
SET
    shop_code = resolved.shop_code,
    shop_name = resolved.shop_name,
    shop_identity_key = resolved.shop_identity_key,
    shop_mapping_status = 'mapped',
    shop_mapping_source = 'manual_backfill',
    shop_mapping_message = FORMAT(
        '用户确认历史批次；company_code=%s; company_name=%s',
        resolved.company_code,
        resolved.company_name
    ),
    updated_at = NOW()
FROM resolved
WHERE log.batch_id = resolved.batch_id;

DO $$
DECLARE
    missing_batch_ids TEXT;
BEGIN
    SELECT STRING_AGG(batch_id::text, ',' ORDER BY batch_id)
      INTO missing_batch_ids
    FROM ods.ods_file_ingest_log
    WHERE ingest_status = 'success'
      AND (
          shop_mapping_status IS DISTINCT FROM 'mapped'
          OR shop_identity_key IS NULL
      );

    IF missing_batch_ids IS NOT NULL THEN
        RAISE EXCEPTION '存在未完成店铺映射的成功批次：%', missing_batch_ids;
    END IF;
END $$;
