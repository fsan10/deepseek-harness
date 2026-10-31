"""Apply configurable scene names after two unchanged-money source refreshes."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path
import psycopg2
from etl.common.settlement_sources import load_pg_env
from etl.platform_finance.operating_treatment import prepare_schema,PLATFORMS,validate_projection,refresh_projection,ROOT
from etl.platform_finance.scene_normalization import normalize_dwd
from etl.platform_finance.run_operating_treatment_migration import refresh_all
from etl.platform_finance.reconcile_operating_sources import fingerprints,RAW,ADS,validate_source_rows
from etl.platform_finance.rebuild_operating_categories import monthly,records

def daily(cursor):
    return records(cursor,'''SELECT stat_date,platform_code,company_code,shop_code,source_document_type,
        source_origin,primary_category_code,operating_treatment,sum(source_signed_amount) source_signed_amount,
        sum(income_amount) income,sum(expense_amount) expense,sum(excluded_amount) excluded,
        sum(source_detail_count) source_rows,sum(included_detail_count) included_rows
        FROM ads.ads_platform_operating_flow_company_shop_daily_scene
        GROUP BY 1,2,3,4,5,6,7,8 ORDER BY 1,2,3,4,5,6,7,8''')

def accepted_notes(cursor):
    """Replace obsolete auto-migration status, preserving specific finance notes."""
    cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET classification_note=
        CASE WHEN operating_treatment IS NULL THEN '经营归属待财务确认；当前一级分类：'||primary_category_name||'。'
             WHEN operating_treatment='income' THEN '已确认计入经营收入，退款负金额冲减收入；一级分类：'||primary_category_name||'。'
             WHEN operating_treatment='expense' THEN '已确认计入经营支出，费用返还冲减支出；一级分类：'||primary_category_name||'。'
             WHEN source_business_type IN ('资金冻结','资金解冻','扣减前临时解冻') AND secondary_category_name LIKE '%%退款%%' THEN
                '退款过程的冻结或解冻资金变动，已确认不计入经营收支；一级分类：'||primary_category_name||'。'
             ELSE '已确认不计入经营收支，保留原始明细；一级分类：'||primary_category_name||'。' END
        WHERE classification_note LIKE '分类未映射%%'
           OR classification_note LIKE '经营性质待确认%%'
           OR classification_note LIKE '分类按已确认来源业务场景生成%%'
           OR classification_note LIKE '由既有收入公式迁移%%' RETURNING mapping_id''')
    changed=[r[0] for r in cursor.fetchall()]
    cursor.execute("UPDATE dim.dim_platform_fee_mapping SET source_usage_note='独立业务金额；经营归属和分类可由财务维护，原始描述、文件覆盖及流水防重继续保留。' WHERE source_usage='independent' AND (source_usage_note LIKE '%分类未映射%' OR source_usage_note LIKE '%经营性质待确认%')")
    return changed

def refresh_names(cursor):
    """Existing numeric facts are verified, not reparsed for a naming change."""
    validate_source_rows(cursor)
    for platform,path in (
        ('ks','ks/platform_expense/317_refresh_dws_ks_platform_expense_shop_daily_category_postgres.sql'),
        ('jd','jd/platform_expense/322_refresh_dws_jd_platform_expense_shop_daily_category_postgres.sql'),
        ('tmall','tmall/platform_expense/335_refresh_dws_tmall_platform_expense_shop_daily_category_postgres.sql')):
        print(f'{platform}：ODS原生来源身份已核对，刷新场景名称和费用公式汇总',flush=True)
        normalize_dwd(cursor,platform)
        cursor.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))
    refresh_projection(cursor)
    for path in ('ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql',
                 'ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql'):
        cursor.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output',required=True)
    parser.add_argument('--rebuild-sources',action='store_true',help='同时从ODS重新解析全部平台来源；日常完整ETL仍使用原有全链路')
    args=parser.parse_args()
    load_pg_env()
    conn=psycopg2.connect(application_name='scene_normalization_migration',options='-c lock_timeout=60000 -c statement_timeout=120000')
    try:
        # Acquire outside REPEATABLE READ so a wait behind a healthy Worker
        # cannot freeze the baseline at a snapshot preceding that Worker's commit.
        conn.autocommit=True
        with conn.cursor() as gate:
            gate.execute("SET lock_timeout='0'")
            gate.execute("SET statement_timeout='0'")
            gate.execute("SELECT pg_advisory_lock(hashtext('mock_coffice_global_etl'))")
        conn.autocommit=False
        conn.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as c:
            c.execute("SET LOCAL lock_timeout='10000'")
            c.execute("SET LOCAL statement_timeout='120000'")
            before=daily(c);months=monthly(c)
            raw=fingerprints(c,'ods',RAW)
            dwd_tables=tuple(f'dwd_{p}_{m}_source_detail' for p in PLATFORMS for m in ('main_business_income','platform_expense'))
            dwd_numeric=fingerprints(c,'dwd',dwd_tables,exclude=('secondary_category_name','updated_at'))
            pure=fingerprints(c,'ads',('ads_settlement_net_company_shop_daily','ads_settlement_net_company_shop_monthly'))
            maps=records(c,'''SELECT mapping_id,primary_category_code,operating_treatment,canonical_operating_treatment,
                include_in_platform_expense,source_role,source_usage FROM dim.dim_platform_fee_mapping ORDER BY mapping_id''')
            counts_before=records(c,'''SELECT platform_code,count(*) rows,count(DISTINCT secondary_category_name) names
                FROM ads.ads_platform_operating_flow_company_shop_daily_scene GROUP BY 1 ORDER BY 1''')
            prepare_schema(c)
            notes=accepted_notes(c)
            refresh=refresh_all if args.rebuild_sources else refresh_names
            refresh(c)
            assert before==daily(c),'名称清洗改变每日、分类、经营归属、金额或来源数量'
            first=fingerprints(c,'ads',ADS,exclude=('created_at','updated_at','mapping_updated_at'))
            print('第一次名称清洗刷新通过，进行第二次幂等验收',flush=True)
            refresh(c)
            assert before==daily(c),'第二次刷新改变经营金额或明细数量'
            assert months==monthly(c),'月度店铺金额变化'
            assert first==fingerprints(c,'ads',ADS,exclude=('created_at','updated_at','mapping_updated_at')),'名称清洗不幂等'
            assert raw==fingerprints(c,'ods',RAW),'ODS被改变'
            assert pure==fingerprints(c,'ads',tuple(pure)),'纯结算被改变'
            if not args.rebuild_sources:
                assert dwd_numeric==fingerprints(c,'dwd',dwd_tables,exclude=('secondary_category_name','updated_at')),'DWD金额、日期、状态或原生来源字段被改变'
            assert maps==records(c,'''SELECT mapping_id,primary_category_code,operating_treatment,canonical_operating_treatment,
                include_in_platform_expense,source_role,source_usage FROM dim.dim_platform_fee_mapping ORDER BY mapping_id'''),'既有分类、归属或来源职责改变'
            projection={p:validate_projection(c,p) for p in PLATFORMS}
            lineage=validate_source_rows(c)
            counts_after=records(c,'''SELECT platform_code,count(*) rows,count(DISTINCT secondary_category_name) names
                FROM ads.ads_platform_operating_flow_company_shop_daily_scene GROUP BY 1 ORDER BY 1''')
            examples=records(c,'''SELECT "业务类型" business,"描述" description,
                dim.normalize_platform_scene('ks','fund',"业务类型"||' + '||"描述","业务类型") scene
                FROM common.v_current_ks_fund_raw WHERE "描述"~'(订单号|订单编号|退款单号)'
                ORDER BY id LIMIT 5''')
            c.execute("SELECT count(*) FROM pg_attribute WHERE attrelid='dim.dim_platform_scene_normalization_rule'::regclass AND attnum>0 AND NOT attisdropped AND col_description(attrelid,attnum) IS NULL")
            assert c.fetchone()[0]==0,'清洗规则字段注释遗漏'
            output={'checked_at':datetime.now(timezone.utc).isoformat(),'applied':False,'daily_money_and_source_counts_unchanged':True,
                'monthly_unchanged':True,'business_configuration_unchanged':True,'ods_unchanged':True,'pure_settlement_unchanged':True,
                'idempotent':True,'notes_updated':notes,'before':counts_before,'after':counts_after,
                'projection':projection,'source_lineage':lineage,'examples':examples,'monthly':months,'raw_fingerprints':raw,'pure_fingerprints':pure}
            output['refresh_mode']='full_source_rebuild' if args.rebuild_sources else 'verified_dwd_names_and_seven_platform_projection'
            output['dwd_non_naming_fields_unchanged']=not args.rebuild_sources
            if args.apply:conn.commit();output['applied']=True
            else:conn.rollback()
            Path(args.output).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            print('可配置场景清洗规则、备注及历史日汇总已提交' if args.apply else '全部验收通过，预演已回滚',flush=True)
    except Exception:
        conn.rollback();raise
    finally:conn.close()

if __name__=='__main__':main()
