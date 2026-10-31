"""Apply explicit operating policies only after unchanged-money regression."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone
import psycopg2
from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import prepare_schema,PLATFORMS,validate_projection
from etl.platform_finance.run_operating_treatment_migration import refresh_all
from etl.platform_finance.rebuild_operating_categories import money_signature,monthly,records
from etl.platform_finance.reconcile_operating_sources import fingerprints,RAW,ADS,validate_source_rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--output',required=True)
    args=p.parse_args()
    load_pg_env()
    conn=psycopg2.connect(application_name='operating_policy_migration',options='-c lock_timeout=10000 -c statement_timeout=120000')
    try:
        conn.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_global_etl'))")
            before=money_signature(c);months=monthly(c)
            raw=fingerprints(c,'ods',RAW)
            pure=fingerprints(c,'ads',('ads_settlement_net_company_shop_daily','ads_settlement_net_company_shop_monthly'))
            c.execute('SELECT mapping_id,operating_treatment,primary_category_code,primary_category_name FROM dim.dim_platform_fee_mapping ORDER BY mapping_id')
            business_before=c.fetchall()
            prepare_schema(c)
            refresh_all(c)
            assert before==money_signature(c),'经营规则迁移改变了既有每日金额/明细数量'
            first=fingerprints(c,'ads',ADS,exclude=('created_at','updated_at','mapping_updated_at'))
            print('第一次全平台刷新通过，开始第二次刷新与幂等验收',flush=True)
            refresh_all(c)
            assert before==money_signature(c),'第二次刷新改变了既有金额'
            assert first==fingerprints(c,'ads',ADS,exclude=('created_at','updated_at','mapping_updated_at')),'重复刷新结果不一致'
            assert months==monthly(c),'月度/店铺金额变化'
            assert raw==fingerprints(c,'ods',RAW),'原始ODS发生变化'
            assert pure==fingerprints(c,'ads',tuple(pure)),'纯结算结果变化'
            c.execute('SELECT mapping_id,operating_treatment,primary_category_code,primary_category_name FROM dim.dim_platform_fee_mapping ORDER BY mapping_id')
            assert business_before==c.fetchall(),'既有财务归属或分类被覆盖'
            projection={platform:validate_projection(c,platform) for platform in PLATFORMS}
            lineage=validate_source_rows(c)
            policy=records(c,'''SELECT mapping_id,platform_code,secondary_category_name,operating_treatment,
                treatment_origin,source_usage,source_usage_note,alias_of_mapping_id,source_role,metric_role
                FROM dim.dim_platform_fee_mapping ORDER BY mapping_id''')
            c.execute("SELECT count(*) FROM pg_attribute WHERE attrelid='dim.dim_platform_fee_mapping'::regclass AND attnum>0 AND NOT attisdropped AND col_description(attrelid,attnum) IS NULL")
            assert c.fetchone()[0]==0,'字段注释遗漏'
            result={'checked_at':datetime.now(timezone.utc).isoformat(),'applied':False,'unchanged_daily_money':True,
                'unchanged_monthly_money':True,'unchanged_business_configuration':True,'ods_unchanged':True,
                'pure_settlement_unchanged':True,'idempotent':True,'projection':projection,'source_lineage':lineage,
                'policy':policy,'monthly':months,'raw_fingerprints':raw,'pure_fingerprints':pure}
            if args.apply:conn.commit();result['applied']=True
            else:conn.rollback()
            Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print('来源用途、经营归属纠错入口及两张看板ADS已提交' if args.apply else '验收通过，预演全部回滚',flush=True)
    except Exception:
        conn.rollback();raise
    finally:conn.close()

if __name__=='__main__':main()
