"""Rebuild the business category catalog with transactional amount regression.

The default runs the seven-platform refresh twice and rolls back. --apply only
commits if both published income/expense tables retain every daily money total,
including August, while category references and names are unique and complete.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.category_catalog import rebuild_catalog, ALIASES
from etl.platform_finance.reconcile_operating_sources import fingerprints, RAW, ADS, validate_source_rows
from etl.platform_finance.run_operating_treatment_migration import refresh_all


def records(cursor, query, params=()):
    with cursor.connection.cursor(cursor_factory=RealDictCursor) as c:
        c.execute(query, params)
        return [dict(r) for r in c.fetchall()]


def money_signature(cursor):
    """Full daily scene/accounting identity, excluding only classification."""
    return records(cursor, '''WITH amounts AS (
        SELECT stat_date,platform_code,company_code,shop_code,source_document_type,
            secondary_category_code,income_amount,0::numeric expense_amount,
            included_detail_count,included_detail_count source_detail_count
        FROM ads.ads_platform_main_business_income_company_shop_daily_category
        UNION ALL SELECT stat_date,platform_code,company_code,shop_code,source_document_type,
            secondary_category_code,0::numeric,expense_amount,
            included_detail_count,source_detail_count
        FROM ads.ads_platform_expense_company_shop_daily_category)
        SELECT stat_date,platform_code,company_code,shop_code,source_document_type,
            secondary_category_code,SUM(income_amount) income,SUM(expense_amount) expense,
            SUM(included_detail_count) included_rows,SUM(source_detail_count) source_rows
        FROM amounts GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4,5,6''')


def monthly(cursor):
    return records(cursor, '''SELECT date_trunc('month',stat_date)::date stat_month,
        platform_code,company_code,shop_code,sum(income_amount) income,sum(expense_amount) expense
        FROM ads.ads_platform_operating_flow_company_shop_daily_scene
        GROUP BY 1,2,3,4 ORDER BY 1,2,3,4''')


def catalog_state(cursor):
    return {'categories': records(cursor, 'SELECT * FROM dim.dim_platform_fee_primary_category ORDER BY primary_category_code'),
            'mappings': records(cursor, 'SELECT * FROM dim.dim_platform_fee_mapping ORDER BY mapping_id')}


def source_contract(state):
    ignored={'primary_category_code','primary_category_name','updated_at','updated_by'}
    return {r['mapping_id']:{k:v for k,v in r.items() if k not in ignored} for r in state['mappings']}


def validate_catalog(cursor):
    checks={}
    for name, query in (
        ('duplicate_names', '''SELECT count(*) FROM (SELECT dim.platform_category_name_key(primary_category_name)
            FROM dim.dim_platform_fee_primary_category GROUP BY 1 HAVING count(*)>1) x'''),
        ('broken_references', '''SELECT count(*) FROM dim.dim_platform_fee_mapping m
            LEFT JOIN dim.dim_platform_fee_primary_category c USING(primary_category_code)
            WHERE c.primary_category_code IS NULL OR m.primary_category_name<>c.primary_category_name'''),
        ('legacy_alias_references', '''SELECT count(*) FROM dim.dim_platform_fee_mapping
            WHERE primary_category_code=ANY(%s)'''),
        ('unclassified_confirmed', '''SELECT count(*) FROM ads.ads_platform_operating_flow_company_shop_daily_scene
            WHERE operating_treatment IS NOT NULL AND mapping_status='unmapped' '''),
    ):
        cursor.execute(query, (list(ALIASES),) if '%s' in query else ())
        checks[name]=cursor.fetchone()[0]
    if any(checks.values()):
        raise RuntimeError(f'分类目录验收未通过：{checks}')
    return checks


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--apply', action='store_true')
    args=p.parse_args()
    load_pg_env()
    conn=psycopg2.connect(application_name='operating_category_rebuild',
        options='-c lock_timeout=10000 -c statement_timeout=120000')
    try:
        conn.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
            before=catalog_state(c)
            before_money=money_signature(c)
            before_month=monthly(c)
            raw=fingerprints(c,'ods',RAW)
            pure=fingerprints(c,'ads',('ads_settlement_net_company_shop_daily','ads_settlement_net_company_shop_monthly'))
            changes=rebuild_catalog(c)
            print(f'分类引用迁移{len(changes["reclassified"])}条，删除旧分类{len(changes["deleted_categories"])}个',flush=True)
            refresh_all(c)
            if before_money != money_signature(c):
                raise RuntimeError('分类调整改变了原始每日收支或明细数量，已停止提交')
            first=fingerprints(c,'ads',ADS,exclude=('created_at','updated_at'))
            print('全量每日收支回归通过，开始第二次刷新',flush=True)
            refresh_all(c)
            if first != fingerprints(c,'ads',ADS,exclude=('created_at','updated_at')):
                raise RuntimeError('分类迁移后的两次刷新结果不一致')
            after=catalog_state(c)
            if source_contract(before)!=source_contract(after):
                raise RuntimeError('分类迁移改变了原来源职责、退款归属或其他非分类配置')
            if raw!=fingerprints(c,'ods',RAW) or pure!=fingerprints(c,'ads',tuple(pure)):
                raise RuntimeError('分类迁移改变了ODS或纯结算结果')
            validation=validate_catalog(c)
            lineage=validate_source_rows(c)
            after_month=monthly(c)
            if before_month!=after_month:
                raise RuntimeError('月份/公司/店铺经营金额出现变化')
            output={'checked_at':datetime.now(timezone.utc).isoformat(),'applied':False,
                'amount_regression_basis':'pre_rebuild_published_ads; not independent finance acceptance',
                'before':before,'after':after,'changes':changes,'validation':validation,
                'monthly_before':before_month,'monthly_after':after_month,
                'august_daily_unchanged':True,'all_daily_amounts_unchanged':True,
                'source_contract_unchanged':True,'ods_unchanged':True,'pure_settlement_unchanged':True,
                'idempotent':True,'source_lineage':lineage,'raw_fingerprints':raw,
                'published_daily_signature':before_money}
            Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        if args.apply:
            conn.commit()
            output['applied']=True
            Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print('分类目录、平台映射和两张看板ADS已原子提交；8月及其他月份金额保持不变',flush=True)
        else:
            conn.rollback()
            print('两次刷新和分类验收通过，预演已全部回滚',flush=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__=='__main__':
    main()
