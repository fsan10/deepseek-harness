"""Classification-independent operating income, expense and excluded detail.

The existing platform DWD and formula DWS remain the source-formula stages of
the same finance pipeline. This final DWS stage applies editable treatment once,
before the shared ADS; source selection and refund guards remain upstream.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = ('douyin', 'jd', 'ks', 'pdd', 'tmall', 'wechat_channels', 'xhs')
MIGRATION = 'dim/439_dim_platform_operating_treatment_postgres.sql'
CREATE_FILES = (
    'douyin/operating_treatment/440_dws_douyin_operating_flow_shop_daily_scene_postgres.sql',
    'jd/operating_treatment/441_dws_jd_operating_flow_shop_daily_scene_postgres.sql',
    'ks/operating_treatment/442_dws_ks_operating_flow_shop_daily_scene_postgres.sql',
    'pdd/operating_treatment/443_dws_pdd_operating_flow_shop_daily_scene_postgres.sql',
    'tmall/operating_treatment/444_dws_tmall_operating_flow_shop_daily_scene_postgres.sql',
    'wechat_channels/operating_treatment/445_dws_wechat_channels_operating_flow_shop_daily_scene_postgres.sql',
    'xhs/operating_treatment/446_dws_xhs_operating_flow_shop_daily_scene_postgres.sql',
)
REFRESH_FILES = (
    'douyin/operating_treatment/447_refresh_dws_douyin_operating_flow_shop_daily_scene_postgres.sql',
    'jd/operating_treatment/448_refresh_dws_jd_operating_flow_shop_daily_scene_postgres.sql',
    'ks/operating_treatment/449_refresh_dws_ks_operating_flow_shop_daily_scene_postgres.sql',
    'pdd/operating_treatment/450_refresh_dws_pdd_operating_flow_shop_daily_scene_postgres.sql',
    'tmall/operating_treatment/451_refresh_dws_tmall_operating_flow_shop_daily_scene_postgres.sql',
    'wechat_channels/operating_treatment/452_refresh_dws_wechat_channels_operating_flow_shop_daily_scene_postgres.sql',
    'xhs/operating_treatment/453_refresh_dws_xhs_operating_flow_shop_daily_scene_postgres.sql',
)
ADS_FILES = ('ads/operating_flow/454_ads_platform_operating_flow_company_shop_daily_scene_postgres.sql',
             'ads/operating_flow/455_refresh_ads_platform_operating_flow_company_shop_daily_scene_postgres.sql')


def prepare_schema(cursor):
    cursor.execute("SELECT to_regclass('dim.dim_platform_fee_mapping')")
    if cursor.fetchone()[0] is None:
        return
    from etl.platform_finance.scene_normalization import prepare_schema as prepare_scene_schema
    prepare_scene_schema(cursor)
    cursor.execute((ROOT/'sql'/MIGRATION).read_text(encoding='utf-8'))
    from etl.platform_finance.category_catalog import ensure_catalog
    ensure_catalog(cursor)
    from etl.platform_finance.operating_policy import initialize_policy
    initialize_policy(cursor)
    for path in ('ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql', 'ads/main_business_income/325_ads_platform_main_business_income_company_shop_daily_category_postgres.sql', *CREATE_FILES, ADS_FILES[0]):
        cursor.execute((ROOT/'sql'/path).read_text(encoding='utf-8'))


def seed_income_components(cursor, platform):
    """Expose existing formula components without changing their signed values."""
    cursor.execute(sql.SQL('''
        SELECT DISTINCT platform_code,platform_name,source_document_type,
            secondary_category_code,secondary_category_name,
            primary_category_code,primary_category_name
        FROM dws.{}''').format(sql.Identifier(f'dws_{platform}_main_business_income_shop_daily_category')))
    rows=cursor.fetchall()
    for p,name,doc,code,scene,primary,primary_name in rows:
        # Stable formula components keep a finance-maintained classification.
        # Looking up the formula's old display name first recreated categories
        # which had already been merged by the catalog migration.
        cursor.execute('''SELECT mapping_id FROM dim.dim_platform_fee_mapping
            WHERE platform_code=%s AND source_document_type=%s
              AND source_component_code=%s''',(p,doc,code))
        if cursor.fetchone():
            continue
        # Existing exact income scenes (PDD/Wechat/Tmall) already have a rule.
        cursor.execute('''SELECT mapping_id FROM dim.dim_platform_fee_mapping
            WHERE platform_code=%s AND source_document_type=%s
              AND secondary_category_name=%s
              AND source_component_code IS NULL''',(p,doc,scene))
        if cursor.fetchone():
            continue
        from etl.platform_finance.category_catalog import category_for_scene, ensure_category
        classified_code,classified_name=ensure_category(cursor,category_for_scene({
            'operating_treatment':'income','source_component_code':code,
            'secondary_category_name':scene,'primary_category_code':primary}))
        component_code='component_'+hashlib.sha1((doc+'|'+code).encode()).hexdigest()[:20]
        cursor.execute('''INSERT INTO dim.dim_platform_fee_mapping(
            platform_code,platform_name,source_document_type,secondary_category_code,
            secondary_category_name,source_component_code,primary_category_code,
            primary_category_name,include_in_platform_expense,operating_treatment,canonical_operating_treatment,
            source_role,metric_role,is_active,classification_note,created_by,updated_by)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,FALSE,'income','income','PRIMARY','MAIN_REVENUE',TRUE,
                '由既有收入公式迁移；负金额继续冲减收入。','operating_migration','operating_migration')
            ON CONFLICT(platform_code,source_document_type,secondary_category_code) DO NOTHING''',
            (p,name,doc,component_code,scene+'（'+classified_name+'）',code,classified_code,classified_name))


def prepare_fee_scenes(cursor, platform):
    """Discover missing categories; never infer operating nature just from sign."""
    relation=f'dwd_{platform}_platform_expense_source_detail'
    cursor.execute('''SELECT column_name FROM information_schema.columns
        WHERE table_schema='dwd' AND table_name=%s''',(relation,))
    columns={r[0] for r in cursor.fetchall()}
    if not columns:
        return
    doc='d.source_document_type' if 'source_document_type' in columns else "'fund'" if platform=='tmall' else "'settlement'"
    biz='d.source_business_type' if 'source_business_type' in columns else 'd.source_event_type' if 'source_event_type' in columns else 'NULL::text'
    desc='d.source_description' if 'source_description' in columns else 'NULL::text'
    cursor.execute(f'''SELECT DISTINCT d.platform_name,{doc},{biz},{desc},d.secondary_category_name
        FROM dwd.{relation} d
        LEFT JOIN LATERAL dim.match_platform_operating_scene(%s,{doc},d.secondary_category_name,{biz},{desc}) m ON TRUE
        WHERE m.mapping_id IS NULL AND d.directional_expense_amount<>0''',(platform,))
    for name,document,business,description,scene in cursor.fetchall():
        from etl.platform_finance.operating_policy import default_treatment
        treatment=default_treatment(platform,document,scene,business,description)
        role=('EXPENSE_OFFSET' if business=='佣金/技术服务费返还' or scene=='带货佣金未开票抵扣'
              else 'SUPPLEMENT' if document=='fund' and treatment=='expense'
              else 'PRIMARY' if treatment in ('income','expense') else 'RECONCILIATION')
        # Unknown business nature remains visible for explicit finance treatment.
        secondary=f'{platform}_{document}_'+hashlib.sha1(scene.encode()).hexdigest()[:16]
        from etl.platform_finance.category_catalog import category_for_scene, ensure_category
        category_code,category_name=ensure_category(cursor,category_for_scene({
            'operating_treatment':treatment,'source_business_type':business,
            'secondary_category_name':scene,'primary_category_code':'unmapped'}))
        cursor.execute('''INSERT INTO dim.dim_platform_fee_mapping(
            platform_code,platform_name,source_document_type,secondary_category_code,
            secondary_category_name,source_business_type,primary_category_code,primary_category_name,
            include_in_platform_expense,operating_treatment,canonical_operating_treatment,source_role,metric_role,
            classification_note,is_active,created_by,updated_by,source_treatment_initialized)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,
                'operating_discovery','operating_discovery',TRUE)
            ON CONFLICT(platform_code,source_document_type,secondary_category_code) DO NOTHING''',
            (platform,name,document,secondary,scene,business,category_code,category_name,treatment=='expense',treatment,treatment,
             role or 'RECONCILIATION','EXPENSE_OFFSET' if role=='EXPENSE_OFFSET' else 'PLATFORM_EXPENSE' if treatment=='expense' else 'RECONCILIATION',
             '分类按已确认来源业务场景生成；经营归属沿用来源规则。' if treatment else '经营性质待确认；未按金额符号自动归属。'))
    if platform=='xhs':
        # Unknown income transaction types retain their signed component and
        # await finance confirmation rather than failing the entire refresh.
        from etl.platform_finance.category_catalog import ensure_category
        category_code,category_name=ensure_category(cursor,'pending_nature')
        cursor.execute('''INSERT INTO dim.dim_platform_fee_mapping(
            platform_code,platform_name,source_document_type,secondary_category_code,secondary_category_name,
            source_component_code,source_business_type,primary_category_code,primary_category_name,
            include_in_platform_expense,operating_treatment,canonical_operating_treatment,source_role,metric_role,
            classification_note,is_active,created_by,updated_by,source_treatment_initialized)
            SELECT DISTINCT 'xhs','小红书','settlement','xhs_pending_'||left(md5(source_business_type),16),
                '订单结算交易 + '||source_business_type,'unconfirmed_income_'||left(md5(source_business_type),16),
                source_business_type,%s,%s,FALSE,NULL,NULL,'RECONCILIATION','RECONCILIATION',
                '新增订单交易类型，金额沿用来源公式，经营性质等待财务确认。',TRUE,'operating_discovery','operating_discovery',TRUE
            FROM dwd.dwd_xhs_main_business_income_source_detail
            WHERE source_business_type NOT IN ('结算入账','退款','申诉调账')
            ON CONFLICT(platform_code,source_document_type,secondary_category_code) DO NOTHING''',(category_code,category_name))


def refresh_projection(cursor, platforms=PLATFORMS):
    from etl.platform_finance.operating_policy import initialize_policy
    runtime = getattr(cursor.connection, 'refresh_scope', None)
    if runtime is not None and not runtime.full:
        platforms = tuple(p for p in platforms if p in runtime.platforms)
    for platform in platforms:
        cursor.execute("SELECT to_regclass(%s),to_regclass(%s),to_regclass(%s)",
            (f'dws.dws_{platform}_main_business_income_shop_daily_category',
             f'dws.dws_{platform}_platform_expense_shop_daily_category',
             f'dwd.dwd_{platform}_platform_expense_source_detail'))
        if not all(cursor.fetchone()):
            continue
        seed_income_components(cursor,platform)
        initialize_policy(cursor)
        cursor.execute((ROOT/'sql'/REFRESH_FILES[PLATFORMS.index(platform)]).read_text(encoding='utf-8'))
        # Formula/component identities stay unchanged; only their display name
        # is normalized here. Raw expense scenes were cleaned before grouping.
        cursor.execute(sql.SQL('''UPDATE dws.{} SET secondary_category_name=
            dim.normalize_platform_scene(platform_code,source_document_type,secondary_category_name)''').format(
            sql.Identifier(f'dws_{platform}_operating_flow_shop_daily_scene')))
    cursor.execute((ROOT/'sql'/ADS_FILES[1]).read_text(encoding='utf-8'))


def execute_finance_files(cursor, files):
    """Integrate discovery and the final DWS stage in the caller transaction."""
    from etl.common.finance_sources import prepare_finance_sources
    prepare_schema(cursor)
    prepared = set()
    for relative in files:
        if 'refresh_dwd_' in relative:
            platform = relative.split('/')[0]
            if platform in PLATFORMS and platform not in prepared:
                prepare_finance_sources(cursor, platform,
                    include_fund=not (platform=='douyin' and 'main_business_income/' in relative))
                prepared.add(platform)
        if 'refresh_dws_' in relative:
            platform=relative.split('/')[0]
            if platform in PLATFORMS:
                prepare_fee_scenes(cursor,platform)
        if relative in (
            'ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql',
            'ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql'):
            refresh_projection(cursor)
            for shared in ('ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql',
                           'ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql'):
                cursor.execute((ROOT/'sql'/shared).read_text(encoding='utf-8'))
            continue
        cursor.execute((ROOT/'sql'/relative).read_text(encoding='utf-8'))
        if 'refresh_dwd_' in relative and '_platform_expense_source_detail_' in relative:
            platform=relative.split('/')[0]
            if platform in PLATFORMS:
                from etl.platform_finance.scene_normalization import normalize_dwd
                normalize_dwd(cursor,platform)


def validate_projection(cursor, platform):
    """Compare final DWS/ADS; classification and routing may change independently."""
    differences=[]
    for treatment, relation, amount in (
        ('income','ads_platform_main_business_income_company_shop_daily_category','income_amount'),
        ('expense','ads_platform_expense_company_shop_daily_category','expense_amount')):
        cursor.execute(sql.SQL('''WITH expected AS (
            SELECT stat_date,platform_code,shop_code,source_document_type,
                primary_category_code,secondary_category_code,SUM({amount}) amount
            FROM dws.{source} WHERE operating_treatment=%s
            GROUP BY 1,2,3,4,5,6
        ),actual AS (
            SELECT stat_date,platform_code,shop_code,source_document_type,
                primary_category_code,secondary_category_code,SUM({amount}) amount
            FROM ads.{target} WHERE platform_code=%s GROUP BY 1,2,3,4,5,6
        ) SELECT (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) x)
            +(SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) x)''').format(
            amount=sql.Identifier(amount),source=sql.Identifier(f'dws_{platform}_operating_flow_shop_daily_scene'),
            target=sql.Identifier(relation)),(treatment,platform))
        differences.append(cursor.fetchone()[0])
    if any(differences):
        raise RuntimeError(f'{platform}经营归属DWS/ADS双向差异：{differences}')
    return tuple(differences)
