"""One shared business classification catalog, independent of money routing.

Rebuilding explicitly reclassifies existing scenes, migrates references, and
deletes unused legacy aliases. Subsequent ETL only discovers new scenes; it
does not overwrite a category or treatment chosen later by finance.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG_SQL = 'dim/462_platform_category_name_identity_postgres.sql'

# Codes remain stable across platforms. Chargebacks/returns use the same
# category as their originating fee and keep their original calculation sign.
CATALOG = {
    'sales_income': ('商品销售收入', '订单货款、商品实收及订单优惠券收入。'),
    'sales_refund': ('销售退款', '实际订单退款及补充退款；金额方向由原来源公式保留。'),
    'platform_subsidy': ('平台补贴', '平台、支付、政府及达人补贴的已确认收入组成。'),
    'merchant_subsidy': ('商家优惠', '商家承担的优惠或补贴，沿用原来源冲减符号。'),
    'collected_delivery_income': ('代收配送收入', '已确认归收入的代收配送金额。'),
    'other_operating_income': ('其他经营收入', '小额收款及申诉调账等已确认经营收入。'),
    'platform_commission': ('平台佣金', '平台交易佣金及其返还。'),
    'platform_service_fee': ('平台服务费', '技术、交易及软件服务费和原费项返还。'),
    'payment_service_fee': ('支付手续费', '支付、分期渠道手续费及其返还。'),
    'influencer_commission': ('达人佣金', '达人、团长、买手及带货机构佣金和返还。'),
    'service_provider_commission': ('服务商佣金', '平台服务商佣金和返还。'),
    'channel_share': ('渠道分成', '渠道经营分成。'),
    'promotion_expense': ('推广费用', '联盟、站外、多多进宝及拉新推广费用和返还。'),
    'marketing_discount_fee': ('营销活动费用', '红包、淘金币、返点及其他营销优惠费用和冲回。'),
    'baiyibutie': ('百亿补贴服务费', '百亿补贴活动相关软件或渠道服务费用和返还。'),
    'after_sale_compensation': ('售后赔付', '消费者补偿、直赔及售后申诉费用冲回，不含销售退款。'),
    'small_payment_expense': ('小额打款', '已确认小额打款，含历史已确认归入此类的业务。'),
    'freight_insurance_expense': ('运费保险', '退货包运费、运费宝、运费险及其追款或理赔冲回。'),
    'product_insurance_expense': ('商品保险', '商品保险服务费及其冲回。'),
    'fulfillment_guarantee_expense': ('履约保障费', '履约、权益保障和已确认履约保险费用。'),
    'penalty_expense': ('违约金', '延迟或虚假发货等违约处罚费用。'),
    'logistics_fee': ('物流服务费', '常规物流、快递及偏远地区配送服务费用。'),
    'return_shipping_expense': ('退货物流费', '商责退运费、退货上门取件及历史已确认退货物流金额。'),
    'consolidated_shipping_expense': ('集运物流费', '商家集运、集运中转及原确认冻结/解冻/扣减过程净额。'),
    'jd_bean_expense': ('京豆费用', '随单京豆等已确认京豆费用。'),
    'other_platform_expense': ('其他平台费用', '性质已确认为费用但无更具体业务分类的原费项。'),
    'account_transfer': ('账户划转', '提现、广告账户划转等已确认不计入经营的账户移动。'),
    'settlement_reconciliation': ('结算核对', '货款到账、退款过程、垫资回补及其他来源已统计的核对项。'),
    'non_operating': ('其他非经营收支', '明确不计入经营且不属于账户划转或结算核对的来源。'),
    'pending_nature': ('待确认款项', '原始业务可见但经营性质尚未确认，不推断收入或费用。'),
}

ALIASES = {
    'product_sales_income': 'sales_income',
    'after_sales_expense': 'after_sale_compensation',
    'after_sales_compensation_expense': 'after_sale_compensation',
    'small_payment': 'small_payment_expense',
    'guarantee_insurance': 'fulfillment_guarantee_expense',
    'shipping_insurance': 'freight_insurance_expense',
    'violation_penalty': 'penalty_expense',
    'reverse_logistics_expense': 'return_shipping_expense',
    'return_logistics_fee': 'return_shipping_expense',
    'marketing_activity_expense': 'marketing_discount_fee',
    'excluded': 'non_operating',
    'non_expense_collected_delivery_fee': 'collected_delivery_income',
    'non_expense_merchant_settlement': 'settlement_reconciliation',
    'non_expense_payment_marketing_return': 'settlement_reconciliation',
    'non_expense_account_transfer': 'account_transfer',
    'non_expense_goods_payment': 'sales_income',
    'non_expense_goods_settlement': 'settlement_reconciliation',
    'non_expense_refund_reconciliation': 'settlement_reconciliation',
    'non_expense_sales_refund': 'sales_refund',
}


def _rows(cursor):
    columns = [c[0] for c in cursor.description]
    return [dict(r) if isinstance(r, dict) else dict(zip(columns, r)) for r in cursor.fetchall()]


def category_for_scene(scene):
    """Choose a classification only; never decide or change operating nature."""
    treatment = scene.get('operating_treatment')
    text = ' '.join(str(scene.get(k) or '') for k in
                    ('secondary_category_name', 'source_business_type', 'source_description_match_value'))
    old = scene.get('primary_category_code') or ''
    component = scene.get('source_component_code') or ''
    if treatment is None:
        return 'pending_nature'
    if treatment == 'excluded':
        if any(x in text for x in ('提现', '广告账户', '账户划转')) or old == 'non_expense_account_transfer':
            return 'account_transfer'
        if old.startswith('non_expense_') or any(x in text for x in ('结算', '退款', '冻结', '解冻', '垫资', '回补', '支付营销回退')):
            return 'settlement_reconciliation'
        return 'non_operating'
    if treatment == 'income':
        if '退款' in text or 'refund' in component or old in ('sales_refund', 'non_expense_sales_refund'):
            return 'sales_refund'
        if '代收配送' in text:
            return 'collected_delivery_income'
        if '小额收款' in text or '申诉调账' in text:
            return 'other_operating_income'
        if 'subsidy' in component or old == 'platform_subsidy':
            return 'merchant_subsidy' if component == 'merchant_subsidy' else 'platform_subsidy'
        return ALIASES.get(old, old) if ALIASES.get(old, old) in CATALOG else 'sales_income'
    # Preserve documented scene-specific historical decisions, including the
    # KS deposit-wallet recharge explicitly confirmed as small payments.
    if old in ('small_payment', 'small_payment_expense'):
        return 'small_payment_expense'
    if any(x in text for x in ('运费险', '运费宝', '运费保险', '退换货运费险', '退货包运费', '挽单补偿险')):
        return 'freight_insurance_expense'
    if '百亿补贴' in text or old == 'baiyibutie':
        return 'baiyibutie'
    if any(x in text for x in ('淘金币', '返点积分', '限时红包', '返现/返券')):
        return 'marketing_discount_fee'
    if '小额打款' in text:
        return 'small_payment_expense'
    if '集运' in text:
        return 'consolidated_shipping_expense'
    if '服务商佣金' in text:
        return 'service_provider_commission'
    if '品牌新享新品孵化软件服务费' in text:
        return 'platform_service_fee'
    if '天猫佣金' in text and '百补订单预收' not in text:
        return 'platform_commission'
    if old == 'non_expense_sales_refund' and '运费补偿' in text:
        return 'return_shipping_expense'
    if old == 'unmapped':
        if '佣金' in text or '带货佣金未开票抵扣' in text:
            return 'influencer_commission'
        if '技术服务费' in text:
            return 'platform_service_fee'
        return 'other_platform_expense'
    return ALIASES.get(old, old) if ALIASES.get(old, old) in CATALOG else 'other_platform_expense'


def ensure_category(cursor, code):
    name, note = CATALOG[code]
    cursor.execute('''INSERT INTO dim.dim_platform_fee_primary_category(
        primary_category_code,primary_category_name,display_order,classification_note,
        platform_code,created_by,updated_by)
        VALUES(%s,%s,%s,%s,NULL,'category_catalog','category_catalog')
        ON CONFLICT DO NOTHING''', (code, name, list(CATALOG).index(code) * 10, note))
    cursor.execute('SELECT primary_category_code,primary_category_name FROM dim.dim_platform_fee_primary_category WHERE primary_category_code=%s', (code,))
    result = _rows(cursor)
    if not result:
        # A manually maintained same-name category keeps its stable code.
        cursor.execute('''SELECT primary_category_code,primary_category_name
            FROM dim.dim_platform_fee_primary_category
            WHERE dim.platform_category_name_key(primary_category_name)=
                  dim.platform_category_name_key(%s)''', (name,))
        result = _rows(cursor)
    if len(result) != 1:
        raise RuntimeError(f'一级分类{code}不能唯一关联，停止迁移')
    return result[0]['primary_category_code'], result[0]['primary_category_name']


def rebuild_catalog(cursor):
    """Explicit catalog rebuild, preserving every formula and treatment field."""
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('platform_category_catalog'))")
    cursor.execute('SELECT * FROM dim.dim_platform_fee_mapping ORDER BY mapping_id')
    mappings = _rows(cursor)
    decisions = [(row, category_for_scene(row)) for row in mappings]
    target_codes = {code for _, code in decisions}
    for code in target_codes:
        cursor.execute('''INSERT INTO dim.dim_platform_fee_primary_category(
            primary_category_code,primary_category_name,display_order,classification_note,
            platform_code,created_by,updated_by)
            VALUES(%s,%s,%s,%s,NULL,'category_catalog','category_catalog')
            ON CONFLICT(primary_category_code) DO UPDATE SET
                primary_category_name=EXCLUDED.primary_category_name,
                classification_note=EXCLUDED.classification_note,
                display_order=EXCLUDED.display_order,platform_code=NULL,is_active=TRUE,
                updated_by='category_catalog' ''',
            (code, CATALOG[code][0], list(CATALOG).index(code)*10, CATALOG[code][1]))
    changed=[]
    for row, code in decisions:
        name=CATALOG[code][0]
        if (row['primary_category_code'], row['primary_category_name']) != (code, name):
            cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET primary_category_code=%s,
                primary_category_name=%s,updated_by='category_catalog' WHERE mapping_id=%s''',
                (code,name,row['mapping_id']))
            changed.append({'mapping_id':row['mapping_id'],'platform_code':row['platform_code'],
                            'before_code':row['primary_category_code'],'before_name':row['primary_category_name'],
                            'after_code':code,'after_name':name})
    cursor.execute('''DELETE FROM dim.dim_platform_fee_primary_category c
        WHERE NOT EXISTS (SELECT 1 FROM dim.dim_platform_fee_mapping m
                          WHERE m.primary_category_code=c.primary_category_code)
          AND (c.primary_category_code=ANY(%s) OR EXISTS (
              SELECT 1 FROM dim.dim_platform_fee_primary_category keep
              WHERE keep.primary_category_code=ANY(%s)
                AND lower(regexp_replace(keep.primary_category_name,'[[:space:]　]+','','g'))=
                    lower(regexp_replace(c.primary_category_name,'[[:space:]　]+','','g'))))
        RETURNING c.primary_category_code,c.primary_category_name''',
        (list(ALIASES), list(target_codes)))
    deleted=_rows(cursor)
    cursor.execute((ROOT/'sql'/CATALOG_SQL).read_text(encoding='utf-8'))
    return {'reclassified':changed,'deleted_categories':deleted,'rules':len(mappings)}


def ensure_catalog(cursor):
    """Initialize once; later repair only categories reintroduced by old seeds."""
    cursor.execute("SELECT to_regclass('dim.dim_platform_fee_primary_category') category,to_regclass('dim.uq_platform_primary_category_name_key') ready")
    state=_rows(cursor)[0]
    if state['category'] is None:
        cursor.execute((ROOT/'sql/dim/369_dim_platform_fee_primary_category_postgres.sql').read_text(encoding='utf-8'))
        cursor.execute('ALTER TABLE dim.dim_platform_fee_primary_category ADD COLUMN IF NOT EXISTS platform_code VARCHAR(32)')
    if not state['ready']:
        return rebuild_catalog(cursor)
    cursor.execute('''SELECT m.* FROM dim.dim_platform_fee_mapping m
        WHERE m.primary_category_code=ANY(%s)
           OR (m.primary_category_code<>'unmapped' AND NOT EXISTS (
               SELECT 1 FROM dim.dim_platform_fee_primary_category c
               WHERE c.primary_category_code=m.primary_category_code))''',(list(ALIASES),))
    for row in _rows(cursor):
        code,name=ensure_category(cursor,category_for_scene(row))
        cursor.execute('''UPDATE dim.dim_platform_fee_mapping SET primary_category_code=%s,
            primary_category_name=%s,updated_by='category_catalog' WHERE mapping_id=%s''',
            (code,name,row['mapping_id']))
    cursor.execute('''DELETE FROM dim.dim_platform_fee_primary_category c
        WHERE c.primary_category_code=ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM dim.dim_platform_fee_mapping m
                          WHERE m.primary_category_code=c.primary_category_code)''',(list(ALIASES),))
    return None
