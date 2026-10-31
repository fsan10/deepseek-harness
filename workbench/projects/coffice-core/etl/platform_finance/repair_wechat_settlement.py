"""Recover an accepted WeChat settlement upload and reconcile its scoped retry.

No new ODS batch is imported. Reference files, immutable ODS fingerprints and
out-of-scope derived records are checked around the existing audited retry API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from apps.file_ingest.coverage import ROOT, business_day, canonical, fingerprint_rows, load_file
from apps.file_ingest.service import FileIngestService
from etl.common.settlement_sources import load_pg_env

RAW='ods.ods_wechat_channels_settlement_raw'
MIGRATIONS=('common/470_wechat_settlement_source_selection_postgres.sql',
            'common/460_finance_source_selection_postgres.sql')
SETTLEMENT_TABLES=[
    ('dwd',f'dwd_wechat_channels_settlement_{kind}_event_detail','stat_date') for kind in ('income','expense','net')
]+[
    ('dws','dws_wechat_channels_settlement_income_shop_daily_type','stat_date'),
    ('dws','dws_wechat_channels_settlement_expense_shop_daily_type','stat_date'),
    ('dws','dws_wechat_channels_settlement_net_shop_daily','stat_date'),
    ('ads','ads_settlement_income_company_shop_daily_type','stat_date'),
    ('ads','ads_settlement_expense_company_shop_daily_type','stat_date'),
    ('ads','ads_settlement_net_company_shop_daily','stat_date'),
    ('ads','ads_settlement_net_company_shop_monthly','stat_month'),
]


def query(cursor,statement,params=()):
    cursor.execute(statement,params)
    return [dict(row) for row in cursor.fetchall()]


def raw_fingerprint(cursor):
    return query(cursor,f'''SELECT batch_id,COUNT(*) rows,
        MD5(STRING_AGG(MD5(TO_JSONB(r)::text),'' ORDER BY id)) digest
        FROM {RAW} r GROUP BY batch_id ORDER BY batch_id''')


def outside_fingerprints(cursor,shops,months):
    result={}
    for schema,table,column in SETTLEMENT_TABLES:
        cursor.execute(sql.SQL('''SELECT COUNT(*) rows,
            MD5(COALESCE(STRING_AGG(MD5(TO_JSONB(t)::text),'' ORDER BY TO_JSONB(t)::text),'')) digest
            FROM {}.{} t WHERE NOT(platform_code='wechat_channels' AND shop_code=ANY(%s)
                AND DATE_TRUNC('month',{})::date=ANY(%s::date[]))''').format(
                sql.Identifier(schema),sql.Identifier(table),sql.Identifier(column)),(shops,months))
        result[schema+'.'+table]=dict(cursor.fetchone())
    return result


def source_reference(cursor,run_id,storage_root):
    tasks=query(cursor,'SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at',(run_id,))
    if len(tasks)!=1 or tasks[0]['report_type']!='wechat_channels_settlement':
        raise ValueError('此修复入口仅接受一个已成功入库的视频号结算文件')
    task=tasks[0]
    if task['status'] not in ('success','duplicate') or not task.get('batch_id'):
        raise ValueError('文件尚未完整入库，不能通过此入口刷新')
    claim=task.get('coverage') or {}
    if not claim.get('start') or not claim.get('end') or claim.get('complete_export') is not True:
        raise ValueError('原上传缺少已确认的完整查询区间，不能猜测覆盖范围')
    columns,rows=load_file(task,storage_root)
    actual=query(cursor,f'SELECT * FROM {RAW} WHERE batch_id=%s ORDER BY source_row_no',(task['batch_id'],))
    if len(rows)!=len(actual) or fingerprint_rows(rows,columns)!=fingerprint_rows(actual,columns):
        raise RuntimeError('参考文件与ODS的完整业务字段或行数不一致')
    for expected,stored in zip(rows[:5],actual[:5]):
        if any(canonical(expected.get(c))!=canonical(stored.get(c)) for c in columns):
            raise RuntimeError('参考文件与ODS原始字段抽样不一致')
    expected={}
    grouped=defaultdict(lambda:[0,Decimal(0),Decimal(0),Decimal(0)])
    for row in rows:
        day=business_day(row['记账时间'])
        if not claim['start']<=day<=claim['end']:
            raise ValueError('文件日期超出原上传声明')
        amount=Decimal(str(row['收支金额']).strip()).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        direction=canonical(row['收支类型'])
        if amount<=0 or direction not in ('收入','支出'):
            raise ValueError('参考文件金额或收支方向无效')
        inc=amount if direction=='收入' else Decimal(0)
        exp=amount if direction=='支出' else Decimal(0)
        v=grouped[day];v[0]+=1;v[1]+=inc;v[2]+=exp;v[3]+=inc-exp
    expected=dict(grouped)
    months=sorted({day[:7]+'-01' for day in grouped})
    return task,expected,months,{'file':task['source_file_name'],'batch_id':task['batch_id'],
        'file_hash':task['file_hash'],'rows':len(rows),'sample_rows':min(5,len(rows)),
        'all_business_fields_equal':True,'coverage':claim}


def reconcile(cursor,task,expected):
    start,end=task['coverage']['start'],task['coverage']['end']
    rows=query(cursor,'''SELECT stat_date,SUM(included_event_count) events,SUM(income_amount) income,
        SUM(expense_amount) expense,SUM(settlement_net_amount) net
        FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='wechat_channels'
        AND shop_code=%s AND stat_date BETWEEN %s AND %s GROUP BY stat_date ORDER BY stat_date''',
        (task['resolved_shop_code'],start,end))
    actual={str(row['stat_date']):[row[k] for k in ('events','income','expense','net')] for row in rows}
    if actual!=expected:
        raise RuntimeError('文件与结算日ADS的逐日流水数、收入、支出或净额不一致')
    cursor.execute('''SELECT COUNT(*)-COUNT(DISTINCT (shop_identity_key,flow_no)) duplicates,
        COUNT(*) FILTER(WHERE validation_difference_amount<>0) differences
        FROM dwd.dwd_wechat_channels_settlement_net_event_detail WHERE shop_code=%s
        AND stat_date BETWEEN %s AND %s''',(task['resolved_shop_code'],start,end))
    if any(cursor.fetchone().values()):
        raise RuntimeError('结算DWD存在重复身份或公式差异')
    for table,field in (('ads_settlement_income_company_shop_daily_type','income_amount'),
                        ('ads_settlement_expense_company_shop_daily_type','expense_amount')):
        check=query(cursor,sql.SQL('''SELECT stat_date,SUM({}) amount FROM ads.{}
            WHERE platform_code='wechat_channels' AND shop_code=%s AND stat_date BETWEEN %s AND %s
            GROUP BY stat_date''').format(sql.Identifier(field),sql.Identifier(table)),
            (task['resolved_shop_code'],start,end))
        observed={str(row['stat_date']):row['amount'] for row in check}
        idx=1 if field=='income_amount' else 2
        if any(observed.get(day,Decimal(0))!=values[idx] for day,values in expected.items()):
            raise RuntimeError('结算收入/支出分类ADS与参考文件不一致')
    monthly=query(cursor,'''WITH daily AS (SELECT DATE_TRUNC('month',stat_date)::date stat_month,
        SUM(included_event_count) events,SUM(income_amount) income,SUM(expense_amount) expense,
        SUM(settlement_net_amount) net FROM ads.ads_settlement_net_company_shop_daily
        WHERE platform_code='wechat_channels' AND shop_code=%s GROUP BY 1)
        SELECT d.stat_month FROM daily d FULL JOIN
        (SELECT * FROM ads.ads_settlement_net_company_shop_monthly WHERE platform_code='wechat_channels'
            AND shop_code=%s) m USING(stat_month)
        WHERE (d.events,d.income,d.expense,d.net) IS DISTINCT FROM
              (m.included_event_count,m.income_amount,m.expense_amount,m.settlement_net_amount)''',
        (task['resolved_shop_code'],task['resolved_shop_code']))
    if monthly:raise RuntimeError('结算日/月ADS不一致')
    totals=[sum((v[i] for v in expected.values()),0) for i in range(4)]
    return {'days':len(expected),'events':totals[0],'income':totals[1],'expense':totals[2],
            'net':totals[3],'daily_and_monthly_differences':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--ingest-run',required=True);p.add_argument('--output',required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--wait-seconds',type=int,default=180)
    p.add_argument('--env-file',default=str(ROOT/'.env'))
    args=p.parse_args();load_pg_env(args.env_file)
    service=FileIngestService(argparse.Namespace(host=os.environ['PGHOST'],pg_port=int(os.getenv('PGPORT','5432')),
        dbname=os.environ['PGDATABASE'],user=os.environ['PGUSER'],password=os.getenv('PGPASSWORD')))
    record={'checked_at':datetime.now().astimezone().isoformat(),'ingest_run_id':args.ingest_run,'applied':False}
    output=Path(args.output)
    with psycopg2.connect(cursor_factory=RealDictCursor) as conn:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            task,expected,months,reference=source_reference(cur,args.ingest_run,service.storage_root)
            before=raw_fingerprint(cur)
            outside=outside_fingerprints(cur,[task['resolved_shop_code']],months)
            failures=query(cur,'''SELECT t.etl_task_id,e.refresh_context FROM ops.etl_task t
                JOIN ops.etl_run e USING(etl_run_id) WHERE e.ingest_run_id=%s
                AND t.etl_key='wechat_channels_settlement' AND t.status='failed'
                ORDER BY e.created_at DESC LIMIT 1''',(args.ingest_run,))
    record.update(reference=reference,ods_before=before,outside_before=outside,
                  shops=[task['resolved_shop_code']],months=months)
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    if not args.apply:
        print(json.dumps({'reference':reference,'failed_task_found':bool(failures),'applied':False},ensure_ascii=False,default=str));return
    if not failures:raise RuntimeError('未找到该记录关联的视频号结算失败任务')
    frozen=failures[0]['refresh_context'] or {}
    if frozen.get('mode')!='incremental' or frozen.get('months')!={'wechat_channels':months} or frozen.get('shops')!={'wechat_channels':[task['resolved_shop_code']]}:
        raise RuntimeError('原失败任务的范围不等于本店受影响月份，停止而不扩大刷新')
    with service.transaction() as cur:
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
        for path in MIGRATIONS:cur.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))
    retry=service.retry_etl_task(str(failures[0]['etl_task_id']),'人工修复：视频号结算来源',None)
    record['retry']=retry
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'retry_run':retry['etl_run_id'],'months':retry['months'],'shops':retry['shops']},ensure_ascii=False),flush=True)
    deadline=time.monotonic()+args.wait_seconds
    with psycopg2.connect(cursor_factory=RealDictCursor) as watch:
        watch.autocommit=True
        while True:
            with watch.cursor() as cur:
                result=query(cur,'SELECT status,error_message FROM ops.etl_run WHERE etl_run_id=%s',(retry['etl_run_id'],))[0]
            if result['status'] not in ('queued','running'):break
            if time.monotonic()>deadline:raise RuntimeError('关联重试仍在队列或运行中，请根据输出的运行ID继续查看')
            time.sleep(2)
    record['retry_result']=result
    if result['status']!='success':
        output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        raise RuntimeError('关联重试未全部成功，请检查该运行的失败节点')
    with psycopg2.connect(cursor_factory=RealDictCursor) as conn:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            if before!=raw_fingerprint(cur):raise RuntimeError('原始ODS内容摘要变化')
            if outside!=outside_fingerprints(cur,[task['resolved_shop_code']],months):raise RuntimeError('范围外结算记录发生变化')
            record['reconciliation']=reconcile(cur,task,expected)
    record.update(applied=True,ods_unchanged=True,outside_scope_unchanged=True)
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(record['reconciliation'],ensure_ascii=False,default=str))


if __name__=='__main__':
    main()
