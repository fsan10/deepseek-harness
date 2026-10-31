"""Freeze an import's business scope once, shared by every dependent ETL node."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from psycopg2 import sql
from psycopg2.extras import Json

from etl.common.refresh_runtime import SOURCE_DATES, ORDER_PAYMENT_FIELDS, PLATFORMS, next_month


def _months(start, end):
    current = start.replace(day=1)
    while current <= end:
        yield current.isoformat()
        current = next_month(current)


def _row(row, names):
    return row if isinstance(row, dict) else dict(zip(names, row))


def freeze_readiness(cursor, context):
    from etl.common.source_coverage import freeze_jd_fund_coverage
    context['as_of_date'] = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    context['fund_coverage'] = freeze_jd_fund_coverage(cursor,context)
    return context


def build_refresh_context(cursor, run: dict) -> dict:
    """No filename inference, date watermark, or silent full-refresh fallback."""
    if run['trigger_type'] == 'manual':
        return {'version': 1, 'mode': 'full', 'trigger_type': 'manual'}
    if run.get('scope') == 'all':
        raise ValueError('全量刷新只能由人工创建')
    context = {'version': 1, 'mode': 'incremental', 'trigger_type': run['trigger_type'],
               'months': {}, 'shops': {}, 'batch_ids': []}
    cursor.execute('''SELECT COALESCE(MAX(batch_id) FILTER(WHERE ingest_status='success'),0) AS cutoff,
        COALESCE(ARRAY_AGG(batch_id) FILTER(WHERE ingest_status<>'success'),ARRAY[]::bigint[]) AS excluded
        FROM ods.ods_file_ingest_log''')
    item = _row(cursor.fetchone(), ('cutoff', 'excluded'))
    context['batch_cutoff'] = int(item['cutoff'])
    cursor.execute("SELECT to_regclass('common.ingest_source_day_selection') AS relation")
    relation = cursor.fetchone()
    if (relation['relation'] if isinstance(relation,dict) else relation[0]):
        cursor.execute('SELECT COALESCE(MAX(selection_id),0) AS revision FROM common.ingest_source_day_selection')
        revision = cursor.fetchone()
        context['source_selection_cutoff'] = int(revision['revision'] if isinstance(revision,dict) else revision[0])
    # A parallel loader can finish an older batch after a newer one. The
    # high-water mark alone would let that late completion enter later nodes.
    context['excluded_batch_ids'] = sorted(int(b) for b in item['excluded'] if b <= context['batch_cutoff'])
    if not run.get('ingest_run_id'):
        # Configuration edits may affect historical periods, but still only the
        # named platforms. Bank submission keeps its separately controlled path.
        keys = run.get('requested_etls') or []
        platforms = {p for p in PLATFORMS if any(k.startswith(p + '_') for k in keys)}
        if not platforms:
            raise ValueError('自动刷新缺少明确平台和导入上下文，禁止执行全量')
        for platform in platforms:
            cursor.execute(sql.SQL('SELECT MIN(stat_date) AS low,MAX(stat_date) AS high FROM dws.{}').format(
                sql.Identifier(f'dws_{platform}_operating_flow_shop_daily_scene')))
            bounds = cursor.fetchone()
            bounds = _row(bounds, ('low', 'high'))
            if bounds['low']:
                context['months'][platform] = list(_months(bounds['low'], bounds['high']))
        return freeze_readiness(cursor,context)
    cursor.execute('''SELECT DISTINCT l.batch_id,l.platform_code,l.shop_code,l.target_table,
            l.report_period_start,l.report_period_end,l.parsed_rows,
            c.shop_identity_key,c.company_code,c.shop_mapping_status,c.ingest_status
        FROM ops.ingest_file_task t
        LEFT JOIN ops.ingest_file_task_batch tb ON tb.file_task_id=t.file_task_id
        JOIN ods.ods_file_ingest_log l ON l.batch_id=COALESCE(tb.batch_id,t.batch_id)
        LEFT JOIN common.v_ingest_batch_shop_context c ON c.batch_id=l.batch_id
            AND c.target_table=l.target_table AND c.platform_code=l.platform_code
        WHERE t.run_id=%s AND t.status IN ('success','duplicate') ORDER BY l.batch_id''', (str(run['ingest_run_id']),))
    names = [d[0] for d in cursor.description]
    batches = [_row(r, names) for r in cursor.fetchall()]
    by_batch = {}
    for batch in batches:
        batch_id = int(batch['batch_id'])
        if batch_id in by_batch:
            raise ValueError(f'批次{batch_id}店铺映射冲突，停止生成增量范围')
        if batch['shop_mapping_status'] != 'mapped' or batch['ingest_status'] != 'success' or not all(batch[k] for k in ('shop_code', 'shop_identity_key', 'company_code')):
            raise ValueError(f'批次{batch_id}未成功或店铺公司未映射，停止刷新')
        by_batch[batch_id] = batch
    for batch_id, batch in by_batch.items():
        platform, table = batch['platform_code'], batch['target_table']
        expression = SOURCE_DATES.get(table)
        if expression is None:
            raise ValueError(f'{table}尚未定义增量业务日期，禁止回退全量')
        expressions = [expression]
        if table.endswith('_order_raw') and platform in ORDER_PAYMENT_FIELDS:
            field = sql.Identifier(ORDER_PAYMENT_FIELDS[platform]).as_string(cursor.connection)
            expressions.append(f"NULLIF(NULLIF(BTRIM({field}),''),'-')::timestamp::date")
        months = set()
        for expression in expressions:
            cursor.execute(sql.SQL(f'SELECT MIN({expression}) AS low,MAX({expression}) AS high FROM ods.{{}} WHERE batch_id=%s').format(sql.Identifier(table)), (batch_id,))
            bounds = _row(cursor.fetchone(), ('low', 'high'))
            if bounds['low']:
                months.update(_months(bounds['low'], bounds['high']))
        if batch['report_period_start'] and batch['report_period_end']:
            months.update(_months(batch['report_period_start'], batch['report_period_end']))
        cursor.execute('SELECT coverage FROM ops.ingest_file_task WHERE run_id=%s AND batch_id=%s',
                       (str(run['ingest_run_id']),batch_id))
        for row in cursor.fetchall():
            claim = row['coverage'] if isinstance(row,dict) else row[0]
            if claim and claim.get('start') and claim.get('end'):
                months.update(_months(date.fromisoformat(claim['start']), date.fromisoformat(claim['end'])))
        # A trusted receipt includes zero-transaction days and may arrive
        # before prepare_settlement_sources registers the coverage metadata.
        cursor.execute('''SELECT a.business_date_start,a.business_date_end
            FROM ops.automation_artifact a
            JOIN ops.automation_step_run s ON s.step_run_id=a.step_run_id
            JOIN ods.ods_file_ingest_log l ON l.batch_id=%s AND l.file_hash=a.file_hash
            WHERE a.coverage_verified AND s.platform_code=l.platform_code AND s.shop_code=l.shop_code
              AND a.business_date_start IS NOT NULL AND a.business_date_end IS NOT NULL
              AND s.business_date_start=a.business_date_start AND s.business_date_end=a.business_date_end''', (batch_id,))
        for receipt in cursor.fetchall():
            receipt = _row(receipt, ('business_date_start', 'business_date_end'))
            months.update(_months(receipt['business_date_start'], receipt['business_date_end']))
        # Verified coverage also handles a successful zero-row replacement.
        cursor.execute("SELECT to_regclass('common.settlement_source_registry') AS relation")
        exists = cursor.fetchone()
        if (exists['relation'] if isinstance(exists, dict) else exists[0]):
            cursor.execute('SELECT period_start,period_end FROM common.settlement_source_registry WHERE batch_id=%s', (batch_id,))
            coverage = cursor.fetchone()
            if coverage:
                coverage = _row(coverage, ('period_start', 'period_end'))
                months.update(_months(coverage['period_start'], coverage['period_end']))
        if table.endswith('_order_raw'):
            months.update(_previous_order_months(cursor, batch))
        if not months:
            raise ValueError(f'批次{batch_id}无法确定已验证的业务日期范围（含零行文件），停止刷新')
        if months:
            context['months'][platform] = sorted(set(context['months'].get(platform, [])) | months)
            context['shops'][platform] = sorted(set(context['shops'].get(platform, [])) | {batch['shop_code']})
        context['batch_ids'].append(batch_id)
    return freeze_readiness(cursor,context)


def _previous_order_months(cursor, batch):
    """A changed/removed order line must invalidate its OLD business month too."""
    platform = batch['platform_code']
    raw_key = '主订单编号' if platform in ('douyin', 'tmall') else '订单号'
    cursor.execute('''SELECT table_name,ARRAY_AGG(column_name::text) AS columns
        FROM information_schema.columns WHERE table_schema='dwd'
        AND table_name LIKE %s GROUP BY table_name''', (f'dwd_{platform}_%',))
    tables = [_row(r, ('table_name', 'columns')) for r in cursor.fetchall()]
    months = set()
    for item in tables:
        columns = set(item['columns'])
        key = next((k for k in ('main_order_no', 'order_no', 'sub_order_no') if k in columns), None)
        if not key or 'stat_date' not in columns or 'shop_code' not in columns:
            continue
        cursor.execute(sql.SQL('''SELECT DISTINCT DATE_TRUNC('month',d.stat_date)::date AS month
            FROM dwd.{} d WHERE d.shop_code=%s AND EXISTS (
                SELECT 1 FROM ods.{} r WHERE r.batch_id=%s
                AND NULLIF(BTRIM(r.{}), '')=d.{})''').format(
                    sql.Identifier(item['table_name']), sql.Identifier(batch['target_table']),
                    sql.Identifier(raw_key), sql.Identifier(key)), (batch['shop_code'], batch['batch_id']))
        for row in cursor.fetchall():
            month = row['month'] if isinstance(row, dict) else row[0]
            if month:
                months.add(month.isoformat())
    return months


def ensure_refresh_context(service, run_id) -> dict:
    with service.transaction() as cursor:
        cursor.execute('SELECT * FROM ops.etl_run WHERE etl_run_id=%s FOR UPDATE', (str(run_id),))
        run = dict(cursor.fetchone())
        if run.get('refresh_context') is not None:
            return run['refresh_context']
        context = build_refresh_context(cursor, run)
        cursor.execute('UPDATE ops.etl_run SET refresh_context=%s,updated_at=NOW() WHERE etl_run_id=%s',
                       (Json(context), str(run_id)))
        return context


def retry_refresh_context(cursor, parent: dict, *, replay: bool = False) -> dict:
    """Freeze new sources for precisely the original affected shops/months."""
    import copy
    context = copy.deepcopy(parent.get('refresh_context') or build_refresh_context(cursor, parent))
    if context.get('mode') == 'full':
        # A retry must not silently turn into a new automatic full refresh.
        raise ValueError('全量运行请明确重新创建人工刷新；节点重试只支持有范围的增量运行')
    if replay:
        return context
    if not context.get('months') or not context.get('shops'):
        raise ValueError('原运行缺少明确业务月份或店铺，不能自动扩展重试范围')
    cursor.execute('''SELECT COALESCE(MAX(batch_id) FILTER(WHERE ingest_status='success'),0) AS cutoff,
        COALESCE(ARRAY_AGG(batch_id) FILTER(WHERE ingest_status<>'success'),ARRAY[]::bigint[]) AS excluded
        FROM ods.ods_file_ingest_log''')
    row = _row(cursor.fetchone(), ('cutoff','excluded'))
    context['batch_cutoff'] = int(row['cutoff'])
    context['excluded_batch_ids'] = sorted(int(b) for b in row['excluded'] if b <= context['batch_cutoff'])
    cursor.execute('SELECT COALESCE(MAX(selection_id),0) AS revision FROM common.ingest_source_day_selection')
    context['source_selection_cutoff'] = int(_row(cursor.fetchone(),('revision',))['revision'])
    return freeze_readiness(cursor,context)
