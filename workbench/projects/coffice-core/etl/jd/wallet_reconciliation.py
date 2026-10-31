"""Reconcile settlement groups without mistaking observed dates for coverage."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from etl.common.errors import SourceNotReady


# Same seven-field event key and direction formula as JD's existing DWD SQL.
# Validate against frozen ODS sources so an adjacent month's wallet is usable
# without publishing that month, or reading newer published DWD from a replay.
FUND_SOURCE = '''WITH cleaned AS (
    SELECT r.*,c.shop_identity_key,
        MD5(CONCAT_WS(CHR(31),BTRIM(COALESCE(r."商户订单号",'')),BTRIM(COALESCE(r."交易订单号",'')),
            BTRIM(COALESCE(r."支出类型",'')),BTRIM(COALESCE(r."交易金额",'')),BTRIM(COALESCE(r."交易类型",'')),
            BTRIM(COALESCE(r."入账时间",'')),BTRIM(COALESCE(r."资金动账备注",'')))) event_key
    FROM common.v_selected_jd_fund_raw r JOIN common.v_ingest_batch_shop_context c USING(batch_id)
    WHERE c.platform_code='jd' AND c.target_table='ods_jd_fund_raw'
      AND (%s::text[]='{}'::text[] OR c.shop_code=ANY(%s::text[]))
), latest AS (
    SELECT DISTINCT ON(shop_identity_key,event_key) * FROM cleaned
    ORDER BY shop_identity_key,event_key,ingest_time DESC,id DESC
), wallet AS (
    SELECT shop_identity_key,NULLIF(BTRIM("商户订单号"),'') merchant_order_no,
        BTRIM("交易类型") business_type,NULLIF(NULLIF(BTRIM("入账时间"),''),'-')::timestamp::date event_date,
        CASE BTRIM("支出类型") WHEN '收入' THEN ROUND(REPLACE(BTRIM("交易金额"),',','')::numeric,2)
            WHEN '支出' THEN -ROUND(REPLACE(BTRIM("交易金额"),',','')::numeric,2) END signed_amount
    FROM latest
) '''


def expected_wallet_date(merchant, settlement_date):
    prefix = str(merchant or '')[:8]
    if re.fullmatch(r'20[0-9]{6}',prefix):
        try:
            return date(int(prefix[:4]),int(prefix[4:6]),int(prefix[6:8]))
        except ValueError:
            pass
    return settlement_date + timedelta(days=1)


def unmatched_status(expected, coverage, as_of):
    days = set(coverage.get('verified_days',[]))
    if expected.isoformat() in days:
        return 'missing_count'
    if expected >= as_of:
        return 'pending_count'
    return 'uncovered_count' if days else 'coverage_unknown_count'


def validate(cursor, context=None):
    context = context if context is not None else getattr(getattr(cursor.connection, 'refresh_scope', None), 'context', {})
    months = context.get('months', {}).get('jd', [])
    shops = context.get('shops', {}).get('jd', [])
    scope = '''source_document_type='settlement' AND NULLIF(merchant_order_no,'') IS NOT NULL
        AND (%s::date[]='{}'::date[] OR DATE_TRUNC('month',stat_date)::date=ANY(%s::date[]))
        AND (%s::text[]='{}'::text[] OR shop_code=ANY(%s::text[]))'''
    args = (months,months,shops,shops)
    cursor.execute('''SELECT shop_identity_key,merchant_order_no,MIN(stat_date),MAX(stat_date),
        ROUND(SUM(signed_amount),2) FROM dwd.dwd_jd_platform_expense_source_detail
        WHERE '''+scope+' GROUP BY 1,2 ORDER BY 1,2',args)
    settlement = cursor.fetchall()
    cursor.execute('''SELECT shop_identity_key,source_batch_id,MIN(stat_date),MAX(stat_date)
        FROM dwd.dwd_jd_platform_expense_source_detail WHERE '''+scope+' GROUP BY 1,2 ORDER BY 1,2',args)
    batches = [{'shop_identity_key':s,'batch_id':b,'date_from':low,'date_to':high}
               for s,b,low,high in cursor.fetchall()]
    cursor.execute(FUND_SOURCE+'''SELECT shop_identity_key,merchant_order_no,ROUND(SUM(signed_amount),2)
        FROM wallet WHERE business_type='商户结算' AND merchant_order_no IS NOT NULL GROUP BY 1,2''',(shops,shops))
    funds = {(shop,merchant): amount for shop,merchant,amount in cursor.fetchall()}
    cursor.execute(FUND_SOURCE+'''SELECT shop_identity_key,MIN(event_date),MAX(event_date) FROM wallet GROUP BY 1''',(shops,shops))
    windows = {shop:(low,high) for shop,low,high in cursor.fetchall()}
    coverage = context.get('fund_coverage',{})
    as_of = date.fromisoformat(context['as_of_date']) if context.get('as_of_date') else datetime.now(ZoneInfo('Asia/Shanghai')).date()
    result = {'settlement_group_count':len(settlement),
        'settlement_batch_count':len(settlement),  # Deprecated compatibility alias: group count, not ODS batches.
        'source_batch_count':len({r['batch_id'] for r in batches}),'settlement_batches':batches,
        'matched_count':0, 'pending_count':0,
        'missing_count':0, 'amount_mismatch_count':0, 'settlement_total':Decimal('0'),
        'uncovered_count':0,'coverage_unknown_count':0,
        'fund_total':Decimal('0'), 'settlement_date_from':None, 'settlement_date_to':None,
        'fund_extract_from':min((v[0] for v in windows.values() if v[0]),default=None),
        'fund_extract_to':max((v[1] for v in windows.values() if v[1]),default=None),
        'fund_observed_dates':{s:{'low':lo,'high':hi} for s,(lo,hi) in windows.items()},
        'fund_coverage':coverage,'as_of_date':as_of,'exceptions':[]}
    for shop, merchant, start, end, amount in settlement:
        expected = expected_wallet_date(merchant,start)
        wallet = funds.get((shop,merchant))
        key = ('matched_count' if wallet == amount else 'amount_mismatch_count') if wallet is not None else unmatched_status(expected,coverage.get(shop,{}),as_of)
        result[key] += 1
        result['settlement_total'] += amount
        result['fund_total'] += wallet or Decimal('0')
        result['settlement_date_from'] = min(result['settlement_date_from'] or start,start)
        result['settlement_date_to'] = max(result['settlement_date_to'] or end,end)
        if key != 'matched_count':
            result['exceptions'].append({'shop_identity_key':shop,'merchant_order_no':merchant,
                'settlement_amount':amount,'fund_amount':wallet,'expected_wallet_date':expected,
                'observed_dates':windows.get(shop),'status':key})
    print('[WALLET_RECONCILIATION] '+json.dumps(result,ensure_ascii=False,default=str),flush=True)
    if any(result[k] for k in ('missing_count','amount_mismatch_count','uncovered_count','coverage_unknown_count')):
        error_type = RuntimeError
        if (context.get('mode') == 'incremental' and context.get('trigger_type') == 'ingest_complete'
                and not result['missing_count'] and not result['amount_mismatch_count']):
            error_type = SourceNotReady
        raise error_type('京东结算到钱包对账未通过：'
            f"missing={result['missing_count']}，amount_mismatch={result['amount_mismatch_count']}，"
            f"fund_not_covered={result['uncovered_count']}，fund_coverage_unknown={result['coverage_unknown_count']}，"
            f"batch_cutoff={context.get('batch_cutoff')}，exceptions={result['exceptions'][:20]}；"
            '已验证范围内无匹配流水才判真实缺失；资金范围未覆盖或完整性未知时同样停止刷新。'
            '交易首末日期不能证明完整覆盖；请补齐对应完整导出，若已经补入请使用“使用最新数据重跑”。')
    return result
