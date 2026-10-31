"""Explicit source purpose, default suggestions, and finance-owned treatment."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = 'dim/463_platform_operating_policy_postgres.sql'

# These are documented source contracts, not an inference from RECONCILIATION.
# Availability movements/advances are deliberately absent: finance may reclassify.
ACCOUNTED = {
    ('douyin','goods_settlement_inflow'): '资金货款结算是结算明细的到账结果；商品收入和费用已由结算明细计算。',
    ('jd','merchant_settlement'): '商户结算到账与京东结算单互相核对；经营金额由结算单组成计算。',
    ('ks','goods_settlement'): '订单货款到账已由快手结算单还原商品收入和费用，不能再将净到账当作商品收入。',
    ('ks','refund_supplement_settlement'): '退款补结算到账用于核对快手结算单，不能与结算组成重复统计。',
}
DUPLICATE = {
    ('douyin','refund_after_settlement_to_user'): '该退款过程与订单结算退款属于同一业务事实；结算退款链路已统计。',
    ('ks','post_settlement_cash_refund'): '结算后退现金属于原退款的资金核对表示；经营退款由结算/补充退款链路计算。',
}

def as_rows(cursor):
    columns = [c[0] for c in cursor.description]
    return [dict(r) if isinstance(r,dict) else dict(zip(columns,r)) for r in cursor.fetchall()]

def default_treatment(platform, document, scene, business=None, description=None):
    """Only confirmed component/scene contracts get an automatic default."""
    if (platform,business) in {('ks','余额提现'),('wechat_channels','提现'),('jd','提现'),('douyin','提现')}:
        return 'excluded'
    if document=='settlement':
        known = {
            'douyin': {'平台服务费','技术服务费','达人佣金','服务商服务费','团长服务费'},
            'ks': {'技术服务费(元)','预售增收技术服务费（元）','达人佣金(元)','团长佣金(元)','快赚客佣金(元)','服务商佣金(元)','其他收费'},
            'jd': {'佣金','服务费','运费险','技术服务费'},
            'xhs': {'平台佣金','买手佣金','花呗分期手续费','运费宝'},
        }
        if scene in known.get(platform,set()): return 'expense'
        if platform=='jd' and scene=='货款': return 'income'
    if platform=='douyin' and scene=='带货佣金未开票抵扣': return 'expense'
    if platform=='ks':
        if business=='佣金/技术服务费返还': return 'expense'
        if business=='资金扣减' and description=='退货包运费服务扣款': return 'expense'
        if business in ('资金冻结','资金解冻','扣减前临时解冻'): return 'excluded'
    return None

def initialize_policy(cursor):
    cursor.execute((ROOT/'sql'/MIGRATION).read_text(encoding='utf-8'))
    cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping WHERE NOT policy_initialized ORDER BY mapping_id')
    for row in as_rows(cursor):
        key=(row['platform_code'],row['secondary_category_code'])
        usage='accounted' if key in ACCOUNTED else 'duplicate' if key in DUPLICATE else 'independent'
        note=ACCOUNTED.get(key) or DUPLICATE.get(key) or ((row.get('classification_note') or '独立金额项目。')+' 经营归属可由财务重新确认；文件覆盖和流水防重继续执行。')
        treatment=row['operating_treatment']
        origin='pending' if treatment is None else 'system' if row['created_by']=='operating_discovery' else 'historical'
        cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET source_usage=%s,source_usage_note=%s,
            treatment_origin=%s,suggested_operating_treatment=%s,policy_initialized=TRUE WHERE mapping_id=%s''',
            (usage,note,origin,treatment,row['mapping_id']))
    # This source name is an alias of the actual income formula component.
    cursor.execute('''UPDATE dim.dim_platform_fee_mapping a SET alias_of_mapping_id=b.mapping_id
        FROM dim.dim_platform_fee_mapping b WHERE a.platform_code='xhs'
        AND a.secondary_category_name='申诉调账' AND a.source_component_code IS NULL
        AND b.platform_code='xhs' AND b.source_component_code='xhs_appeal_adjustment_income'
        AND a.alias_of_mapping_id IS NULL''')
    # Known new scenes enter through the supplemental branch (canonical NULL).
    # Their explanatory roles can be corrected without enabling the old fee path.
    cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET
        source_role=CASE WHEN source_business_type='佣金/技术服务费返还' THEN 'EXPENSE_OFFSET'
            WHEN secondary_category_name='资金扣减 + 快手小店退款-超售后期' THEN 'REFUND_SUPPLEMENT' ELSE 'SUPPLEMENT' END,
        metric_role=CASE WHEN source_business_type='佣金/技术服务费返还' THEN 'EXPENSE_OFFSET'
            WHEN secondary_category_name='资金扣减 + 快手小店退款-超售后期' THEN 'MAIN_REFUND' ELSE 'PLATFORM_EXPENSE' END
        WHERE platform_code='ks' AND canonical_operating_treatment IS NULL AND source_role='RECONCILIATION'
        AND operating_treatment IS NOT NULL AND (source_business_type='佣金/技术服务费返还'
            OR secondary_category_name IN ('资金扣减 + 快手小店退款-超售后期','资金转账 + 退货包运费垫资追款'))''')

def present_policy(row):
    """Expose meaning, not legacy compatibility switches, to the UI."""
    row=dict(row)
    usage=row.get('source_usage','independent')
    row['source_usage_label']={'independent':'可配置的独立金额','accounted':'已由主来源统计','duplicate':'重复业务事实'}.get(usage,usage)
    row['treatment_editable']=usage=='independent'
    row['treatment_origin_label']={'historical':'历史保留','manual':'人工确认','system':'系统规则','pending':'归属待确认'}.get(row.get('treatment_origin'),'归属待确认' if row.get('operating_treatment') is None else '历史保留')
    row['effective_operating_treatment']='excluded' if usage!='independent' else row.get('operating_treatment')
    row['source_usage_note']=row.get('source_usage_note') or '独立业务金额，可修改经营归属。'
    status=row.get('configuration_etl_status')
    row['configuration_status_label']=('已生效' if status=='success' else '重算失败' if status in ('failed','cancelled')
        else '重算中' if status=='running' else '等待重算' if status in ('queued','deferred') else '当前配置')
    return row

def automatic_classification_note(row,treatment,category_name):
    """Current-state template; finance-authored business notes remain untouched."""
    if treatment is None:return f'经营归属待财务确认；当前一级分类：{category_name}。'
    if treatment=='income':return f'已确认计入经营收入，退款负金额冲减收入；一级分类：{category_name}。'
    if treatment=='expense':return f'已确认计入经营支出，费用返还冲减支出；一级分类：{category_name}。'
    if row.get('source_business_type') in ('资金冻结','资金解冻','扣减前临时解冻') and '退款' in row.get('secondary_category_name',''):
        return f'退款过程的冻结或解冻资金变动，已确认不计入经营收支；一级分类：{category_name}。'
    return f'已确认不计入经营收支，保留原始明细；一级分类：{category_name}。'

def maintain_automatic_note(old,treatment,category_name,note):
    legacy={'经营归属待确认','经营性质待确认；未按金额符号自动归属。','经营性质待确认；未按金额符号自动归类。',
        '分类未映射；经营归属来自已确认来源规则。','分类按已确认来源业务场景生成；经营归属沿用来源规则。',
        '由既有收入公式迁移；负金额继续冲减收入。'}
    if old and note==old.get('classification_note') and (note in legacy or note==automatic_classification_note(old,old.get('operating_treatment'),old.get('primary_category_name'))):
        return automatic_classification_note(old,treatment,category_name)
    return note
