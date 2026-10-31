DO $migration$
DECLARE
    source_row RECORD;
    new_company_influencer_id BIGINT;
BEGIN
    IF TO_REGCLASS('dim.dim_influencer_business_assignment_monthly') IS NULL THEN
        RETURN;
    END IF;

    FOR source_row IN
        SELECT DISTINCT ON (platform_code, influencer_id)
            platform_code,
            influencer_id,
            CASE
                WHEN influencer_id = '0' THEN '其他'
                ELSE COALESCE(NULLIF(BTRIM(influencer_name), ''), influencer_id)
            END AS influencer_name
        FROM dim.dim_influencer_business_assignment_monthly
        WHERE NULLIF(BTRIM(platform_code), '') IS NOT NULL
          AND NULLIF(BTRIM(influencer_id), '') IS NOT NULL
        ORDER BY platform_code, influencer_id, effective_month DESC, updated_at DESC
    LOOP
        SELECT mapping.company_influencer_id
        INTO new_company_influencer_id
        FROM dim.dim_company_influencer_source_mapping mapping
        WHERE mapping.platform_code = source_row.platform_code
          AND mapping.source_influencer_id = source_row.influencer_id;

        IF new_company_influencer_id IS NULL THEN
            INSERT INTO dim.dim_company_influencer (
                company_influencer_name,
                note
            )
            VALUES (
                source_row.influencer_name,
                '由旧平台达人商务归属自动迁移；初始保持一平台账号一公司达人。'
            )
            RETURNING company_influencer_id INTO new_company_influencer_id;

            INSERT INTO dim.dim_company_influencer_source_mapping (
                company_influencer_id,
                platform_code,
                source_influencer_id,
                source_influencer_name_snapshot,
                is_active
            )
            VALUES (
                new_company_influencer_id,
                source_row.platform_code,
                source_row.influencer_id,
                source_row.influencer_name,
                TRUE
            );
        END IF;
    END LOOP;

    INSERT INTO dim.dim_company_influencer_business_assignment_monthly (
        company_influencer_id,
        effective_month,
        business_owner_id,
        assignment_source,
        note,
        is_active,
        created_at,
        updated_at
    )
    SELECT
        mapping.company_influencer_id,
        legacy.effective_month,
        legacy.business_owner_id,
        'legacy_migration',
        COALESCE(legacy.note, '由平台达人商务归属自动迁移'),
        legacy.is_active,
        legacy.created_at,
        legacy.updated_at
    FROM dim.dim_influencer_business_assignment_monthly legacy
    JOIN dim.dim_company_influencer_source_mapping mapping
      ON mapping.platform_code = legacy.platform_code
     AND mapping.source_influencer_id = legacy.influencer_id
    ON CONFLICT (company_influencer_id, effective_month) DO NOTHING;
END
$migration$;
