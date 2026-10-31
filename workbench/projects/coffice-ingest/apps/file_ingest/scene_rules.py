"""Previewable PostgreSQL scene-name rules; financial/source policy is separate."""
import hashlib
import json
import uuid
from datetime import datetime
import psycopg2
from etl.platform_finance.operating_policy import as_rows

FIELDS=('rule_name','platform_code','source_document_type','source_business_type','pattern','replacement','priority','is_active','note')
POLICY=('operating_treatment','canonical_operating_treatment','primary_category_code','is_active','include_in_platform_expense','source_role','source_usage')

def list_rules(cursor):
    cursor.execute('''SELECT r.*,j.status configuration_etl_status FROM dim.dim_platform_scene_normalization_rule r
        LEFT JOIN ops.etl_run j ON j.etl_run_id=r.last_etl_run_id
        ORDER BY r.platform_code,r.source_document_type,r.priority,r.rule_id''')
    return as_rows(cursor)

def proposed_rule(payload,old=None):
    from .service import FEE_PLATFORM_ETLS
    row={**(old or {}),**{k:payload[k] for k in FIELDS if k in payload}}
    row['rule_name']=str(row.get('rule_name','')).strip()
    row['pattern']=str(row.get('pattern',''))
    row['replacement']=str(row.get('replacement',''))
    row['source_business_type']=str(row.get('source_business_type') or '').strip() or None
    row['priority']=int(row.get('priority',100))
    row['is_active']=bool(row.get('is_active',True))
    row['note']=str(row.get('note','')).strip()
    if not row['rule_name'] or len(row['rule_name'])>128:raise ValueError('请填写不超过128字的规则名称')
    if row.get('platform_code') not in FEE_PLATFORM_ETLS or row.get('source_document_type') not in ('fund','settlement'):raise ValueError('请选择有效平台和来源')
    if not row['pattern'] or len(row['pattern'])>500:raise ValueError('请填写不超过500字的PostgreSQL正则')
    if len(row['replacement'])>500 or len(row['note'])>1000 or not 0<=row['priority']<=10000:raise ValueError('替换内容、说明或执行顺序超出范围')
    return row

def normalized(cursor,inputs,rules):
    names=[i['scene'] for i in inputs]
    for rule in sorted(rules,key=lambda r:(r['priority'],r.get('rule_id') or 9223372036854775807)):
        if not rule['is_active']:continue
        indexes=[n for n,i in enumerate(inputs) if i['platform']==rule['platform_code'] and i['document']==rule['source_document_type']
            and (not rule.get('source_business_type') or (i.get('business') or i['scene'].split(' + ')[0])==rule['source_business_type'])]
        # Validate the pattern even when current source coverage is empty.
        cursor.execute("SELECT regexp_replace('',%s,%s,'g')",(rule['pattern'],rule['replacement']))
        if not indexes:continue
        cursor.execute("SELECT n, btrim(regexp_replace(s,%s,%s,'g')) name FROM unnest(%s::int[],%s::text[]) x(n,s)",
            (rule['pattern'],rule['replacement'],indexes,[names[n] for n in indexes]))
        for r in as_rows(cursor):names[r['n']]=r['name']
    if any(not n or len(n)>768 for n in names):raise ValueError('清洗结果为空或超长，请缩小正则范围并重新预览')
    return names

def preview(cursor,payload):
    from .service import FEE_ODS_CANDIDATE_QUERIES
    rules=list_rules(cursor)
    old=next((r for r in rules if r['rule_id']==payload.get('rule_id')),None)
    if payload.get('rule_id') and not old:raise ValueError('规则不存在，请刷新')
    proposed=proposed_rule(payload,old)
    if len(str(payload.get('sample_text') or ''))>20000:raise ValueError('补充测试样本请控制在20000字以内')
    if old and payload.get('updated_at') and datetime.fromisoformat(str(payload['updated_at']).replace('Z','+00:00'))!=old['updated_at']:
        raise ValueError('规则已被修改，请刷新后重新预览')
    updated=[r for r in rules if not old or r['rule_id']!=old['rule_id']]+[proposed]
    scope={proposed['platform_code']}
    if old:scope.add(old['platform_code'])
    inputs=[]
    for platform in sorted(scope):
        cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE platform_code=%s AND alias_of_mapping_id IS NULL ORDER BY mapping_id',(platform,))
        for m in as_rows(cursor):
            inputs.append({'platform':platform,'document':m['source_document_type'],'business':m['source_business_type'],
                'scene':m['secondary_category_name'],'kind':'mapping','mapping_id':m['mapping_id'],
                'policy':tuple(m[k] for k in POLICY)})
        cursor.execute(f'''SELECT DISTINCT * FROM ({FEE_ODS_CANDIDATE_QUERIES[platform]}) c(document,business,description,scene)''')
        for r in as_rows(cursor):
            inputs.append({'platform':platform,'document':r['document'],'business':r['business'],'scene':r['scene'],'kind':'source'})
        cursor.execute('''SELECT DISTINCT source_document_type,secondary_category_name FROM ads.ads_platform_operating_flow_company_shop_daily_scene WHERE platform_code=%s''',(platform,))
        for r in as_rows(cursor):inputs.append({'platform':platform,'document':r['source_document_type'],'business':None,'scene':r['secondary_category_name'],'kind':'published'})
    for scene in str(payload.get('sample_text') or '').splitlines():
        if scene.strip():inputs.append({'platform':proposed['platform_code'],'document':proposed['source_document_type'],
            'business':proposed['source_business_type'],'scene':scene.strip(),'kind':'sample'})
    inputs.sort(key=lambda i:(i['platform'],i['document'],i['kind'],i['scene'] or '',i.get('mapping_id') or 0,i.get('business') or ''))
    cursor.execute('SAVEPOINT scene_regex_preview')
    cursor.execute("SELECT current_setting('statement_timeout') timeout")
    timeout=as_rows(cursor)[0]['timeout']
    try:
        cursor.execute("SELECT set_config('statement_timeout','3000',true)")
        before=normalized(cursor,inputs,rules)
        after=normalized(cursor,inputs,updated)
        again=normalized(cursor,[{**i,'scene':name} for i,name in zip(inputs,after)],updated)
        if after!=again:raise ValueError('规则重复执行会继续改变名称，请改为可重复清洗的正则')
    except psycopg2.Error as exc:
        cursor.execute('ROLLBACK TO SAVEPOINT scene_regex_preview')
        raise ValueError('正则无效或执行超时，请检查PostgreSQL正则语法并缩小匹配范围') from exc
    finally:
        cursor.execute('ROLLBACK TO SAVEPOINT scene_regex_preview')
        cursor.execute('RELEASE SAVEPOINT scene_regex_preview')
        cursor.execute("SELECT set_config('statement_timeout',%s,true)",(timeout,))
    groups={}
    conflicts=[]
    for item,name in zip(inputs,after):
        if item['kind']!='mapping':continue
        key=(item['platform'],item['document'],name)
        if key in groups and groups[key]['policy']!=item['policy']:
            conflicts.append({'scene':name,'mapping_ids':[groups[key]['mapping_id'],item['mapping_id']]})
        else:groups[key]=item
    examples=[{'before':i['scene'],'after':name,'current':prev,'kind':i['kind']} for i,prev,name in zip(inputs,before,after) if name!=i['scene'] or name!=prev or i['kind']=='sample']
    token=hashlib.sha256(json.dumps({'rules':[{k:r.get(k) for k in (*FIELDS,'rule_id')} for r in updated],
        'inputs':inputs},sort_keys=True,default=str).encode()).hexdigest()
    return {'preview_token':token,'changed_names':sum(a!=b for a,b in zip(before,after)),
        'source_names_before':len({(i['platform'],i['document'],i['scene']) for i in inputs if i['kind']=='source'}),
        'source_names_after':len({(i['platform'],i['document'],n) for i,n in zip(inputs,after) if i['kind']=='source'}),
        'examples':examples[:30],'conflicts':conflicts,'can_save':not conflicts,
        'scope_note':'只调整场景命名；保留原始描述、来源身份、金额符号、经营归属及分类。不同配置的场景不允许合并。保存后重算受影响平台的历史数据。'}

def save(service,payload,operator,ip_address):
    from .service import FEE_PLATFORM_ETLS
    with service.transaction() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext('mock_coffice_global_etl')) acquired")
        if not as_rows(cursor)[0]['acquired']:raise ValueError('当前正在重算，请稍后重新预览')
        proof=preview(cursor,payload)
        if not payload.get('preview_token') or proof['preview_token']!=payload['preview_token']:raise ValueError('规则或来源已变化，请重新预览再保存')
        if proof['conflicts']:raise ValueError('清洗后合并了分类、经营归属或来源职责不同的场景，请缩小正则范围')
        old=None
        if payload.get('rule_id'):
            cursor.execute('SELECT * FROM dim.dim_platform_scene_normalization_rule WHERE rule_id=%s FOR UPDATE',(payload['rule_id'],))
            old=as_rows(cursor)[0]
        row=proposed_rule(payload,old)
        if old:
            cursor.execute('''UPDATE dim.dim_platform_scene_normalization_rule SET
                rule_name=%s,platform_code=%s,source_document_type=%s,source_business_type=%s,pattern=%s,replacement=%s,
                priority=%s,is_active=%s,note=%s,updated_by=%s,updated_at=now() WHERE rule_id=%s RETURNING *''',
                (*[row[k] for k in FIELDS],operator,old['rule_id']))
        else:
            cursor.execute('''INSERT INTO dim.dim_platform_scene_normalization_rule
                (rule_name,platform_code,source_document_type,source_business_type,pattern,replacement,priority,is_active,note,
                 created_by,updated_by,rule_code) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
                (*[row[k] for k in FIELDS],operator,operator,'manual_'+uuid.uuid4().hex))
        saved=as_rows(cursor)[0]
        scope=list({row['platform_code']}|({old['platform_code']} if old else set()))
        cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET normalized_scene_name=
            dim.normalize_platform_scene(platform_code,source_document_type,secondary_category_name,source_business_type)
            WHERE platform_code=ANY(%s)''',(scope,))
        etls=set(FEE_PLATFORM_ETLS[row['platform_code']])
        if old:etls.update(FEE_PLATFORM_ETLS[old['platform_code']])
        job=service.create_etl_run(etls,trigger_type='fee_mapping',scope='affected',operator=operator,cursor=cursor)
        cursor.execute('UPDATE dim.dim_platform_scene_normalization_rule SET last_etl_run_id=%s::uuid WHERE rule_id=%s',
            (str(job['etl_run_id']),saved['rule_id']))
        cursor.execute('UPDATE dim.dim_platform_fee_mapping SET last_etl_run_id=%s::uuid WHERE platform_code=ANY(%s)',
            (str(job['etl_run_id']),scope))
        service._write_log(cursor,'scene_rule_save','scene_rule',str(saved['rule_id']),operator,ip_address,
            '维护收支场景清洗规则',json.loads(json.dumps({'before':old,'after':saved,'changed_names':proof['changed_names']},default=str)))
    return {'rule':saved,'etl_run':job}
