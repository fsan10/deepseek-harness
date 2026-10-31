"""Freeze proven export dates separately from the dates of observed transactions."""
from __future__ import annotations

from datetime import date, timedelta


def summarize_days(days):
    days = sorted({date.fromisoformat(str(d)) for d in days})
    intervals = []
    for day in days:
        if intervals and day == date.fromisoformat(intervals[-1]['end']) + timedelta(days=1):
            intervals[-1]['end'] = day.isoformat()
        else:
            intervals.append({'start':day.isoformat(),'end':day.isoformat()})
    return {'low':days[0].isoformat() if days else None,'high':days[-1].isoformat() if days else None,
            'verified_days':[d.isoformat() for d in days],'intervals':intervals}


def freeze_jd_fund_coverage(cursor, context):
    """Only approved complete exports within both frozen cutoffs prove coverage.

    A file's first/last event and an unverified legacy claim do not prove empty
    dates. A fill operation that retained old rows against an empty new export
    also does not authorize a completeness claim for that date.
    """
    if 'jd' not in context.get('months',{}):
        return {}
    cutoff = int(context.get('batch_cutoff',0))
    cursor.execute('''WITH latest AS (
        SELECT DISTINCT ON(shop_identity_key,stat_date) *
        FROM common.ingest_source_day_selection
        WHERE platform_code='jd' AND target_table='ods_jd_fund_raw' AND selection_id<=%s
        ORDER BY shop_identity_key,stat_date,selection_id DESC
    ) SELECT s.shop_identity_key,s.stat_date FROM latest s
      JOIN dim.dim_platform_shop_company d USING(shop_identity_key)
      WHERE d.platform_code='jd' AND d.is_active AND CURRENT_DATE>=d.valid_from
        AND (d.valid_to IS NULL OR CURRENT_DATE<=d.valid_to)
        AND (%s::text[]='{}'::text[] OR d.shop_code=ANY(%s::text[]))
        AND s.evidence->'coverage'->>'complete_export'='true'
        AND s.stat_date BETWEEN (s.evidence->'coverage'->>'start')::date
                            AND (s.evidence->'coverage'->>'end')::date
        AND NOT (s.selection_mode='fill_gaps' AND s.evidence->>'comparison'='empty_new')
        AND NOT EXISTS (SELECT 1 FROM unnest(s.batch_ids) b(batch_id)
            LEFT JOIN ods.ods_file_ingest_log l USING(batch_id)
            WHERE l.batch_id IS NULL OR l.batch_id>%s OR l.batch_id=ANY(%s::bigint[])
               OR l.ingest_status<>'success' OR l.failed_rows<>0
               OR l.target_table<>'ods_jd_fund_raw' OR l.shop_identity_key<>s.shop_identity_key)
        AND EXISTS (SELECT 1 FROM ods.ods_file_ingest_log proof
            WHERE proof.file_hash=s.evidence->>'file_hash' AND proof.platform_code='jd'
              AND proof.target_table='ods_jd_fund_raw' AND proof.shop_identity_key=s.shop_identity_key
              AND proof.ingest_status='success' AND proof.failed_rows=0 AND proof.batch_id<=%s
              AND NOT(proof.batch_id=ANY(%s::bigint[])))
        ORDER BY 1,2''', (int(context.get('source_selection_cutoff',0)),
            context.get('shops',{}).get('jd',[]),context.get('shops',{}).get('jd',[]),
            cutoff,context.get('excluded_batch_ids',[]),cutoff,context.get('excluded_batch_ids',[])))
    grouped = {}
    for row in cursor.fetchall():
        shop,day = (row['shop_identity_key'],row['stat_date']) if isinstance(row,dict) else row
        grouped.setdefault(shop,[]).append(day)
    return {shop:summarize_days(days) for shop,days in grouped.items()}
