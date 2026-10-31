"""Atomically reconcile operating sources while protecting settlement and ODS.

Uses the existing seven-platform formulas and editable finance classifications.
The default is a rollback preview; --apply commits only after two identical
refreshes, raw-fact/configuration invariants and the settlement file check pass.
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2 import sql

from etl.common.settlement_sources import load_pg_env
from etl.common.finance_sources import verify_fund_files
from etl.platform_finance.reconcile_settlement import RAW_TABLES, file_baselines, reconcile
from etl.platform_finance.run_operating_treatment_migration import refresh_all
from etl.platform_finance.operating_treatment import PLATFORMS

ADS = ('ads_platform_main_business_income_company_shop_daily_category',
       'ads_platform_expense_company_shop_daily_category',
       'ads_platform_operating_flow_company_shop_daily_scene')
RAW = (*RAW_TABLES, 'ods_douyin_fund_raw', 'ods_ks_fund_raw', 'ods_jd_fund_raw')


def fingerprints(cursor, schema, tables, *, exclude=()):
    result = {}
    for table in tables:
        cursor.execute(sql.SQL('''SELECT COUNT(*),MD5(COALESCE(STRING_AGG(v,'' ORDER BY v),''))
            FROM (SELECT MD5((TO_JSONB(r)-%s::text[])::text) v FROM {}.{} r) s''').format(
            sql.Identifier(schema),sql.Identifier(table)),(list(exclude),))
        result[table] = cursor.fetchone()
    return result


def mappings(cursor):
    cursor.execute("SELECT mapping_id,TO_JSONB(m)-'updated_at' FROM dim.dim_platform_fee_mapping m ORDER BY mapping_id")
    return dict(cursor.fetchall())


def monthly_totals(cursor, start, end):
    cursor.execute('''SELECT platform_code,shop_code,MAX(shop_name),SUM(income_amount),SUM(expense_amount)
        FROM ads.ads_platform_operating_flow_company_shop_daily_scene
        WHERE stat_date BETWEEN %s AND %s GROUP BY 1,2 ORDER BY 1,2''',(start,end))
    return [{'platform_code':p,'shop_code':s,'shop_name':n,'income':i,'expense':e,'net':i-e}
            for p,s,n,i,e in cursor.fetchall()]


def validate_source_rows(cursor):
    """Check selected ODS identities against candidate DWD, before routing."""
    checks = []
    specs = [
        ('douyin','main_business_income','settlement'),
        ('douyin','platform_expense','settlement'),('douyin','platform_expense','fund'),
        ('ks','main_business_income','settlement'),('ks','main_business_income','fund'),
        ('ks','platform_expense','settlement'),('ks','platform_expense','fund'),
        ('pdd','main_business_income','settlement'),('pdd','platform_expense','settlement'),
        ('wechat_channels','main_business_income','settlement'),
        ('wechat_channels','platform_expense','settlement'),
    ]
    for platform,metric,document in specs:
        dwd=f'dwd_{platform}_{metric}_source_detail'
        source=f'v_current_{platform}_{document}_raw'
        condition = sql.SQL('WHERE source_document_type=%s') if platform in ('douyin','ks') else sql.SQL('')
        if platform=='douyin' and metric=='main_business_income':
            condition=sql.SQL('')
        params=(document,) if condition.as_string(cursor) else ()
        cursor.execute(sql.SQL('''WITH expected AS (SELECT id FROM common.{}),
            actual AS (SELECT DISTINCT source_id id FROM dwd.{} {})
            SELECT (SELECT COUNT(*) FROM expected),(SELECT COUNT(*) FROM actual),
              (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) x)
             +(SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) x)''').format(
                sql.Identifier(source),sql.Identifier(dwd),condition),params)
        expected, actual, difference=cursor.fetchone()
        if difference:
            raise RuntimeError(f'{dwd}/{document}来源身份差异：{expected}/{actual}/{difference}')
        checks.append({'platform':platform,'metric':metric,'document':document,
                       'source_rows':expected,'dwd_source_rows':actual,'difference':difference})
    # JD's documented seven-field event identity and Tmall's account flow
    # identity remain scoped to the shop; compare both candidate chains.
    for platform,document,source,key in (
        ('jd','settlement','ods.ods_jd_settlement_raw',
         '''NULLIF(REPLACE(REPLACE(BTRIM(r."单据编号"),'="',''),'"',''),'')'''),
        ('jd','fund','ods.ods_jd_fund_raw',
         '''MD5(CONCAT_WS(E'\\x1f',BTRIM(COALESCE(r."商户订单号",'')),
             BTRIM(COALESCE(r."交易订单号",'')),BTRIM(COALESCE(r."支出类型",'')),
             BTRIM(COALESCE(r."交易金额",'')),BTRIM(COALESCE(r."交易类型",'')),
             BTRIM(COALESCE(r."入账时间",'')),BTRIM(COALESCE(r."资金动账备注",''))))'''),
        ('tmall','aggregate','common.v_current_tmall_aggregate_fund_raw','NULLIF(BTRIM(r."支付流水号"),\'\')'),
        ('tmall','alipay','common.v_current_tmall_alipay_fund_raw',
         '''NULLIF(BTRIM(REPLACE(r."账务流水号",E'\\t','')),'')'''),
    ):
        for metric in ('main_business_income','platform_expense'):
            field='source_document_type' if platform=='jd' else 'source_account_type'
            cursor.execute(f'''WITH keyed AS (
                SELECT r.id,c.shop_identity_key,{key} k,r.ingest_time
                FROM {source} r JOIN common.v_ingest_batch_shop_context c USING(batch_id)
            ),expected AS (
                SELECT DISTINCT ON (shop_identity_key,k) id FROM keyed WHERE k IS NOT NULL
                ORDER BY shop_identity_key,k,ingest_time DESC,id DESC
            ),actual AS (
                SELECT source_id id FROM dwd.dwd_{platform}_{metric}_source_detail WHERE {field}=%s
            ) SELECT (SELECT COUNT(*) FROM expected),(SELECT COUNT(*) FROM actual),
              (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) x)
             +(SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) x)''',(document,))
            expected,actual,difference=cursor.fetchone()
            if difference:
                raise RuntimeError(f'{platform}/{metric}/{document}来源身份差异：{difference}')
            checks.append({'platform':platform,'metric':metric,'document':document,
                           'source_rows':expected,'dwd_source_rows':actual,'difference':difference})
    for metric,expected_sql,actual_sql in (
        ('income', '''SELECT id FROM common.v_current_xhs_settlement_income_raw
            UNION ALL SELECT -id FROM common.v_current_xhs_settlement_expense_raw
            WHERE BTRIM("业务款项")='申诉调账' ''',
         'SELECT source_id id FROM dwd.dwd_xhs_main_business_income_source_detail'),
        ('expense', '''SELECT 'income'::text source_table,id FROM common.v_current_xhs_settlement_income_raw
            UNION ALL SELECT 'expense',id FROM common.v_current_xhs_settlement_expense_raw
            WHERE BTRIM("业务款项")<>'申诉调账' ''',
         'SELECT DISTINCT source_table,source_id id FROM dwd.dwd_xhs_platform_expense_source_detail'),
    ):
        cursor.execute(f'''WITH expected AS ({expected_sql}),actual AS ({actual_sql})
            SELECT (SELECT COUNT(*) FROM expected),(SELECT COUNT(*) FROM actual),
              (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) x)
             +(SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) x)''')
        expected,actual,difference=cursor.fetchone()
        if difference:
            raise RuntimeError(f'xhs/{metric}来源身份差异：{difference}')
        checks.append({'platform':'xhs','metric':metric,'source_rows':expected,
                       'dwd_source_rows':actual,'difference':difference})
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settlement-manifest',required=True)
    parser.add_argument('--fund-manifest',required=True,help='显式标准店铺及独立资金参考文件，缺少导入或字段不一致时停止')
    parser.add_argument('--output',required=True)
    parser.add_argument('--start',default='2026-09-01')
    parser.add_argument('--end',default='2026-09-30')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--platform',action='append',choices=PLATFORMS,
                        help='仅重建指定平台来源DWD/DWS；仍验收七平台ADS及纯结算，默认全部平台')
    args=parser.parse_args()
    start,end=date.fromisoformat(args.start),date.fromisoformat(args.end)
    if start.day!=1 or end!=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1]):
        raise ValueError('月度验收需要对应自然月的月初至月末')
    entries=json.loads(Path(args.settlement_manifest).read_text(encoding='utf-8-sig'))
    load_pg_env()
    connection=psycopg2.connect(application_name='operating_source_reconciliation',
        options='-c lock_timeout=10000 -c statement_timeout=120000')
    try:
        connection.set_session(isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
            raw_before=fingerprints(cursor,'ods',RAW)
            settlement_tables=('ads_settlement_net_company_shop_daily','ads_settlement_net_company_shop_monthly')
            settlement_before=fingerprints(cursor,'ads',settlement_tables)
            mapping_before=mappings(cursor)
            before=monthly_totals(cursor,start,end)
            fund_checks=verify_fund_files(cursor,json.loads(Path(args.fund_manifest).read_text(encoding='utf-8-sig')))
            expected,file_checks=file_baselines(cursor,entries,start,end,register_coverage=False)
            settlement_results,_=reconcile(cursor,expected,start,end)
            print('纯结算：源文件、ODS、日/月ADS复核通过',flush=True)
            refresh_all(cursor,args.platform or PLATFORMS)
            lineage=validate_source_rows(cursor)
            first=fingerprints(cursor,'ads',ADS,exclude=('updated_at','created_at'))
            after=monthly_totals(cursor,start,end)
            print('第一次混合经营刷新通过，开始重复刷新验收',flush=True)
            refresh_all(cursor,args.platform or PLATFORMS)
            validate_source_rows(cursor)
            if first != fingerprints(cursor,'ads',ADS,exclude=('updated_at','created_at')):
                raise RuntimeError('两次刷新结果不一致')
            if raw_before != fingerprints(cursor,'ods',RAW):
                raise RuntimeError('ODS原始事实发生变化')
            if settlement_before != fingerprints(cursor,'ads',settlement_tables):
                raise RuntimeError('纯结算ADS发生变化')
            current=mappings(cursor)
            if any(current.get(k)!=v for k,v in mapping_before.items()):
                raise RuntimeError('既有财务经营归属、分类或来源配置发生变化')
            reconcile(cursor,expected,start,end)
            cursor.execute('''SELECT COUNT(*) FROM ads.v_settlement_net_company_shop_monthly_metric v
                JOIN ads.ads_settlement_net_company_shop_monthly m
                  USING(stat_month,platform_code,company_code,shop_code)
                WHERE v.stat_month=%s AND v.amount IS DISTINCT FROM CASE v.metric_code
                    WHEN 'income' THEN m.income_amount
                    WHEN 'expense' THEN COALESCE(m.display_expense_amount,m.expense_amount)
                    WHEN 'settlement_net' THEN m.settlement_net_amount END''',(start.replace(day=1),))
            if cursor.fetchone()[0]:
                raise RuntimeError('用户使用的纯结算月度指标视图与月ADS不一致')
            cursor.execute('''SELECT
                (SELECT COUNT(*) FROM ads.v_settlement_net_company_shop_monthly_metric WHERE stat_month=%s),
                3*(SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_monthly WHERE stat_month=%s)''',
                (start.replace(day=1),start.replace(day=1)))
            observed,expected_metric_rows=cursor.fetchone()
            if observed!=expected_metric_rows:
                raise RuntimeError('纯结算月度指标视图缺少指标行')
            result={'checked_at':datetime.now(timezone.utc).isoformat(),'applied':False,
                    'start':start,'end':end,'before':before,'after':after,
                    'lineage':lineage,'settlement_results':settlement_results,
                    'settlement_file_checks':file_checks,'ods_unchanged':True,
                    'fund_file_checks':fund_checks,'refreshed_platforms':args.platform or list(PLATFORMS),
                    'existing_mapping_unchanged':True,'settlement_unchanged':True,
                    'idempotent':True,'raw_fingerprints':raw_before}
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        if args.apply:
            connection.commit()
            result['applied']=True
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print('来源修复已原子提交，ODS、财务配置和纯结算结果保持不变',flush=True)
        else:
            connection.rollback()
            print('验收预演通过，全部数据库修改已回滚',flush=True)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__=='__main__':
    main()
