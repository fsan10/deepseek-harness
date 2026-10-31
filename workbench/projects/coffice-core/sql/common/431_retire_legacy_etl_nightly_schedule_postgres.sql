-- Retire the independent ETL nightly scheduler. ETL schedules are owned by Automation Workbench.
DO $retire_legacy_schedule$
BEGIN
    IF to_regclass('ops.etl_nightly_schedule') IS NOT NULL THEN
        EXECUTE $disable$
            UPDATE ops.etl_nightly_schedule
            SET enabled = FALSE,
                updated_by = 'automation_workbench_migration',
                updated_at = NOW()
            WHERE config_id = 1
              AND enabled IS DISTINCT FROM FALSE
        $disable$;
    END IF;
END;
$retire_legacy_schedule$;
