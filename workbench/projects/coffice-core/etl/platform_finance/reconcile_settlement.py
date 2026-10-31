"""Reconcile source exports by day and month before committing settlement ADS.

An explicit manifest binds reference files to ODS by SHA256, not filenames.
--apply stages affected pipelines in one transaction; any mismatch rolls back.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import importlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from etl.common.settlement_sources import ROOT, TABLES, ensure_schema, load_pg_env

DATE_COLUMNS = {
    'douyin':'结算时间','jd':'账单日期','ks':'实际结算时间','pdd':'发生时间',
    'xhs':'结算时间','wechat_channels':'记账时间',
}
FEE_KEYWORDS = (
    '品牌新享-首单拉新计划','限时红包代商家垫付扣回','淘金币软件服务费','基础软件服务费',
    '光合平台软件服务费','淘宝内容推广服务费','淘宝客佣金代扣款','先用后付技术服务费',
    '天猫佣金（类目系统）','代扣返点积分','代扣交易退回积分','消费者体验提升计划服务费',
    '商家集运','淘宝联盟佣金代扣','淘宝联盟推广佣金返还','天猫保证金履约险追偿','支付宝转账小额打款',
)
RAW_TABLES = [t for ts in TABLES.values() for t in ts] + [
    'ods_jd_settlement_raw','ods_pdd_settlement_raw','ods_wechat_channels_settlement_raw',
]


def norm(value):
    return '' if value is None else str(value).replace('\ufeff','').strip()


def amount(value):
    text = norm(value).replace(',','')
    return Decimal(0) if text in ('','-','--') else Decimal(text)


def money_values(platform, table, r, *, settlement=False):
    def a(key):
        value = amount(r.get(key))
        return value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP) if settlement else value
    if platform == 'douyin':
        return a('收入合计'),-a('支出合计'),a('结算金额'),True
    if platform == 'ks':
        return a('合计收入(元)'),a('合计支出(元)'),a('实际结算金额(元)'),True
    if platform == 'pdd':
        inc, exp = a('收入金额（+元）'),-a('支出金额（-元）')
        if settlement and (norm(r.get('账务类型')) == '退款' or (
            norm(r.get('账务类型')) == '优惠券结算'
            and norm(r.get('业务描述')).split('|', 1)[0] == '0020005'
        )):
            # Confirmed PDD settlement presentation: refunds reduce income;
            # removing them from expense preserves the original settlement net.
            refund = a('支出金额（-元）')
            inc, exp = inc + refund, exp + refund
    elif platform == 'jd':
        net = a('金额'); direction = norm(r.get('收支方向'))
        return net if direction=='收入' else Decimal(0),-net if direction=='支出' else Decimal(0),net,True
    elif platform == 'xhs':
        net = a('动账金额'); income = 'income' in table or norm(r.get('业务款项'))=='申诉调账'
        return net if income else Decimal(0),Decimal(0) if income else -net,net,True
    elif platform == 'wechat_channels':
        value = a('收支金额'); direction = norm(r.get('收支类型'))
        inc,exp = (value if direction=='收入' else Decimal(0)),(value if direction=='支出' else Decimal(0))
    elif platform == 'tmall':
        agg = 'aggregate' in table
        inc = a('收入金额(元)' if agg else '收入金额（+元）')
        exp = a('支出金额(元)' if agg else '支出金额（-元）') * (1 if agg else -1)
        if settlement:
            kind = norm(r.get('入帐类型' if agg else '业务类型')).replace('\t','')
            desc = (norm(r.get('备注')) or norm(r.get('业务描述'))).replace('\t','')
            income_eligible = kind == ('交易收款' if agg else '交易付款')
            expense_eligible = kind in ('扣款','扣款退回','交易分账','转账','其它') and any(k in desc for k in FEE_KEYWORDS)
            signed = inc-exp
            inc,exp = inc if income_eligible else Decimal(0),-signed if expense_eligible else Decimal(0)
            return inc,exp,inc-exp,income_eligible or expense_eligible
    else:
        raise ValueError(platform)
    return inc,exp,inc-exp,True


def records(entry):
    path = Path(entry['path'])
    if path.suffix.lower()=='.csv':
        for enc in ('utf-8-sig','gb18030','utf-16'):
            try:
                data=list(csv.reader(path.read_text(encoding=enc).splitlines())); break
            except UnicodeError:
                continue
        else:
            raise ValueError('文件编码无法识别')
    else:
        wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
        try:
            ws=wb[entry['sheet']]; ws.reset_dimensions(); data=list(ws.values)
        finally:
            wb.close()
    header=[norm(v) for v in data[entry['header_row']-1]]
    platform,table=entry['platform_code'],entry['target_table']
    date_col=DATE_COLUMNS.get(platform,'入帐日期' if 'aggregate' in table else '发生时间')
    for n,vals in enumerate(data[entry['header_row']:],entry['header_row']+1):
        r=dict(zip(header,vals)); text=norm(r.get(date_col))
        try:
            day=datetime.strptime(text,'%Y%m%d').date() if len(text)==8 and text.isdigit() else date.fromisoformat(text[:10])
        except ValueError:
            continue  # Non-data platform footer; ODS count and five samples are checked below.
        yield n,day,r


def totals(rows,platform,table,settlement=False):
    result=defaultdict(lambda:[0,Decimal(0),Decimal(0),Decimal(0)])
    for _,day,row in rows:
        inc,exp,net,eligible=money_values(platform,table,row,settlement=settlement)
        if eligible:
            t=result[day]; t[0]+=1; t[1]+=inc; t[2]+=exp; t[3]+=net
    return dict(result)


def ods_fingerprints(cursor):
    result={}
    for table in RAW_TABLES:
        cursor.execute(sql.SQL('''SELECT batch_id,COUNT(*),MD5(STRING_AGG(MD5(TO_JSONB(r)::text),'' ORDER BY id))
            FROM ods.{} r GROUP BY batch_id ORDER BY batch_id''').format(sql.Identifier(table)))
        result[table]={str(row[0]):[row[1],row[2]] for row in cursor.fetchall()}
    return result


def file_baselines(cursor,entries,start,end,*,register_coverage=True):
    expected=defaultdict(lambda:[0,Decimal(0),Decimal(0),Decimal(0)])
    checks=[]
    for entry in entries:
        path=Path(entry['path']); digest=hashlib.sha256(path.read_bytes()).hexdigest()
        table,platform=entry['target_table'],entry['platform_code']
        cursor.execute('''SELECT l.batch_id,c.shop_code,c.shop_name,l.source_sheet_name
            FROM ods.ods_file_ingest_log l JOIN common.v_ingest_batch_shop_context c USING(batch_id)
            WHERE l.file_hash=%s AND l.target_table=%s AND l.platform_code=%s AND l.ingest_status='success'
              AND c.shop_mapping_status='mapped' AND c.company_code IS NOT NULL''',(digest,table,platform))
        candidates=cursor.fetchall()
        if platform=='xhs':
            candidates=[b for b in candidates if b[3]==entry['sheet']]
        if len(candidates)!=1:
            raise RuntimeError(f'{path.name}无法通过文件摘要唯一关联ODS：{candidates}')
        batch,shop,name,_=candidates[0]
        local=list(records(entry)); raw_totals=totals(local,platform,table)
        cursor.execute(sql.SQL('SELECT * FROM ods.{} WHERE batch_id=%s ORDER BY source_row_no').format(sql.Identifier(table)),(batch,))
        cols=[c.name for c in cursor.description]
        raw=[dict(zip(cols,row)) for row in cursor.fetchall()]
        dtcol=DATE_COLUMNS.get(platform,'入帐日期' if 'aggregate' in table else '发生时间')
        source=[]
        for r in raw:
            text=norm(r[dtcol]); day=datetime.strptime(text,'%Y%m%d').date() if len(text)==8 and text.isdigit() else date.fromisoformat(text[:10])
            source.append((r['source_row_no'],day,r))
        if len(local)!=len(source) or raw_totals!=totals(source,platform,table):
            raise RuntimeError(f'{path.name}文件与ODS逐日行数/收支/净额不一致')
        sample_count=min(5,len(local))
        by_row={r['source_row_no']:r for r in raw}
        for n,_,r in local[:sample_count]:
            actual=by_row.get(n)
            if actual is None or any(norm(v)!=norm(actual[k]) for k,v in r.items() if k in actual):
                raise RuntimeError(f'{path.name}第{n}行原始字段抽样不一致')
        if platform in TABLES:
            if entry.get('unverified_single_source'):
                # A single imported source can be checked without claiming a
                # complete reporting period or authorizing source replacement.
                cursor.execute('''SELECT COUNT(*),COUNT(*) FILTER (
                    WHERE decision_reason<>'unverified_single_source')
                    FROM common.v_settlement_source_decision WHERE batch_id=%s''',(batch,))
                n, invalid = cursor.fetchone()
                if not n or invalid:
                    raise RuntimeError(f'批次{batch}不是未声明范围的单一有效来源')
                cursor.execute('''SELECT COUNT(*) FROM common.v_settlement_source_decision d
                    JOIN common.v_effective_settlement_source s
                      ON s.shop_identity_key=d.shop_identity_key AND s.target_table=d.target_table
                     AND s.stat_date=d.stat_date AND s.source_group_key<>d.source_group_key
                    WHERE d.batch_id=%s''',(batch,))
                if cursor.fetchone()[0]:
                    raise RuntimeError(f'批次{batch}存在其他有效来源，不能按单一来源验收')
            elif 'start' not in entry or 'end' not in entry or not entry.get('evidence'):
                raise ValueError('覆盖选择需要明确的完整查询范围和确认依据')
            else:
                # Verification/refresh must not itself authorize a new source.
                # Historical registrations remain readable on all platforms.
                cursor.execute('SELECT period_start,period_end,file_hash FROM common.settlement_source_registry WHERE batch_id=%s',(batch,))
                if cursor.fetchone()!=(date.fromisoformat(entry['start']),date.fromisoformat(entry['end']),digest):
                    if platform != 'douyin' or not _matches_approved_douyin_source(cursor,shop,local,entry):
                        raise RuntimeError(f'批次{batch}缺少与参考文件一致的已提交覆盖登记或逐日采信；核对工具不再新增人工登记。'
                                           '请先通过受支持的预检采信流程或可信自动化回执处理；不得以 --apply 绕过。')
        metric=totals(local,platform,table,settlement=True)
        summary=[0,Decimal(0),Decimal(0),Decimal(0)]
        for day,value in metric.items():
            if start<=day<=end:
                key=(platform,shop,day)
                for i in range(4): expected[key][i]+=value[i]; summary[i]+=value[i]
        checks.append({'file':path.name,'path':str(path),'sheet':entry.get('sheet'),'batch_id':batch,
            'platform_code':platform,'shop_code':shop,'shop_name':name,'file_hash':digest,
            'raw_rows':len(local),'sample_rows':sample_count,'events':summary[0],
            'coverage_verified':not entry.get('unverified_single_source',False),
            'income':summary[1],'expense':summary[2],'net':summary[3]})
    return dict(expected),checks


def _matches_approved_douyin_source(cursor, shop, local, entry):
    """Allow checking already approved new-workflow files without registering."""
    from apps.file_ingest.coverage import fingerprint_rows
    from etl.douyin.load_douyin_settlement_ods import CONFIG
    cursor.execute('''SELECT s.stat_date FROM common.v_ingest_source_day_selection s
        JOIN dim.dim_platform_shop_company d USING(shop_identity_key)
        WHERE d.platform_code='douyin' AND d.shop_code=%s AND d.is_active
          AND s.target_table='ods_douyin_settlement_raw' AND s.stat_date BETWEEN %s AND %s''',
        (shop,entry['start'],entry['end']))
    chosen={r[0] for r in cursor.fetchall()}
    if not chosen or not {day for _,day,_ in local}.issubset(chosen):
        return False
    cursor.execute('''SELECT r.* FROM common.v_current_douyin_settlement_raw r
        JOIN common.v_ingest_batch_shop_context c USING(batch_id)
        WHERE c.shop_code=%s AND r."结算时间"::timestamp::date BETWEEN %s AND %s''',
        (shop,entry['start'],entry['end']))
    cols=[c.name for c in cursor.description]
    current=[dict(zip(cols,r)) for r in cursor.fetchall()]
    return fingerprint_rows([r for _,_,r in local],CONFIG.expected_columns)==fingerprint_rows(current,CONFIG.expected_columns)


def stage_pipelines(cursor):
    for platform in ('douyin','ks','xhs','tmall'):
        module='run_tmall_settlement_from_funds_etl' if platform=='tmall' else f'run_{platform}_settlement_metrics_etl'
        m=importlib.import_module(f'etl.{platform}.{module}')
        m.execute_files(cursor,m.PREPARE_SQL_FILES)
        if platform=='tmall':
            legacy=m.legacy_available(cursor)
            m.execute_files(cursor,m.LEGACY_CREATE_SQL_FILES)
            if legacy: m.execute_files(cursor,m.LEGACY_REFRESH_SQL_FILES)
            m.execute_files(cursor,m.FUND_CREATE_SQL_FILES); m.execute_files(cursor,m.ALL_DWS_CREATE_SQL_FILES)
            source=m.validate_sources(cursor); m.validate_batch_mapping(cursor)
            m.execute_files(cursor,m.FUND_REFRESH_SQL_FILES); m.execute_files(cursor,m.COMBINE_SQL_FILES)
            m.execute_files(cursor,m.ADS_CREATE_SQL_FILES); m.execute_files(cursor,m.ADS_REFRESH_SQL_FILES)
            m.validate_pipeline(cursor,source,legacy); m.validate_comments(cursor)
        else:
            source=m.validate_ods(cursor); m.validate_batch_shop_mapping(cursor)
            m.execute_files(cursor,m.CREATE_SQL_FILES); m.execute_files(cursor,m.REFRESH_SQL_FILES)
            if platform=='xhs': m.validate_result(cursor,source)
            else:
                m.validate_pipeline(cursor,source[0] if platform=='ks' else source); m.validate_comments(cursor)
        print(f'{platform}: 来源/粒度/组成金额/DWS/ADS/公司归属校验通过',flush=True)
    shared=importlib.import_module('etl.platform_finance.run_settlement_shared_ads_etl')
    shared.execute_files(cursor,shared.PREPARE_SQL_FILES); shared.execute_files(cursor,shared.CREATE_SQL_FILES)
    shared.validate_dws_sources(cursor); shared.execute_files(cursor,shared.REFRESH_SQL_FILES)
    shared.validate_result(cursor)


def reconcile(cursor,expected,start,end):
    query='''SELECT platform_code,shop_code,stat_date,SUM(included_event_count),
        SUM(income_amount),SUM(expense_amount),SUM(settlement_net_amount)
        FROM ads.ads_settlement_net_company_shop_daily WHERE stat_date BETWEEN %s AND %s GROUP BY 1,2,3'''
    cursor.execute(query,(start,end))
    actual={tuple(r[:3]):list(r[3:]) for r in cursor.fetchall()}
    if expected!=actual:
        keys=sorted(set(expected)|set(actual))
        bad=[{'key':k,'file':expected.get(k),'ads':actual.get(k)} for k in keys if expected.get(k)!=actual.get(k)]
        raise RuntimeError('文件与ADS逐日结算不一致：'+json.dumps(bad[:15],ensure_ascii=False,default=str))
    summary=defaultdict(lambda:[0,Decimal(0),Decimal(0),Decimal(0)])
    for (platform,shop,_),values in expected.items():
        for i in range(4): summary[(platform,shop)][i]+=values[i]
    cursor.execute('''SELECT platform_code,shop_code,SUM(included_event_count),SUM(income_amount),
        SUM(expense_amount),SUM(settlement_net_amount) FROM ads.ads_settlement_net_company_shop_monthly
        WHERE stat_month=%s GROUP BY 1,2''',(start.replace(day=1),))
    monthly={tuple(r[:2]):list(r[2:]) for r in cursor.fetchall()}
    if dict(summary)!=monthly:
        raise RuntimeError('月度ADS与来源文件汇总不一致')
    cursor.execute("SELECT COUNT(*) FROM pg_attribute WHERE attrelid='common.settlement_source_registry'::regclass AND attnum>0 AND NOT attisdropped AND col_description(attrelid,attnum) IS NULL")
    if cursor.fetchone()[0]: raise RuntimeError('来源登记表字段注释遗漏')
    cursor.execute("SELECT obj_description('common.settlement_source_registry'::regclass)")
    if not cursor.fetchone()[0]: raise RuntimeError('来源登记表表注释遗漏')
    return [{'platform_code':p,'shop_code':s,'events':v[0],'income':v[1],'expense':v[2],'net':v[3],'difference':Decimal(0)} for (p,s),v in sorted(summary.items())],query


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest'); p.add_argument('--output',required=True)
    p.add_argument('--start',default='2026-09-01'); p.add_argument('--end',default='2026-09-30')
    p.add_argument('--apply',action='store_true'); p.add_argument('--snapshot-only',action='store_true')
    p.add_argument('--before-snapshot'); p.add_argument('--env-file',default=str(ROOT/'.env'))
    p.add_argument('--check-ks-file',help='只检查快手原始文件的商家ID、行数及金额，不连接数据库')
    args=p.parse_args(); load_pg_env(args.env_file)
    start,end=date.fromisoformat(args.start),date.fromisoformat(args.end)
    if start.day!=1 or end!=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1]):
        raise ValueError('月度验收需要对应自然月的月初至月末')
    output=Path(args.output)
    if args.check_ks_file:
        rows=list(records({'path':args.check_ks_file,'sheet':'0','header_row':1,
            'platform_code':'ks','target_table':'ods_ks_settlement_raw'}))
        ids=sorted({norm(row['商家ID']) for _,_,row in rows})
        values=totals(rows,'ks','ods_ks_settlement_raw')
        record={'merchant_ids':ids,'rows':len(rows),'net':sum((v[3] for v in values.values()),Decimal(0))}
        output.write_text(json.dumps(record,ensure_ascii=False,default=str),encoding='utf-8')
        print(json.dumps(record,ensure_ascii=False,default=str)); return
    with psycopg2.connect(application_name='settlement_reconcile') as conn:
        conn.set_session(isolation_level='REPEATABLE READ',readonly=not args.apply)
        with conn.cursor() as cursor:
            before=ods_fingerprints(cursor)
            if args.snapshot_only:
                output.write_text(json.dumps(before,indent=2),encoding='utf-8')
                print('已保存ODS原始事实摘要，未修改数据库'); return
            if not args.manifest: raise ValueError('需要显式来源清单')
            if args.apply: ensure_schema(cursor)
            expected,checks=file_baselines(cursor,json.loads(Path(args.manifest).read_text(encoding='utf-8-sig')),start,end,
                register_coverage=args.apply)
            if args.apply: stage_pipelines(cursor)
            results,query=reconcile(cursor,expected,start,end)
            after=ods_fingerprints(cursor)
            if before!=after: raise RuntimeError('刷新过程中ODS原始事实发生变化')
            if args.before_snapshot:
                original=json.loads(Path(args.before_snapshot).read_text(encoding='utf-8'))
                for table,batches in original.items():
                    if any(after[table].get(b)!=v for b,v in batches.items()):
                        raise RuntimeError('修复前后历史ODS事实摘要不一致')
            cursor.execute('''SELECT platform_code,target_table,batch_id,covered_by_batch_id,decision_reason,
                SUM(source_rows) rows FROM common.v_settlement_source_decision
                WHERE stat_date BETWEEN %s AND %s GROUP BY 1,2,3,4,5 ORDER BY 1,2,3''',(start,end))
            cols=[c.name for c in cursor.description]; decisions=[dict(zip(cols,r)) for r in cursor.fetchall()]
            record={'checked_at':datetime.now().astimezone().isoformat(),'applied':False,
                'commit_status':'staged_verified' if args.apply else 'read_only_verified',
                'start':start,'end':end,'results':results,'file_checks':checks,'decisions':decisions,
                'daily_keys':len(expected),'ods_unchanged':True,'ads_query':query}
            # Store the evidence before committing; a filesystem failure also rolls back.
            output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        if not args.apply: conn.rollback()
    record['applied']=args.apply
    record['commit_status']='committed' if args.apply else 'read_only_verified'
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'applied':args.apply,'shops':len(results),'daily_keys':len(expected),
        'file_sheets':len(checks),'differences':0,'ods_unchanged':True},ensure_ascii=False))


if __name__=='__main__':
    main()
