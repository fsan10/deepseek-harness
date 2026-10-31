"""Migrate and verify operating treatment atomically; .env is process-scoped.

Without --apply the complete refresh is rolled back, including audit records.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import PLATFORMS, ROOT, prepare_schema, refresh_projection, validate_projection


def refresh_all(cursor, platforms=PLATFORMS):
    """Refresh and validate the complete seven-platform chain in the caller transaction."""
    prepare_schema(cursor)
    results={}
    for platform,module in (
        ('douyin','etl.douyin.run_douyin_platform_expense_etl'),
        ('ks','etl.ks.run_ks_platform_expense_etl'),
        ('jd','etl.jd.run_jd_main_business_finance_etl'),
        ('tmall','etl.tmall.run_tmall_main_business_finance_etl')):
        if platform not in platforms:
            continue
        implementation=importlib.import_module(module)
        print(f'{platform}：校验ODS和批次店铺，刷新来源公式及经营归属',flush=True)
        implementation.execute_files(cursor,implementation.PREPARE_SQL_FILES)
        ods=implementation.validate_ods(cursor)
        implementation.execute_files(cursor,implementation.CREATE_SQL_FILES)
        implementation.execute_files(cursor,implementation.REFRESH_SQL_FILES)
        implementation.validate_comments(cursor)
        results[platform]=(implementation.validate_results(cursor) if platform=='tmall' else implementation.validate_pipeline(cursor,ods))
    from etl.platform_finance import run_pdd_wechat_xhs_main_business_finance_etl as remaining
    for platform in ('pdd','wechat_channels','xhs'):
        if platform not in platforms:
            continue
        print(f'{platform}：校验ODS和批次店铺，刷新来源公式及经营归属',flush=True)
        remaining.execute_files(cursor,remaining.PREPARE_SQL_FILES)
        remaining.validate_ods(cursor,platform)
        remaining.validate_batch_mapping(cursor,platform)
        create,refresh=remaining.files_for_scope(platform)
        remaining.execute_files(cursor,create)
        remaining.execute_files(cursor,refresh)
        remaining.validate_comments(cursor,platform)
        remaining.validate_dws_ads(cursor,platform)
        remaining.validate_reconciliation(cursor,platform)
    from etl.platform_finance import run_douyin_ks_main_business_income_etl as income
    for platform,create,refresh in (
        ('douyin',income.DOUYIN_CREATE_SQL_FILES,income.DOUYIN_REFRESH_SQL_FILES),
        ('ks',income.KS_CREATE_SQL_FILES,income.KS_REFRESH_SQL_FILES)):
        if platform not in platforms:
            continue
        income.validate_ods(cursor,platform)
        income.validate_batch_mapping(cursor,platform)
        income.execute_files(cursor,create)
        income.execute_files(cursor,refresh)
        income.validate_reconciliation(cursor,platform)
    refresh_projection(cursor)
    income.execute_files(cursor,income.SHARED_REFRESH_SQL_FILES)
    for platform in PLATFORMS:
        validate_projection(cursor,platform)
    from etl.platform_bank_summary import run_platform_bank_summary_etl as summary
    summary.validate_required_objects(cursor)
    summary.execute_files(cursor,summary.MIGRATION_SQL_FILES)
    summary.execute_files(cursor,summary.REFRESH_SQL_FILES)
    summary.validate_result(cursor,False)
    cursor.execute('''SELECT platform_code,COUNT(*),MIN(stat_date),MAX(stat_date),
        SUM(income_amount),SUM(expense_amount),COUNT(*) FILTER(WHERE mapping_status='unmapped'),
        COUNT(*) FILTER(WHERE operating_treatment IS NULL)
        FROM ads.ads_platform_operating_flow_company_shop_daily_scene GROUP BY 1 ORDER BY 1''')
    final=cursor.fetchall()
    print('经营归属验收（平台/行数/日期/收入/支出/未映射分类/性质待确认）：',flush=True)
    print(json.dumps(final,ensure_ascii=False,default=str),flush=True)
    cursor.execute('''SELECT COUNT(*) FROM ads.ads_platform_operating_flow_company_shop_daily_scene
        WHERE income_amount-expense_amount+excluded_amount<>source_signed_amount''')
    if cursor.fetchone()[0]:
        raise RuntimeError('经营归属金额分流不守恒')
    cursor.execute('''SELECT COUNT(*) FROM information_schema.columns c
        WHERE (c.table_schema,c.table_name) IN (
            SELECT n.nspname,p.relname FROM pg_class p JOIN pg_namespace n ON n.oid=p.relnamespace
            WHERE p.relname LIKE '%operating_flow%')
        AND col_description((c.table_schema||'.'||c.table_name)::regclass,c.ordinal_position) IS NULL''')
    if cursor.fetchone()[0]:
        raise RuntimeError('经营收支新增字段注释不完整')
    return final


def main():
    parser=argparse.ArgumentParser(description='经营收支归属迁移及七平台验收，默认事务预演')
    parser.add_argument('--apply',action='store_true',help='提交已验收的映射、DWS和ADS')
    args=parser.parse_args()
    load_pg_env()
    connection=psycopg2.connect(host=os.getenv('PGHOST','192.168.77.111'),port=os.getenv('PGPORT','5432'),
        dbname=os.getenv('PGDATABASE','mock_coffice'),user=os.getenv('PGUSER','postgres'),password=os.getenv('PGPASSWORD'),
        options='-c lock_timeout=10000 -c statement_timeout=120000')
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
            final = refresh_all(cursor)
        if args.apply:
            from apps.file_ingest.service import FileIngestService
            with connection.cursor(cursor_factory=RealDictCursor) as audit:
                FileIngestService._write_log(audit,'fee_mapping_assign','fee_mapping',None,
                    'Codex（按用户授权实施）',None,'上线经营收支三态归属、未映射金额保留及全部类型明细',
                    {'platforms':list(PLATFORMS),'validated_totals':json.loads(json.dumps(final,default=str))})
            connection.commit()
            print('已提交迁移与验收结果',flush=True)
        else:
            connection.rollback()
            print('事务预演通过，所有修改已回滚',flush=True)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__=='__main__':
    main()
