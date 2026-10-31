"""Observe relevant newer sources without changing a run's frozen inputs."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from psycopg2 import sql
from etl.common.refresh_runtime import SOURCE_DATES,next_month
from .registry import ACTIVE_REPORTS


def relevant_tables(context, etl_keys):
    keys = set(etl_keys)
    return {t.removeprefix('ods.') for report in ACTIVE_REPORTS
            if report.platform_code in context.get('months',{}) and keys.intersection(report.etl_keys)
            for t in (report.target_tables or (report.target_table,)) if t.removeprefix('ods.') in SOURCE_DATES}


def periods(context, platform, table):
    return [(date.fromisoformat(m),next_month(date.fromisoformat(m)) +
             (timedelta(days=1) if table=='ods_jd_fund_raw' else timedelta()))
            for m in context.get('months',{}).get(platform,[])]


def matches(day, windows):
    return any(low <= day < high for low,high in windows)


def observe(cursor, context, etl_keys):
    observed_at = datetime.now(timezone.utc).isoformat()
    result = {'observed_at':observed_at,'batch_cutoff':context.get('batch_cutoff'),
        'source_selection_cutoff':context.get('source_selection_cutoff',0),
        'snapshot_policy':context.get('snapshot_policy','latest'),'relevant_batches':[],
        'relevant_selection_changes':[],'snapshot_stale':False,'message':''}
    if context.get('mode') != 'incremental':
        result['status']='not_applicable'
        return result
    tables = relevant_tables(context,etl_keys)
    if not tables:
        result['status']='not_applicable'
        return result
    cursor.execute("SELECT COALESCE(MAX(batch_id) FILTER(WHERE ingest_status='success'),0) current_batch_cutoff FROM ods.ods_file_ingest_log")
    result['current_batch_cutoff']=cursor.fetchone()['current_batch_cutoff']
    cursor.execute('''SELECT l.batch_id,l.platform_code,l.target_table,c.shop_code,c.shop_identity_key
        FROM ods.ods_file_ingest_log l JOIN common.v_ingest_batch_shop_context c USING(batch_id)
        WHERE l.ingest_status='success' AND c.shop_mapping_status='mapped' AND c.company_code IS NOT NULL
          AND l.target_table=ANY(%s) AND (l.batch_id>%s OR l.batch_id=ANY(%s::bigint[]))
        ORDER BY l.batch_id''',(sorted(tables),int(context.get('batch_cutoff',0)),context.get('excluded_batch_ids',[])))
    candidates = [dict(r) for r in cursor.fetchall()]
    for row in candidates:
        platform,table = row['platform_code'],row['target_table']
        shops = context.get('shops',{}).get(platform,[])
        if shops and row['shop_code'] not in shops:
            continue
        windows = periods(context,platform,table)
        cursor.execute(sql.SQL('SELECT DISTINCT ({}) AS day FROM ods.{} WHERE batch_id=%s').format(
            sql.SQL(SOURCE_DATES[table]),sql.Identifier(table)),(row['batch_id'],))
        days = [r['day'] for r in cursor.fetchall() if r['day'] is not None]
        overlaps = any(matches(d,windows) for d in days)
        if not overlaps:
            # Complete approved zero-row exports can affect a scope too.
            cursor.execute('''SELECT f.coverage FROM ops.ingest_file_task f JOIN ops.ingest_run r USING(run_id)
                JOIN ods.ods_file_ingest_log l ON l.batch_id=f.batch_id AND l.file_hash=f.file_hash
                WHERE f.batch_id=%s AND r.coverage_result IS NOT NULL AND f.status IN ('success','duplicate')''',
                (row['batch_id'],))
            for claim_row in cursor.fetchall():
                claim = claim_row['coverage'] or {}
                if claim.get('complete_export') and claim.get('start') and claim.get('end'):
                    low,high = date.fromisoformat(claim['start']),date.fromisoformat(claim['end'])
                    overlaps |= any(low < end and high >= start for start,end in windows)
        if overlaps:
            row['reason']='completed_after_freeze' if row['batch_id']<=context.get('batch_cutoff',0) else 'beyond_cutoff'
            result['relevant_batches'].append(row)
    cursor.execute('''SELECT DISTINCT ON(s.shop_identity_key,s.target_table,s.stat_date)
            s.selection_id,s.platform_code,s.target_table,s.stat_date,s.shop_identity_key,d.shop_code
        FROM common.ingest_source_day_selection s
        JOIN dim.dim_platform_shop_company d USING(shop_identity_key)
        WHERE s.selection_id>%s AND s.target_table=ANY(%s) AND d.is_active
          AND CURRENT_DATE>=d.valid_from AND (d.valid_to IS NULL OR CURRENT_DATE<=d.valid_to)
        ORDER BY s.shop_identity_key,s.target_table,s.stat_date,s.selection_id DESC''',
        (int(context.get('source_selection_cutoff',0)),sorted(tables)))
    for row in cursor.fetchall():
        row = dict(row)
        shops = context.get('shops',{}).get(row['platform_code'],[])
        if (not shops or row['shop_code'] in shops) and matches(row['stat_date'],periods(context,row['platform_code'],row['target_table'])):
            row['stat_date']=str(row['stat_date'])
            result['relevant_selection_changes'].append(row)
    result['snapshot_stale']=bool(result['relevant_batches'] or result['relevant_selection_changes'])
    result['status']='newer_related_sources' if result['snapshot_stale'] else 'current_for_scope'
    if result['snapshot_stale']:
        ids = [r['batch_id'] for r in result['relevant_batches']]
        result['message']=(f"[STALE_SNAPSHOT] 本次快照批次≤{result['batch_cutoff']}、采信≤{result['source_selection_cutoff']}；"
            f"原店铺及业务范围的相关批次{ids[:30]}不在快照中，另有{len(result['relevant_selection_changes'])}个日期采信变化。"
            '本次仍使用冻结输入；补数据后可使用最新数据重跑，范围不自动扩展。')
        if result['snapshot_policy']=='replay':
            result['message']+='这是已明确确认的原快照重放。'
    return result
