"""Read-only impact/source evidence shared by preview and configuration saves."""
from decimal import Decimal
import hashlib
import json
from psycopg2 import sql
from etl.platform_finance.operating_policy import as_rows,ACCOUNTED,DUPLICATE

def effective_rule(cursor, item, *, lock=False):
    ident=item.get('mapping_id')
    if not ident: return None
    cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s'+(' FOR UPDATE' if lock else ''),(ident,))
    rows=as_rows(cursor)
    if not rows: raise ValueError('收支规则不存在，请刷新页面')
    row=rows[0]
    if row.get('alias_of_mapping_id'):
        cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE mapping_id=%s'+(' FOR UPDATE' if lock else ''),(row['alias_of_mapping_id'],))
        row=as_rows(cursor)[0]
    if row['platform_code']!=item['platform_code'] or row['source_document_type']!=item['source_document_type']:
        raise ValueError('收支规则平台或来源不一致')
    return row

def source_evidence(cursor, row):
    """Order relation is only evidence for a documented source contract."""
    result={'source_usage':row.get('source_usage','independent'),'reason':row.get('source_usage_note',''),
            'source_rows':0,'matched_rows':0,'missing_identity_rows':0,'samples':[], 'correction_available':False}
    if result['source_usage']=='independent':
        result['source_rows']=sum(r['source_rows'] for r in impact_rows(cursor,[row['mapping_id']]))
        result['identity_note']='独立金额的经营归属可以直接修改；来源文件覆盖、流水身份及已确认的退款防重继续执行。'
        return result
    p=row['platform_code']
    tables=[f'dwd_{p}_platform_expense_source_detail',f'dwd_{p}_main_business_income_source_detail']
    columns=[]
    for table in tables:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='dwd' AND table_name=%s",(table,))
        columns.append({r[0] if not isinstance(r,dict) else r['column_name'] for r in cursor.fetchall()})
    left,right=columns
    order=next((k for k in ('order_no','merchant_order_no') if k in left and k in right),None)
    if not order or 'shop_identity_key' not in left & right:
        result['identity_note']='该来源暂不能提供可核对的共同订单身份；请先核实批次店铺或来源规则。'
        return result
    doc=sql.SQL('d.source_document_type') if 'source_document_type' in left else sql.Literal('settlement')
    business=sql.SQL('d.source_business_type') if 'source_business_type' in left else sql.SQL('d.source_event_type') if 'source_event_type' in left else sql.SQL('NULL::text')
    desc=sql.SQL('d.source_description') if 'source_description' in left else sql.SQL('NULL::text')
    counterpart=sql.SQL("AND s.source_document_type='settlement'") if 'source_document_type' in right else sql.SQL('')
    if row.get('source_usage')=='duplicate':
        if 'order_refund_amount' in right: counterpart+=sql.SQL(' AND s.order_refund_amount>0')
        elif 'source_business_type' in right: counterpart+=sql.SQL(" AND s.source_business_type LIKE '%退款%'")
    query=sql.SQL('''WITH native AS (
        SELECT d.source_id,d.source_batch_id,d.shop_identity_key,d.{order}::text order_id
        FROM dwd.{source} d CROSS JOIN LATERAL dim.match_platform_operating_scene(%s,{doc},d.secondary_category_name,{biz},{desc}) m
        WHERE m.mapping_id=%s), proof AS (
        SELECT n.*,EXISTS(SELECT 1 FROM dwd.{target} s WHERE s.shop_identity_key=n.shop_identity_key
            AND s.{order}::text=n.order_id {counterpart}) matched FROM native n)
        SELECT count(*) source_rows,count(*) FILTER(WHERE matched) matched_rows,
            count(*) FILTER(WHERE NULLIF(btrim(order_id),'') IS NULL) missing_identity_rows,
            COALESCE(jsonb_agg(jsonb_build_object('batch_id',source_batch_id,'source_id',source_id,'order_no',order_id,'matched',matched)) FILTER(WHERE matched),'[]') samples
        FROM proof''').format(order=sql.Identifier(order),source=sql.Identifier(tables[0]),target=sql.Identifier(tables[1]),doc=doc,biz=business,desc=desc,counterpart=counterpart)
    cursor.execute(query,(p,row['mapping_id']))
    values=as_rows(cursor)[0]
    result.update(values)
    result['samples']=result['samples'][:5]
    verified_contract=(row['platform_code'],row['secondary_category_code']) in (ACCOUNTED.keys() | DUPLICATE.keys())
    result['correction_available']=bool(not verified_contract and result['source_rows'] and not result['matched_rows'] and not result['missing_identity_rows'])
    if verified_contract:
        result['identity_note']='这是已确认的结算/资金来源关系；当前没有关联记录也不能据此把净到账或退款过程再次计入。识别有误时先更正来源身份或描述匹配，避免未来主来源补齐后重复统计。'
    return result

def validate_change(cursor, row, treatment, payload):
    if not row or row.get('source_usage','independent')=='independent': return
    if payload.get('source_usage')=='independent':
        if len(str(payload.get('source_correction_reason','')).strip())<5:
            raise ValueError('更正来源判定需填写至少5字的独立业务依据')
        evidence=source_evidence(cursor,row)
        if not evidence['correction_available']:
            raise ValueError('来源仍有已统计关联或缺少可核对身份；请在“来源依据”查看关联记录并先更正来源/批次店铺。')
        return
    if treatment!='excluded':
        raise ValueError(row.get('source_usage_note') or '该金额已由另一来源统计；请打开“来源依据”核对并更正来源判定。')

def impact_rows(cursor, ids):
    if not ids:return []
    cursor.execute('''SELECT m.mapping_id,date_trunc('month',f.stat_date)::date stat_month,
        f.platform_name,f.company_name,f.shop_name,count(*) scene_rows,sum(f.source_detail_count) source_rows,
        sum(f.source_signed_amount) source_signed_amount,sum(f.income_amount) current_income,sum(f.expense_amount) current_expense
        FROM ads.ads_platform_operating_flow_company_shop_daily_scene f JOIN LATERAL (
            SELECT r.* FROM dim.dim_platform_fee_mapping r WHERE r.platform_code=f.platform_code AND r.source_document_type=f.source_document_type
            AND (r.source_component_code=f.secondary_category_code OR (r.source_component_code IS NULL AND
                (r.secondary_category_code=f.secondary_category_code OR left(f.secondary_category_code,length(r.secondary_category_code)+1)=r.secondary_category_code||'_' OR r.secondary_category_name=f.secondary_category_name)))
            ORDER BY (r.source_component_code=f.secondary_category_code) DESC NULLS LAST,(r.secondary_category_code=f.secondary_category_code) DESC,r.mapping_priority DESC,r.mapping_id LIMIT 1
        ) m ON TRUE WHERE m.mapping_id=ANY(%s)
        GROUP BY 1,2,3,4,5 ORDER BY 2,3,4,5,1''',(ids,))
    return as_rows(cursor)

def preview(cursor,payload):
    requested=payload.get('operating_treatment')
    if requested not in ('income','expense','excluded','pending',None): raise ValueError('无效的经营归属')
    chosen=None if requested=='pending' else requested
    rules={}
    from .service import FileIngestService
    selections=FileIngestService._expand_scene_selections(cursor,payload.get('items') or [])
    for item in selections:
        row=effective_rule(cursor,item)
        if row:
            treatment=chosen if 'operating_treatment' in payload else row['operating_treatment']
            validate_change(cursor,row,treatment,payload)
            rules[row['mapping_id']]=treatment
    rows=impact_rows(cursor,list(rules))
    total_income=total_expense=Decimal(0)
    for row in rows:
        t=rules[row['mapping_id']]
        row['proposed_income']=row['source_signed_amount'] if t=='income' else Decimal(0)
        row['proposed_expense']=-row['source_signed_amount'] if t=='expense' else Decimal(0)
        row['income_delta']=row['proposed_income']-row['current_income']
        row['expense_delta']=row['proposed_expense']-row['current_expense']
        total_income+=row['income_delta'];total_expense+=row['expense_delta']
    token=hashlib.sha256(json.dumps({'rows':rows,'requested':requested,'source_usage':payload.get('source_usage')},sort_keys=True,default=str).encode('utf-8')).hexdigest()
    note='作用于当前平台、来源及规则匹配的全部店铺和历史日期；预览基于已发布金额，未处理的新来源将在重算后体现。'
    if any(k in payload for k in ('source_description_match_type','source_description_match_value','mapping_priority')):
        note+=' 本次包含匹配条件，预览仅覆盖当前已匹配范围，新增匹配的影响需重算后核对。'
    return {'items':rows,'income_delta':total_income,'expense_delta':total_expense,'preview_token':token,
        'scope_note':note,
        'source_rows':sum(r['source_rows'] for r in rows),'rule_count':len(payload.get('items') or [])}
