"""Link archive evidence to FileIngest without submitting or importing a file again."""
from __future__ import annotations

import calendar
import re
from datetime import datetime


def legacy_archive_period(filename: str) -> dict:
    """A legacy filename supplies only its labelled day/month, never range coverage."""
    match = re.match(r"^(\d{8}|\d{6})_", filename)
    if not match:
        return {}
    try:
        value = match[1]
        first = datetime.strptime(value, "%Y%m%d" if len(value) == 8 else "%Y%m").date()
    except ValueError:
        return {}
    last = first if len(value) == 8 else first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return {"business_date_start": first, "business_date_end": last,
            "period_type": "day" if len(value) == 8 else "month"}


def reconcile_report_ingest(cursor, run_id: str | None = None) -> int:
    """Recover missing links with bytes, filename, registered type and DIM identity.

    Successful imports win over uncertain/failed retries of exactly the same file.
    Existing explicit task links remain authoritative. No ODS data is changed.
    """
    cursor.execute("""SELECT a.artifact_id,a.step_run_id,a.file_name,a.business_date_start,a.business_date_end,
               a.period_type,t.file_task_id,t.run_id,t.batch_id,t.report_type
        FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id)
        JOIN LATERAL (
            SELECT t.* FROM ops.ingest_file_task t
            WHERE t.file_hash=a.file_hash AND t.file_size_bytes=a.file_size_bytes
              AND t.source_file_name=a.file_name
              AND t.resolved_platform_code=s.platform_code AND t.resolved_shop_code=s.shop_code
              AND t.resolved_company_code=s.company_code
              AND (a.report_type IS NULL OR t.report_type=a.report_type)
              AND (a.ingest_file_task_id IS NULL OR t.file_task_id=a.ingest_file_task_id)
            ORDER BY (t.status IN ('success','duplicate')) DESC,t.created_at DESC,t.file_task_id
            LIMIT 1
        ) t ON TRUE
        WHERE (a.ingest_file_task_id IS NULL OR a.report_type IS NULL
               OR a.business_date_start IS NULL OR a.business_date_end IS NULL)
          AND (%s::uuid IS NULL OR a.automation_run_id=%s::uuid)""", (run_id, run_id))
    rows = [dict(row) for row in cursor.fetchall()]
    for row in rows:
        period = legacy_archive_period(row['file_name'])
        cursor.execute("""UPDATE ops.automation_artifact SET
            ingest_file_task_id=%s,batch_id=COALESCE(%s,batch_id),report_type=COALESCE(report_type,%s),
            business_date_start=COALESCE(business_date_start,%s),business_date_end=COALESCE(business_date_end,%s),
            period_type=CASE WHEN period_type='unknown' THEN %s ELSE period_type END
            WHERE artifact_id=%s""",
            (row['file_task_id'], row['batch_id'], row['report_type'], period.get('business_date_start'),
             period.get('business_date_end'), period.get('period_type', 'unknown'), row['artifact_id']))
        cursor.execute("""UPDATE ops.automation_step_run SET ingest_run_id=COALESCE(ingest_run_id,%s),
            business_date_start=COALESCE(business_date_start,%s),business_date_end=COALESCE(business_date_end,%s),
            updated_at=NOW() WHERE step_run_id=%s""",
            (row['run_id'], period.get('business_date_start'), period.get('business_date_end'), row['step_run_id']))
    return len(rows)
