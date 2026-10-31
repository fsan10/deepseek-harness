"""One content comparison and source-selection contract for UI and API uploads.

This module never writes ODS. Row counts and amounts are explanatory; equality
requires the full multiset of normalized business fields, including multiplicity.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from psycopg2 import sql
from psycopg2.extras import Json
from .registry import REPORT_BY_TYPE

ROOT = Path(__file__).resolve().parents[2]
SUPPORTED = {
    'douyin_settlement': ('ods_douyin_settlement_raw', '结算时间', '结算金额'),
    'douyin_fund': ('ods_douyin_fund_raw', '动账时间', '动账金额'),
    'jd_settlement': ('ods_jd_settlement_raw', '账单日期', '金额'),
    'jd_fund': ('ods_jd_fund_raw', '入账时间', '交易金额'),
    'wechat_channels_settlement': ('ods_wechat_channels_settlement_raw', '记账时间', '收支金额'),
}
MODES = {'fill_gaps', 'replace_range', 'refresh_only'}


class CoverageConflict(ValueError):
    http_status = 409


def canonical(value):
    if value is None or str(value).strip() == '':
        return None
    value = str(value).replace('\ufeff', '').strip()
    if value.startswith('="') and value.endswith('"'):
        value = value[2:-1]
    return value


def business_day(value):
    value = canonical(value)
    if not value:
        raise ValueError('文件明细缺少业务日期；不能从文件名推断覆盖范围')
    if len(value) == 8 and value.isdigit():
        return datetime.strptime(value, '%Y%m%d').date().isoformat()
    return date.fromisoformat(value[:10]).isoformat()


def normalize_claim(value):
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    claim = dict(value or {})
    if bool(claim.get('start')) != bool(claim.get('end')):
        raise ValueError('完整查询开始、结束日期必须同时填写')
    if claim.get('start'):
        start, end = date.fromisoformat(str(claim['start'])), date.fromisoformat(str(claim['end']))
        if start > end or (end - start).days > 366:
            raise ValueError('查询范围无效或超过367天，请分段提交')
        if end >= datetime.now(ZoneInfo('Asia/Shanghai')).date():
            raise ValueError('账单完整查询结束日期最多为昨天')
        claim['start'], claim['end'] = start.isoformat(), end.isoformat()
        if claim.get('complete_export') is not True:
            raise ValueError('填写查询范围时须明确确认文件为该区间的完整导出')
    empty = claim.get('confirmed_empty_days', [])
    if not isinstance(empty, list):
        raise ValueError('confirmed_empty_days必须为日期列表')
    claim['confirmed_empty_days'] = sorted({date.fromisoformat(str(d)).isoformat() for d in empty})
    if claim.get('bill_date'):
        claim['bill_date'] = date.fromisoformat(str(claim['bill_date'])).isoformat()
    if claim.get('artifact_id'):
        try:claim['artifact_id']=str(uuid.UUID(str(claim['artifact_id'])))
        except (ValueError,TypeError) as exc:raise ValueError('artifact_id必须为有效UUID') from exc
    return claim


def normalize_draft_claim(value):
    """Persist incomplete form input without treating it as approved coverage."""
    if not isinstance(value, dict):
        raise ValueError('草稿查询范围必须为对象')
    claim = {}
    for key in ('start', 'end', 'bill_date'):
        if value.get(key):
            claim[key] = date.fromisoformat(str(value[key])).isoformat()
    claim['complete_export'] = value.get('complete_export') is True
    claim['reason'] = str(value.get('reason') or '').strip()[:2000]
    days = value.get('confirmed_empty_days', [])
    if not isinstance(days, list):
        raise ValueError('零交易确认必须为日期列表')
    claim['confirmed_empty_days'] = sorted({date.fromisoformat(str(d)).isoformat() for d in days})
    if value.get('artifact_id'):
        claim['artifact_id'] = str(uuid.UUID(str(value['artifact_id'])))
    return claim


def load_file(task, storage_root):
    """Use precisely the loader's header alignment and source rows."""
    if str(ROOT / 'etl') not in sys.path:
        sys.path.insert(0, str(ROOT / 'etl'))
    from common.ods_file_loader import (align_source_map, canonicalize_header,
                                       read_csv_rows, read_excel_rows, read_legacy_excel_rows,
                                       validate_header)
    report = task['report_type']
    platform = REPORT_BY_TYPE[report].platform_code
    config = importlib.import_module(f'etl.{platform}.load_{report}_ods').CONFIG
    path = (Path(storage_root) / task['storage_path']).resolve()
    if not path.is_relative_to(Path(storage_root).resolve()):
        raise ValueError('文件存储路径越界')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != task['file_hash']:
        raise ValueError('原始上传文件缺失或SHA256改变，请重新上传')
    reader = read_csv_rows if path.suffix.lower() == '.csv' else read_legacy_excel_rows if path.suffix.lower() == '.xls' else read_excel_rows
    values = reader(config, path) if reader is read_csv_rows else reader(config, path, None)
    header, _ = canonicalize_header(values[3], config.header_aliases)
    validate_header(header, config.expected_columns, False, config.optional_columns)
    rows = [align_source_map(header, row, config.expected_columns) for _, row in values[4]]
    if report == 'jd_settlement':
        claim = task.get('coverage') or {}
        bill_date = claim.get('bill_date') or (claim.get('start') if claim.get('start') == claim.get('end') else None)
        for row in rows:
            if not canonical(row.get('账单日期')):
                if not bill_date:
                    raise ValueError('京东文件缺少账单日期，请为该文件明确填写bill_date，或提供单日完整查询范围；不得从文件名推断')
                row['账单日期'] = bill_date
    return config.expected_columns, rows


def fingerprint_rows(rows, columns):
    counts = Counter(hashlib.sha256(json.dumps([canonical(r.get(c)) for c in columns],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest() for r in rows)
    return hashlib.sha256(json.dumps(sorted(counts.items()), separators=(',', ':')).encode()).hexdigest()


def effective_old_rows(cursor, task, columns, exclude_batches=(), bounds=None):
    table, date_field, _ = SUPPORTED[task['report_type']]
    # Reads the existing chosen source, including explicit prior decisions.
    view = ('v_current_' if task['resolved_platform_code'] in ('douyin','wechat_channels') else 'v_selected_') + table.removeprefix('ods_')
    # Exclude a just-loaded/unadopted batch BEFORE wallet version selection.
    # Filtering v_current afterwards loses the older version it already hid.
    native_versions = task['report_type'] in ('douyin_fund','wechat_channels_settlement') and bool(exclude_batches)
    if native_versions:
        view = 'v_selected_' + table.removeprefix('ods_')
    cursor.execute(sql.SQL('''SELECT r.* FROM common.{} r
        JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
        WHERE c.shop_identity_key=%s AND (%s::date IS NULL OR
            NULLIF(NULLIF(BTRIM(r.{}),''),'-')::timestamp::date BETWEEN %s::date AND %s::date)
        ORDER BY r.ingest_time,r.id''').format(sql.Identifier(view),sql.Identifier(date_field)),
        (task['shop_identity_key'], bounds[0] if bounds else None, *(bounds or (None,None))))
    rows = [dict(r) for r in cursor.fetchall()]
    if exclude_batches:
        # An already approved day is authoritative even if its batch also
        # appears in the legacy upload being recovered. Never undo that choice.
        choices = day_choices(cursor, task, bounds) if bounds else {}
        rows = [r for r in rows if r['batch_id'] not in exclude_batches
                or business_day(r[date_field]) in choices]
    if native_versions:
        key='流水单号' if task['report_type']=='wechat_channels_settlement' else '动帐流水号'
        rows = list({(str(r.get('动账账户') or '').strip(), str(r.get(key) or '').strip()): r
                     for r in rows}.values())
    if task['resolved_platform_code'] == 'jd':
        # The established JD keys are documents or seven-field wallet events,
        # not amount or order alone. Preserve their current DWD semantics.
        keys = ['单据编号'] if table.endswith('settlement_raw') else ['商户订单号','交易订单号','支出类型','交易金额','交易类型','入账时间','资金动账备注']
        latest = {tuple(canonical(r.get(k)) for k in keys): r for r in rows}
        rows = list(latest.values())
    by_day = defaultdict(list)
    for row in rows:
        by_day[business_day(row[date_field])].append(row)
    return by_day


def compare_days(new, old, columns, *, mode, claim, amount_column=None, choices=None):
    """Pure decision function, also used for concurrency checks at activation."""
    dates = set(new)
    if claim.get('start'):
        start, end = date.fromisoformat(claim['start']), date.fromisoformat(claim['end'])
        outside = sorted(d for d in dates if not claim['start'] <= d <= claim['end'])
        if outside:
            raise ValueError(f'文件业务日期超出完整查询范围：{outside[:5]}')
        dates |= {(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
    if mode == 'replace_range' and (not claim.get('start') or not str(claim.get('reason', '')).strip()):
        raise ValueError('以本次文件为准必须填写完整查询范围、完整导出确认和替换原因')
    results = []
    def amount(rows):
        try:
            return str(sum((Decimal((canonical(r.get(amount_column)) or '0').replace(',','')) for r in rows
                            if canonical(r.get(amount_column)) not in (None,'-')), Decimal('0')))
        except InvalidOperation as exc:
            raise ValueError('报表金额字段不是合法数字，请核对文件内容') from exc
    confirmed_empty = set(claim.get('confirmed_empty_days', []))
    for day in sorted(dates):
        before, after = old.get(day, []), new.get(day, [])
        same = fingerprint_rows(before, columns) == fingerprint_rows(after, columns)
        status = 'same' if same and after else 'empty_both' if same else 'new_only' if not before else 'empty_new' if not after else 'different'
        choice = (choices or {}).get(day)
        if status == 'new_only' and choice is not None and not choice['batch_ids']:
            status = 'different'  # An explicitly confirmed zero is not a gap.
        blocked = status == 'different' and mode in ('fill_gaps','refresh_only')
        blocked |= status == 'empty_new' and mode == 'replace_range' and day not in confirmed_empty
        account_column = next((c for c in ('动账账户','结算账户') if c in columns),None)
        missing_accounts = sorted({canonical(r.get(account_column)) or '' for r in before} -
                                  {canonical(r.get(account_column)) or '' for r in after}) if account_column else []
        if mode == 'replace_range' and after and missing_accounts:
            blocked = True  # Do not replace another account with a partial export.
        results.append({'date': day, 'status': status, 'old_rows': len(before), 'new_rows': len(after),
            'old_batches': sorted({int(r['batch_id']) for r in before}), 'blocked': blocked,
            'old_selection_id': choice['selection_id'] if choice else None,
            'missing_accounts':missing_accounts,
            'old_amount': amount(before), 'new_amount': amount(after),
            'new_digest': fingerprint_rows(after, columns),
            'old_digest': fingerprint_rows(before, columns)})
    return results


def day_choices(cursor, task, bounds):
    cursor.execute('''SELECT stat_date,batch_ids,selection_id FROM common.v_ingest_source_day_selection
        WHERE shop_identity_key=%s AND target_table=%s AND stat_date BETWEEN %s AND %s''',
        (task['shop_identity_key'],SUPPORTED[task['report_type']][0],*bounds))
    return {str(r['stat_date']):dict(r) for r in cursor.fetchall()}


def legacy_unselected_batches(cursor, tasks):
    """Only completed uploads from before the coverage workflow are candidates."""
    batches = sorted({int(t['batch_id']) for t in tasks
                      if t.get('batch_id') and t['status'] in ('success', 'duplicate')
                      and t['report_type'] in SUPPORTED})
    if not batches:
        return []
    cursor.execute('''SELECT DISTINCT f.batch_id FROM ops.ingest_file_task f
        JOIN ops.ingest_run r ON r.run_id=f.run_id
        WHERE f.batch_id=ANY(%s) AND f.status='success'
          AND r.status IN ('success','failed') AND r.import_mode='fill_gaps'
          AND (r.coverage_preflight IS NULL OR r.coverage_preflight='null'::jsonb OR
               (f.report_type='wechat_channels_settlement' AND r.coverage_preflight->'items'='[]'::jsonb)
               OR r.status='failed')
          AND (r.coverage_result IS NULL OR r.coverage_result='null'::jsonb)''', (batches,))
    return sorted(int(r['batch_id']) for r in cursor.fetchall())


def preview(cursor, run, tasks, storage_root, *, unselected_only=False):
    mode = run.get('import_mode', 'fill_gaps')
    if mode not in MODES:
        raise ValueError('import_mode必须为fill_gaps、replace_range或refresh_only')
    if mode == 'refresh_only' and any(t['status']!='duplicate' or not t.get('batch_id') for t in tasks):
        raise ValueError('仅刷新必须复用已成功入库的文件，不接收新的原始数据')
    cursor.execute('SELECT COALESCE(MAX(selection_id),0) AS revision FROM common.ingest_source_day_selection')
    revision = cursor.fetchone()['revision']
    legacy_batches = legacy_unselected_batches(cursor, tasks)
    items, seen = [], set()
    for task in tasks:
        report = task['report_type']
        if report not in SUPPORTED:
            if mode == 'replace_range':
                spec=REPORT_BY_TYPE[report]
                raise ValueError(f'{spec.platform_name}{spec.report_name}暂不支持范围替换，请单独提交支持范围替换的报表')
            continue
        claim = normalize_claim(task.get('coverage'))
        if claim.get('artifact_id'):
            cursor.execute('''SELECT a.file_hash,a.business_date_start,a.business_date_end,a.coverage_verified,
                s.platform_code,s.shop_code,s.business_date_start AS request_start,s.business_date_end AS request_end
                FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id)
                WHERE a.artifact_id=%s''',(claim['artifact_id'],))
            receipt = cursor.fetchone()
            if not receipt or not receipt['coverage_verified'] or receipt['file_hash'] != task['file_hash'] or receipt['platform_code'] != task['resolved_platform_code'] or receipt['shop_code'] != task['resolved_shop_code'] or str(receipt['business_date_start']) != claim.get('start') or str(receipt['business_date_end']) != claim.get('end') or receipt['business_date_start'] != receipt['request_start'] or receipt['business_date_end'] != receipt['request_end']:
                raise ValueError('覆盖回执未验证或与文件、店铺、完整查询范围不一致')
        if mode == 'replace_range' and run['source'] != 'manual':
            raise ValueError('自动化不得替换已有来源；差异须由人工核对后提交')
        columns, rows = load_file(task, storage_root)
        if report=='wechat_channels_settlement':
            flow_ids=[canonical(row.get('流水单号')) for row in rows]
            if any(not value or value=='-' for value in flow_ids) or len(set(flow_ids))!=len(flow_ids):
                raise ValueError('视频号文件内流水单号缺失或重复，请核对原始文件；不会按金额或订单号删减流水')
        table, date_field, amount_column = SUPPORTED[report]
        new = defaultdict(list)
        for row in rows:
            new[business_day(row.get(date_field))].append(row)
        bounds = (claim['start'],claim['end']) if claim.get('start') else (min(new),max(new)) if new else None
        if not bounds:
            raise ValueError('零行文件必须明确填写完整查询范围，不能把未知覆盖视为零交易')
        old = effective_old_rows(cursor, task, columns, legacy_batches, bounds=bounds)
        choices = day_choices(cursor, task, bounds)
        days = compare_days(new, old, columns, mode=mode, claim=claim, amount_column=amount_column,choices=choices)
        if unselected_only:
            days = [d for d in days if d['old_selection_id'] is None]
            if not days:
                continue
        for day in days:
            identity = task['shop_identity_key'], table, day['date']
            if identity in seen:
                raise ValueError(f'同一会话同店铺同报表日期重复：{identity}；请分开提交或合并为一份完整导出')
            seen.add(identity)
        items.append({'file_task_id': str(task['file_task_id']), 'file_hash': task['file_hash'],
            'report_type': report, 'shop_identity_key': task['shop_identity_key'], 'target_table': table,
            'shop_name':task['resolved_shop_name'], 'platform_name':task['resolved_platform_name'],
            'report_name':REPORT_BY_TYPE[report].report_name,
            'coverage': claim, 'days': days, 'rows': len(rows)})
    counts = Counter(d['status'] for item in items for d in item['days'])
    report = {'mode': mode, 'selection_revision': revision, 'items': items,
              'summary': dict(counts), 'blocked': any(d['blocked'] for item in items for d in item['days'])}
    if legacy_batches:
        report['baseline_excluded_batches'] = legacy_batches
    # Token binds the exact file, declared intent, old/new content and active
    # source version. File bytes and current data are compared again on complete.
    report['token'] = hashlib.sha256(json.dumps({k:v for k,v in report.items() if k!='selection_revision'}, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return report


def public_preview(report):
    result = json.loads(json.dumps(report))
    for item in result['items']:
        for day in item['days']:
            day.pop('new_digest', None)
            day.pop('old_digest', None)
    result['message'] = ('有差异需要核对，请查看标记的店铺和日期。' if result['blocked'] else
        '核对通过；提交后将使用本次来源替换所选范围。' if result['mode']=='replace_range' else
        '核对通过；仅补入缺失日期，已有来源保持不变。')
    return result


def activate(cursor, run, tasks, storage_root):
    """Validate again and append decisions atomically with refresh creation."""
    approved = run.get('coverage_preflight')
    # Uploaded rows now also exist in ODS. The accepted preflight is the before
    # image; check for concurrent decisions, then compare excluding own batches.
    if approved is None or not approved['items']:
        return None
    if approved['blocked']:
        raise CoverageConflict('来源比较仍有内容差异，不能采信或刷新')
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('ingest-source-selection'))")
    by_id = {str(t['file_task_id']): t for t in tasks}
    own_batches = {int(t['batch_id']) for t in tasks if t['status']=='success' and t.get('batch_id')}
    own_batches.update(int(b) for b in approved.get('baseline_excluded_batches', []))
    selected = 0
    for item in approved['items']:
        task = by_id[item['file_task_id']]
        columns, rows = load_file(task, storage_root)
        if len(rows) != item['rows']:
            raise CoverageConflict('文件行数与预检不一致')
        batch = task.get('batch_id')
        if batch is None:
            raise CoverageConflict('重复文件尚未绑定成功ODS批次，不能切换来源')
        cursor.execute('''SELECT l.parsed_rows,l.failed_rows,c.shop_identity_key,c.ingest_status,c.shop_mapping_status,c.company_code
            FROM ods.ods_file_ingest_log l JOIN common.v_ingest_batch_shop_context c USING(batch_id)
            WHERE l.batch_id=%s AND l.file_hash=%s AND l.target_table=%s''',
            (batch, item['file_hash'], item['target_table']))
        states = cursor.fetchall()
        state = states[0] if len(states)==1 else None
        if not state or not state['company_code'] or state['parsed_rows'] != len(rows) or state['failed_rows'] or state['shop_identity_key'] != task['shop_identity_key'] or state['ingest_status'] != 'success' or state['shop_mapping_status'] != 'mapped':
            raise CoverageConflict('采信批次未完整入库、文件身份不符或店铺映射异常')
        bounds = (item['days'][0]['date'],item['days'][-1]['date'])
        old = effective_old_rows(cursor, task, columns, own_batches,bounds=bounds)
        choices = day_choices(cursor,task,bounds)
        date_field = SUPPORTED[task['report_type']][1]
        cursor.execute(sql.SQL('SELECT * FROM ods.{} WHERE batch_id=%s').format(sql.Identifier(item['target_table'])), (batch,))
        actual = defaultdict(list)
        for row in cursor.fetchall():
            actual[business_day(row[date_field])].append(dict(row))
        for day in item['days']:
            current_choice = choices.get(day['date'])
            if (current_choice['selection_id'] if current_choice else None) != day['old_selection_id']:
                raise CoverageConflict(f"{day['date']}采信版本已变化，请重新预检；ODS已保留，未切换来源")
            if fingerprint_rows(old.get(day['date'], []), columns) != day['old_digest']:
                raise CoverageConflict(f"{day['date']}既有来源在预检后变化，请重新预检；尚未切换来源")
            if fingerprint_rows(actual.get(day['date'], []), columns) != day['new_digest']:
                raise CoverageConflict(f"{day['date']}文件与ODS业务字段或重复行数量不一致，停止采信")
            keep = approved['mode'] in ('fill_gaps', 'refresh_only') and day['status'] in ('same','different','empty_new')
            batches = day['old_batches'] if keep else [int(batch)]
            if not keep and day['new_rows'] == 0:
                batches = []
            cursor.execute('''INSERT INTO common.ingest_source_day_selection(
                platform_code,shop_identity_key,target_table,stat_date,batch_ids,ingest_run_id,selection_mode,evidence,operator)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(ingest_run_id,shop_identity_key,target_table,stat_date) DO NOTHING''',
                (task['resolved_platform_code'],task['shop_identity_key'],item['target_table'],day['date'],batches,
                 str(run['run_id']), 'replace_range' if approved['mode']=='replace_range' else 'fill_gaps',
                 Json({'file_hash': item['file_hash'], 'coverage': item['coverage'], 'comparison': day['status'],
                       'old_batches': day['old_batches'], 'preflight_token': approved['token']}),run['operator']))
            selected += cursor.rowcount
    return {'selected_days': selected, 'summary': approved['summary'], 'mode': approved['mode'],
            'message': 'ODS原始批次保留，来源采信已完成；指标刷新状态请查看关联ETL运行。'}


def recover_legacy_ingest(cursor, run_id, storage_root, operator):
    """Latest retry can safely adopt legacy files when every overlap is equal.

    Only content dates are considered; no filename/range/zero-day inference.
    An existing explicit choice always wins. Any differing day rolls back the
    whole adoption and no retry is queued. The caller owns the transaction.
    """
    if not run_id:
        return None
    cursor.execute('SELECT * FROM ops.ingest_run WHERE run_id=%s FOR UPDATE', (str(run_id),))
    run = cursor.fetchone()
    if not run or run['status'] != 'success' or run.get('coverage_result') is not None:
        return None
    if run.get('coverage_preflight') is not None and run['coverage_preflight'].get('items'):
        return None
    if run.get('import_mode', 'fill_gaps') != 'fill_gaps':
        return None
    cursor.execute('SELECT * FROM ops.ingest_file_task WHERE run_id=%s ORDER BY created_at', (str(run_id),))
    tasks = [dict(r) for r in cursor.fetchall()]
    if not tasks or len(tasks) != run['expected_file_count'] or any(
            t['status'] not in ('success','duplicate') or not t.get('batch_id') for t in tasks):
        raise CoverageConflict('原导入文件尚未全部完整入库，不能自动恢复采信')
    # Recover accepted historical uploads without ever replacing a changed day.
    # JD keeps its existing document/wallet reconciliation retry semantics.
    tasks = [t for t in tasks if t['report_type'] in ('douyin_fund','douyin_settlement','wechat_channels_settlement')]
    if not tasks:
        return None
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext('ingest-source-selection'))")
    report = preview(cursor, run, tasks, storage_root, unselected_only=True)
    if not report['items']:
        return None
    if report['blocked']:
        conflicts = [f"{item['shop_name']} {d['date']}" for item in report['items']
                     for d in item['days'] if d['blocked']]
        raise CoverageConflict('历史文件与既有来源内容不同，未自动覆盖、未创建重试。请在原导入会话复用文件并核对采信范围：'
                               + '；'.join(conflicts[:5]))
    result = activate(cursor, {**run, 'operator':operator, 'coverage_preflight':report}, tasks, storage_root)
    result['recovered_on_retry'] = True
    cursor.execute('''UPDATE ops.ingest_run SET coverage_preflight=%s,coverage_result=%s,updated_at=NOW()
        WHERE run_id=%s''', (Json(report),Json(result),str(run_id)))
    return result
