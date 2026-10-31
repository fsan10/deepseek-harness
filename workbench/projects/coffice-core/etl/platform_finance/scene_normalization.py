"""One database-backed naming contract for candidates, DWD and configuration."""
from pathlib import Path
from psycopg2 import sql

ROOT=Path(__file__).resolve().parents[2]
MIGRATION='dim/464_platform_scene_normalization_postgres.sql'

def prepare_schema(cursor):
    cursor.execute((ROOT/'sql'/MIGRATION).read_text(encoding='utf-8'))

def normalize_items(cursor,items):
    """Keep original names for evidence; use PostgreSQL semantics in every UI."""
    if not items:return items
    cursor.execute('''SELECT n,dim.normalize_platform_scene(p,d,s,b) name FROM
        unnest(%s::text[],%s::text[],%s::text[],%s::text[]) WITH ORDINALITY x(p,d,s,b,n)''',
        ([i['platform_code'] for i in items],[i['source_document_type'] for i in items],
         [i['secondary_category_name'] for i in items],[i.get('source_business_type') for i in items]))
    names={int(r['n'] if isinstance(r,dict) else r[0]):r['name'] if isinstance(r,dict) else r[1] for r in cursor.fetchall()}
    for n,item in enumerate(items,1):
        item['original_secondary_category_name']=item['secondary_category_name']
        item['secondary_category_name']=names.get(n,item['secondary_category_name'])
    return items

def normalize_dwd(cursor,platform):
    """Called once immediately after a fresh expense DWD; raw fields untouched."""
    cursor.execute('SELECT 1 FROM dim.dim_platform_scene_normalization_rule WHERE platform_code=%s AND is_active LIMIT 1',(platform,))
    if not cursor.fetchone():return
    table=f'dwd_{platform}_platform_expense_source_detail'
    cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='dwd' AND table_name=%s",(table,))
    cols={r[0] for r in cursor.fetchall()}
    if 'secondary_category_name' not in cols:return
    doc=sql.SQL('source_document_type') if 'source_document_type' in cols else sql.Literal('fund' if platform=='tmall' else 'settlement')
    biz=sql.SQL('source_business_type') if 'source_business_type' in cols else sql.SQL('source_event_type') if 'source_event_type' in cols else sql.SQL('NULL::text')
    cursor.execute(sql.SQL('''UPDATE dwd.{} SET secondary_category_name=dim.normalize_platform_scene(%s,{},secondary_category_name,{})''').format(sql.Identifier(table),doc,biz),(platform,))

def mapping_group(cursor,mapping_id):
    """Same normalized name and source semantics share one configuration entry."""
    cursor.execute('''SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s''',(mapping_id,))
    row=cursor.fetchone()
    if not row:return []
    if not isinstance(row,dict):row=dict(zip([c[0] for c in cursor.description],row))
    cursor.execute('''SELECT * FROM dim.dim_platform_fee_mapping m
        WHERE platform_code=%s AND source_document_type=%s AND alias_of_mapping_id IS NULL
          AND dim.normalize_platform_scene(platform_code,source_document_type,secondary_category_name,source_business_type)
             =dim.normalize_platform_scene(%s,%s,%s,%s)
        ORDER BY mapping_id''',(row['platform_code'],row['source_document_type'],
        row['platform_code'],row['source_document_type'],row['secondary_category_name'],row['source_business_type']))
    rows=[dict(r) if isinstance(r,dict) else dict(zip([c[0] for c in cursor.description],r)) for r in cursor.fetchall()]
    fields=('operating_treatment','canonical_operating_treatment','primary_category_code','is_active','include_in_platform_expense','source_role','source_usage')
    return [r for r in rows if all(r.get(k)==row.get(k) for k in fields)]
