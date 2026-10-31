"""Bounded refreshes using the existing, registered metric SQL and validations.

Only the isolated ETL child installs this connection factory. ODS is never
written here. Source snapshots are transaction-local; refresh INSERTs retain
their original formulas and replace only the requested platform/shop/months.
Unknown write shapes fail closed instead of falling back to a full refresh.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date

from psycopg2 import extensions, sql


IDENT = r'(?:"[a-z_][a-z_0-9]*"|[a-z_][a-z_0-9]*)'
RELATION = rf'({IDENT})\s*\.\s*({IDENT})'
READ_RELATION = re.compile(rf'\b(FROM|JOIN)\s+{RELATION}', re.I)
DERIVED = {'dwd', 'dws', 'ads'}
PLATFORMS = ('douyin', 'jd', 'ks', 'pdd', 'tmall', 'wechat_channels', 'xhs')

# Business dates come from source fields, never an archive filename.
SOURCE_DATES = {
    'ods_douyin_order_raw': 'NULLIF(BTRIM("订单提交时间"),\'\')::timestamp::date',
    'ods_douyin_fund_raw': 'NULLIF(BTRIM("动账时间"),\'\')::timestamp::date',
    'ods_douyin_settlement_raw': 'NULLIF(NULLIF(BTRIM("结算时间"),\'\'),\'-\')::timestamp::date',
    'ods_ks_order_raw': 'NULLIF(BTRIM("订单创建时间"),\'\')::timestamp::date',
    'ods_ks_fund_raw': 'NULLIF(BTRIM("入账时间"),\'\')::timestamp::date',
    'ods_ks_settlement_raw': 'NULLIF(NULLIF(BTRIM("实际结算时间"),\'\'),\'-\')::timestamp::date',
    'ods_jd_order_raw': 'NULLIF(BTRIM("下单时间"),\'\')::timestamp::date',
    'ods_jd_fund_raw': 'NULLIF(BTRIM("入账时间"),\'\')::timestamp::date',
    'ods_jd_settlement_raw': 'NULLIF(BTRIM("账单日期"),\'\')::date',
    'ods_tmall_order_raw': 'NULLIF(BTRIM("订单创建时间"),\'\')::timestamp::date',
    'ods_tmall_aggregate_fund_raw': 'TO_DATE(BTRIM("入帐日期"),\'YYYYMMDD\')',
    'ods_tmall_alipay_fund_raw': 'NULLIF(BTRIM("发生时间"),\'\')::timestamp::date',
    'ods_tmall_settlement_income_raw': 'TO_DATE(BTRIM("账期"),\'YYYYMMDD\')',
    'ods_tmall_settlement_expense_raw': 'TO_DATE(BTRIM("账期"),\'YYYYMMDD\')',
    # The established PDD order pipelines retain unpaid/cancelled orders and
    # use the validated order-number date when deal time is absent.
    'ods_pdd_order_raw': 'COALESCE(NULLIF(NULLIF(BTRIM("订单成交时间"),\'\'),\'-\')::timestamp::date, TO_DATE(\'20\'||LEFT(BTRIM("订单号"),6),\'YYYYMMDD\'))',
    'ods_pdd_settlement_raw': 'NULLIF(BTRIM("发生时间"),\'\')::timestamp::date',
    'ods_wechat_channels_order_raw': 'NULLIF(BTRIM("订单下单时间"),\'\')::timestamp::date',
    'ods_wechat_channels_settlement_raw': 'NULLIF(BTRIM("记账时间"),\'\')::timestamp::date',
    'ods_xhs_order_raw': 'NULLIF(BTRIM("订单创建时间"),\'\')::timestamp::date',
    'ods_xhs_settlement_income_raw': 'NULLIF(BTRIM("结算时间"),\'\')::timestamp::date',
    'ods_xhs_settlement_expense_raw': 'NULLIF(BTRIM("结算时间"),\'\')::timestamp::date',
    'ods_douyin_qianchuan_finance_raw': 'NULLIF(BTRIM("日期"),\'\')::date',
    'ods_pdd_promotion_expense_raw': 'LEFT(BTRIM("时间"),10)::date',
    'ods_jd_tong_promotion_expense_raw': 'LEFT(BTRIM("结算时间"),10)::date',
    'ods_jd_union_promotion_expense_raw': 'LEFT(BTRIM("结算时间"),10)::date',
    'ods_tmall_taobao_union_promotion_expense_raw': 'TO_DATE(REPLACE(BTRIM("日期"),E\'\\t\',\'\'),\'YYYYMMDD\')',
    'ods_tmall_wanxiangtai_promotion_expense_raw': 'LEFT(BTRIM("记账时间"),10)::date',
}
ORDER_PAYMENT_FIELDS = {
    'douyin': '支付完成时间', 'ks': '订单支付时间', 'jd': '付款确认时间',
    'tmall': '订单付款时间', 'xhs': '支付时间', 'wechat_channels': '支付时间',
}
SOURCE_DATES = {key: value.replace('NULLIF(BTRIM(', 'NULLIF(NULLIF(BTRIM(').replace('),\'\')::timestamp', '),\'\'),\'-\')::timestamp')
                if "NULLIF(NULLIF" not in value and '::timestamp' in value else value
                for key, value in SOURCE_DATES.items()}


def next_month(value: date, offset: int = 1) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def sql_mask(text: str) -> str:
    """Blank quoted/comment bodies while retaining offsets and parentheses."""
    result = list(text)
    pattern = re.compile(r"--[^\n]*|/\*[\s\S]*?\*/|\$[a-zA-Z_0-9]*\$|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"")
    position = 0
    while match := pattern.search(text, position):
        end = match.end()
        if match.group().startswith('$'):
            closing = text.find(match.group(), end)
            if closing < 0:
                raise ValueError('SQL dollar quote is not closed')
            end = closing + len(match.group())
        for index in range(match.start(), end):
            if result[index] != '\n':
                result[index] = ' '
        position = end
    return ''.join(result)


def split_statements(text: str) -> list[str]:
    mask = sql_mask(text)
    boundaries = [-1, *(m.start() for m in re.finditer(';', mask)), len(text)]
    statements = []
    for a, b in zip(boundaries, boundaries[1:]):
        first = re.search(r'\S', mask[a + 1:b])
        if first:
            statements.append(text[a + 1 + first.start():b].strip())
    return statements


def unquote(value: str) -> str:
    return value.strip('"').lower()


def fixed_platform(table: str) -> str | None:
    return next((p for p in PLATFORMS if table.startswith((f'ods_{p}_', f'dwd_{p}_', f'dws_{p}_', f'v_current_{p}_'))), None)


@dataclass(frozen=True)
class RefreshScope:
    context: dict

    def __post_init__(self):
        if self.context.get('mode') not in ('incremental', 'full'):
            raise ValueError('刷新模式缺失或无效；禁止自动回退全量')
        if self.context.get('version') != 1:
            raise ValueError('不支持的刷新范围版本')
        if self.full and self.context.get('trigger_type') != 'manual':
            raise ValueError('全量刷新只能由人工创建')
        for platform, values in self.context.get('months', {}).items():
            if platform not in PLATFORMS:
                raise ValueError(f'无效刷新平台：{platform}')
            for value in values:
                parsed = date.fromisoformat(value)
                if parsed.day != 1:
                    raise ValueError('刷新月份必须是自然月首日')

    @property
    def full(self) -> bool:
        return self.context['mode'] == 'full'

    @property
    def platforms(self) -> set[str]:
        return set(self.context.get('months', {}))

    def predicate(self, connection, table: str, columns: set[str], *, alias: str = '',
                  read: bool = False, monthly_dependency: bool = False,
                  all_platforms: bool = False, all_shops: bool = False,
                  date_expression: str | None = None) -> str:
        if self.full:
            return 'TRUE'
        prefix = sql.Identifier(alias).as_string(connection) + '.' if alias else ''
        date_column = next((c for c in ('stat_date', 'expense_date', 'business_date', 'stat_month', 'budget_month') if c in columns), None)
        if date_expression is None and date_column is None:
            raise ValueError(f'{table}没有受支持的业务日期，禁止无范围刷新')
        expression = date_expression or prefix + sql.Identifier(date_column).as_string(connection)
        monthly = date_column in ('stat_month', 'budget_month')
        platform_fixed = fixed_platform(table)
        conditions = []
        groups = self.context.get('months', {})
        if all_platforms:
            groups = {'*': sorted({m for values in groups.values() for m in values})}
        elif table in ('ads_promotion_expense_company_shop_daily',
                       'ads_gsv_promotion_expense_company_shop_monthly',
                       'ads_platform_bank_total_revenue_company_daily_type'):
            # Its calendar also owns zero rows for these three platforms. A
            # new real-platform date must replace those dependent rows too.
            months = sorted({m for p, values in groups.items()
                             if p in ('douyin', 'jd', 'pdd', 'tmall') for m in values})
            if months:
                groups = {**groups, **{p: sorted(set(groups.get(p, [])) | set(months))
                                      for p in ('ks', 'wechat_channels', 'xhs')}}
        for platform, months in groups.items():
            if platform_fixed and platform != '*' and platform_fixed != platform:
                continue
            values = {date.fromisoformat(value) for value in months}
            if monthly_dependency:
                # M changes M+1's previous-month value; its query also reads M-1.
                values |= {next_month(m) for m in list(values)}
                if read:
                    values |= {next_month(m, -1) for m in list(values)}
            periods = []
            for month in sorted(values):
                low = sql.Literal(month).as_string(connection)
                high = sql.Literal(next_month(month)).as_string(connection)
                periods.append(f'{expression}={low}' if monthly else f'({expression}>={low} AND {expression}<{high})')
            if not periods:
                continue
            dates = '(' + ' OR '.join(periods) + ')'
            if table == 'dwd_pdd_gsv_order_detail' and platform == 'pdd' and date_column == 'stat_date':
                # An unpaid order can become dated in a later export. Its old
                # NULL-date version is outside a normal month DELETE, but its
                # identity belongs to the current frozen replacement scope.
                source = connection.read_view('common', 'v_current_pdd_order_raw', ('dwd', table))
                context = connection.source('common', 'v_ingest_batch_shop_context')
                outer = prefix or sql.Identifier(table).as_string(connection) + '.'
                dates = f'''({dates} OR ({expression} IS NULL AND EXISTS (
                    SELECT 1 FROM {source} r JOIN {context} c ON c.batch_id=r.batch_id
                    WHERE c.platform_code='pdd' AND c.target_table='ods_pdd_order_raw'
                      AND c.shop_code={outer}"shop_code"
                      AND NULLIF(BTRIM(r."订单号"),'')={outer}"order_no")))'''
            parts = [dates]
            if platform != '*' and 'platform_code' in columns:
                parts.append(f'{prefix}"platform_code"={sql.Literal(platform).as_string(connection)}')
            shops = self.context.get('shops', {}).get(platform, [])
            if shops and not all_shops and not all_platforms and 'shop_code' in columns:
                parts.append(f'{prefix}"shop_code"=ANY({sql.Literal(shops).as_string(connection)}::text[])')
            conditions.append('(' + ' AND '.join(parts) + ')')
        return '(' + ' OR '.join(conditions) + ')' if conditions else 'FALSE'


class RefreshConnection(extensions.connection):
    """One immutable source snapshot and one metric transaction per connection."""

    refresh_context: dict

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refresh_scope = RefreshScope(self.refresh_context)
        self.source_cache = {}
        self.read_views = {}
        self.column_cache = {}
        self.refresh_events = []
        self.prepared_sources = set()
        self.selection_configured = False
        self.set_session(isolation_level='REPEATABLE READ')

    def raw_cursor(self):
        return super().cursor()

    def cursor(self, *args, **kwargs):
        self.configure_selection_snapshot()
        requested = kwargs.get('cursor_factory')
        if requested is None or requested is extensions.cursor:
            kwargs['cursor_factory'] = RefreshCursor
        elif not issubclass(requested, RefreshCursor):
            # Validation helpers sometimes request a RealDictCursor. They must
            # observe the identical frozen sources, not bypass the runtime.
            kwargs['cursor_factory'] = type('Refresh' + requested.__name__, (RefreshCursor, requested), {})
        return super().cursor(*args, **kwargs)

    def configure_selection_snapshot(self):
        if not self.selection_configured:
            with self.raw_cursor() as cur:
                cur.execute("SELECT set_config('mock_coffice.source_selection_cutoff',%s,TRUE)",
                            (str(self.refresh_scope.context.get('source_selection_cutoff',0)),))
            self.selection_configured = True

    def columns(self, schema, table):
        key = (schema, table)
        if key not in self.column_cache:
            with self.raw_cursor() as cur:
                cur.execute('SELECT attname FROM pg_attribute WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped', (f'{schema}.{table}',))
                names = {r[0] for r in cur.fetchall()}
            if not names:
                raise RuntimeError(f'刷新对象不存在：{schema}.{table}；请先执行数据库迁移')
            self.column_cache[key] = names
        return self.column_cache[key]

    def source(self, schema, table):
        key = (schema, table)
        if key in self.source_cache:
            return self.source_cache[key]
        name = '_src_' + hashlib.sha1(f'{schema}.{table}'.encode()).hexdigest()[:16]
        qualified = sql.Identifier('pg_temp', name).as_string(self)
        original = sql.Identifier(schema, table).as_string(self)
        started = time.perf_counter()
        with self.raw_cursor() as cur:
            columns = self.columns(schema, table)
            cutoff = int(self.refresh_scope.context.get('batch_cutoff', 0))
            predicate = f'batch_id<={cutoff}' if cutoff and 'batch_id' in columns else 'TRUE'
            excluded = self.refresh_scope.context.get('excluded_batch_ids', [])
            if excluded and 'batch_id' in columns:
                frozen_exclusions = sql.Literal([int(b) for b in excluded]).as_string(self)
                predicate += f' AND NOT (batch_id=ANY({frozen_exclusions}::bigint[]))'
            if schema == 'ods':
                cur.execute(f'CREATE TEMP VIEW {sql.Identifier(name).as_string(self)} AS SELECT * FROM {original} WHERE {predicate}')
            elif table == 'v_ingest_batch_shop_context':
                cur.execute(f'CREATE TEMP TABLE {sql.Identifier(name).as_string(self)} ON COMMIT DROP AS SELECT * FROM {original} WHERE {predicate}')
            else:
                cur.execute('SELECT pg_get_viewdef(to_regclass(%s),TRUE)', (f'{schema}.{table}',))
                definition = cur.fetchone()[0]
                if not definition:
                    raise RuntimeError(f'缺少来源视图定义：{schema}.{table}')
                definition = self.rewrite_sources(definition.rstrip(';'))
                cur.execute(f'CREATE TEMP TABLE {sql.Identifier(name).as_string(self)} ON COMMIT DROP AS {definition}')
            if schema != 'ods':
                if 'batch_id' in columns:
                    cur.execute(f'CREATE INDEX ON {qualified}(batch_id)')
                if 'id' in columns:
                    cur.execute(f'CREATE INDEX ON {qualified}(id)')
                cur.execute(f'ANALYZE {qualified}')
        self.source_cache[key] = qualified
        self.refresh_events.append({'source': f'{schema}.{table}', 'seconds': round(time.perf_counter() - started, 4)})
        return qualified

    def read_view(self, schema, table, target):
        target_columns = self.columns(*target)
        monthly_dependency = 'monthly_ranking' in target[1] or 'business_monthly' in target[1]
        all_platforms = 'platform_code' not in target_columns or target[1] in (
            'ads_promotion_expense_company_shop_daily', 'ads_gsv_promotion_expense_company_shop_monthly',
            'ads_platform_bank_total_revenue_company_daily_type')
        all_shops = 'shop_code' not in target_columns or monthly_dependency
        key = (schema, table, monthly_dependency, all_platforms, all_shops)
        if key in self.read_views:
            return self.read_views[key]
        columns = self.columns(schema, table)
        source = self.source(schema, table) if schema == 'ods' or schema == 'common' else sql.Identifier(schema, table).as_string(self)
        source_table = 'ods_' + re.sub(r'^v_(current|selected)_','',table) if table.startswith(('v_current_','v_selected_')) else table
        expression = SOURCE_DATES.get(source_table) if schema in ('ods', 'common') else None
        expressions = [expression]
        if source_table.endswith('_order_raw'):
            payment = ORDER_PAYMENT_FIELDS.get(fixed_platform(source_table))
            if payment and payment in columns:
                field = sql.Identifier(payment).as_string(self)
                expressions.append(f"NULLIF(NULLIF(BTRIM({field}),''),'-')::timestamp::date")
        predicate = '(' + ' OR '.join(self.refresh_scope.predicate(self, source_table, columns, read=True,
            monthly_dependency=monthly_dependency, all_platforms=all_platforms,
            all_shops=all_shops, date_expression=value) for value in expressions) + ')'
        name = '_read_' + hashlib.sha1(repr(key).encode()).hexdigest()[:16]
        with self.raw_cursor() as cur:
            cur.execute(f'CREATE TEMP VIEW {sql.Identifier(name).as_string(self)} AS SELECT * FROM {source} WHERE {predicate}')
        result = sql.Identifier('pg_temp', name).as_string(self)
        self.read_views[key] = result
        return result

    def rewrite_sources(self, text, target=None):
        def replace(match):
            schema, table = unquote(match[2]), unquote(match[3])
            source = schema == 'ods' and table.startswith('ods_')
            source |= schema == 'common' and (table.startswith(('v_current_', 'v_selected_', 'v_settlement_source_')) or table in ('v_ingest_batch_shop_context', 'v_effective_settlement_source','v_ingest_source_day_selection'))
            if target and (schema in DERIVED or source) and table != 'ods_file_ingest_log':
                # Source metadata has no business date and is never narrowed.
                if schema == 'common' and not table.startswith(('v_current_','v_selected_')):
                    result = self.source(schema, table)
                else:
                    result = self.read_view(schema, table, target)
            elif source:
                result = self.source(schema, table)
            else:
                return match.group()
            following = re.match(r'\s+(?:AS\s+)?([a-z_][a-z_0-9]*)', text[match.end():], re.I)
            reserved = {'where', 'join', 'left', 'right', 'inner', 'outer', 'full', 'cross', 'on', 'using',
                        'group', 'order', 'having', 'limit', 'union', 'offset', 'into', 'loop', 'end',
                        'set', 'for', 'window', 'except', 'intersect', 'returning'}
            if following is None or following[1].lower() in reserved:
                result += ' AS ' + sql.Identifier(table).as_string(self)
            return match[1] + ' ' + result
        return READ_RELATION.sub(replace, text)

    def invalidate_source_cache(self):
        """Trusted coverage registration changes metadata, never raw facts."""
        with self.raw_cursor() as cur:
            for relation in reversed(list(self.read_views.values())):
                cur.execute(f'DROP VIEW IF EXISTS {relation}')
            for (schema, _), relation in reversed(list(self.source_cache.items())):
                kind = 'VIEW' if schema == 'ods' else 'TABLE'
                cur.execute(f'DROP {kind} IF EXISTS {relation}')
        self.source_cache.clear()
        self.read_views.clear()
        self.prepared_sources.clear()

    def commit(self):
        # PostgreSQL keeps temporary views after commit. Remove the runtime's
        # views before their ON COMMIT DROP source tables, so a second metric
        # transaction can safely create a fresh snapshot on this connection.
        with self.raw_cursor() as cur:
            views = list(reversed(list(self.read_views.values()))) + [
                relation for (schema, _), relation in self.source_cache.items() if schema == 'ods'
            ]
            for relation in views:
                cur.execute(f'DROP VIEW IF EXISTS {relation}')
        super().commit()
        self.selection_configured = False
        print('[REFRESH_METRICS] ' + json.dumps({'mode': self.refresh_scope.context['mode'],
            'months': self.refresh_scope.context.get('months', {}), 'shops': self.refresh_scope.context.get('shops', {}),
            'events': self.refresh_events}, ensure_ascii=False), flush=True)
        self.source_cache.clear()
        self.read_views.clear()
        self.refresh_events.clear()
        self.prepared_sources.clear()

    def rollback(self):
        super().rollback()
        self.selection_configured = False
        self.source_cache.clear()
        self.read_views.clear()
        self.refresh_events.clear()
        self.prepared_sources.clear()


class RefreshCursor(extensions.cursor):
    incremental_runtime = True

    def execute(self, query, vars=None):
        # The same cursor can be reused after commit/rollback. SET LOCAL must be
        # restored for that new transaction as well as for newly opened cursors.
        self.connection.configure_selection_snapshot()
        if isinstance(query, sql.Composable):
            query = query.as_string(self.connection)
        if isinstance(query, bytes):
            query = query.decode('utf-8')
        statements = split_statements(query)
        if not self.connection.refresh_scope.full:
            truncated = [re.match(rf'\s*TRUNCATE(?:\s+TABLE)?\s+{RELATION}\s*$', s, re.I) for s in statements]
            platforms = [fixed_platform(unquote(m[2])) for m in truncated if m]
            if platforms and all(p is not None and p not in self.connection.refresh_scope.platforms for p in platforms):
                return super().execute('SELECT NULL WHERE FALSE')
        if statements:
            initial = re.search(r'\b[A-Z]+\b', sql_mask(statements[0]), re.I)
            if initial and initial.group().upper() in ('CREATE', 'ALTER', 'DROP') and not re.search(r'\bCREATE\s+(?:TEMP|TEMPORARY)\b', sql_mask(statements[0]), re.I):
                # A schema file may contain backfills and seed INSERTs after its
                # DDL. Skip the installation file as a whole, not just its DDL.
                return super().execute('SELECT NULL WHERE FALSE')
        if vars is not None and len(statements) != 1:
            raise ValueError('参数化刷新SQL必须只有一条语句')
        for statement in statements:
            self._execute_one(statement, vars)
        return None

    def _execute_one(self, statement, parameters):
        connection = self.connection
        scope = connection.refresh_scope
        mask = sql_mask(statement)
        first = re.search(r'\b[A-Z]+\b', mask, re.I)
        command = first.group().upper() if first else ''
        # Schema installation is a deployment operation, never file-import work.
        if command in ('CREATE', 'ALTER', 'DROP', 'COMMENT', 'GRANT', 'REVOKE'):
            if command == 'CREATE' and re.search(r'\bCREATE\s+(?:TEMP|TEMPORARY)\s+(?:TABLE|VIEW)\b', mask, re.I):
                return super().execute(connection.rewrite_sources(statement), parameters)
            return super().execute('SELECT NULL WHERE FALSE')
        if command == 'DO' and re.search(r'\b(?:ALTER TABLE|CREATE (?:OR REPLACE )?(?:TABLE|VIEW|FUNCTION|PROCEDURE)|DROP (?:TABLE|VIEW|FUNCTION|PROCEDURE))\b', statement, re.I):
            return super().execute('SELECT NULL WHERE FALSE')
        if command == 'DO':
            if re.search(r'\bTRUNCATE\b', statement, re.I):
                raise ValueError('不允许在匿名过程内进行无范围刷新')
            if re.search(r'\b(?:INSERT INTO|UPDATE|DELETE FROM)\s+(?:dwd|dws|ads)\.', statement, re.I) and 'ads_product_code_mapping_workbench' not in statement:
                raise ValueError('匿名过程中的指标写入必须显式支持增量范围')
            return super().execute(connection.rewrite_sources(statement), parameters)
        if re.match(r'\s*(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+ods\.', statement, re.I):
            raise ValueError('刷新运行时禁止修改ODS')
        truncate = re.match(rf'\s*TRUNCATE(?:\s+TABLE)?\s+{RELATION}\s*$', statement, re.I)
        if truncate:
            target = tuple(unquote(v) for v in truncate.groups())
            if target[0] not in DERIVED:
                raise ValueError('禁止刷新运行时清空ODS或配置表')
            if scope.full:
                return super().execute(statement, parameters)
            predicate = scope.predicate(connection, target[1], connection.columns(*target),
                monthly_dependency='monthly_ranking' in target[1] or 'business_monthly' in target[1],
                all_shops='monthly_ranking' in target[1] or 'business_monthly' in target[1])
            started = time.perf_counter()
            super().execute(f'DELETE FROM {sql.Identifier(*target).as_string(connection)} WHERE {predicate}')
            connection.refresh_events.append({'table': '.'.join(target), 'operation': 'delete', 'rows': self.rowcount, 'seconds': round(time.perf_counter() - started, 4)})
            return None
        if command == 'TRUNCATE':
            raise ValueError('不支持的TRUNCATE形态；禁止无范围刷新')
        if command == 'CALL' and 'refresh_operating_sales_product_allocation' in statement:
            return self._allocation(statement)
        insert = re.search(rf'\bINSERT\s+INTO\s+{RELATION}\s*\(([^)]*)\)\s*', statement, re.I)
        if insert and unquote(insert[1]) in DERIVED:
            target = (unquote(insert[1]), unquote(insert[2]))
            if scope.full:
                return super().execute(connection.rewrite_sources(statement), parameters)
            columns = [unquote(c.strip()) for c in insert[3].split(',')]
            if not all(re.fullmatch('[a-z_][a-z_0-9]*', c) for c in columns):
                raise ValueError('不支持的刷新INSERT列清单')
            body = statement[insert.end():].strip()
            if not re.match(r'(SELECT|WITH)\b', body, re.I):
                raise ValueError('增量刷新INSERT必须来自SELECT；禁止自动回退全量')
            predicate = scope.predicate(connection, target[1], set(columns), alias='_refresh',
                monthly_dependency='monthly_ranking' in target[1] or 'business_monthly' in target[1],
                all_shops='monthly_ranking' in target[1] or 'business_monthly' in target[1])
            if predicate == 'FALSE':
                return super().execute('SELECT NULL WHERE FALSE')
            prefix = connection.rewrite_sources(statement[:insert.start()], target)
            body = connection.rewrite_sources(body, target)
            names = sql.SQL(',').join(map(sql.Identifier, columns)).as_string(connection)
            rewritten = prefix + statement[insert.start():insert.end()] + f'SELECT _refresh.* FROM ({body}) AS _refresh({names}) WHERE {predicate}'
            started = time.perf_counter()
            super().execute(rewritten, parameters)
            connection.refresh_events.append({'table': '.'.join(target), 'operation': 'insert', 'rows': self.rowcount, 'seconds': round(time.perf_counter() - started, 4)})
            return None
        update = re.match(rf'\s*UPDATE\s+{RELATION}\s+(?:(?:AS\s+)?([a-z_][a-z_0-9]*)\s+)?SET\b', statement, re.I)
        if update and unquote(update[1]) in DERIVED and not scope.full:
            target = (unquote(update[1]), unquote(update[2]))
            predicate = scope.predicate(connection, target[1], connection.columns(*target), alias=update[3] or '')
            if re.search(r'\bRETURNING\b', mask, re.I):
                raise ValueError('不支持的增量UPDATE RETURNING')
            statement += (' AND ' if re.search(r'\bWHERE\b', mask, re.I) else ' WHERE ') + predicate
        elif not scope.full:
            write = re.search(rf'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO)\s+{RELATION}', statement, re.I)
            if write and unquote(write[1]) in DERIVED:
                raise ValueError('不支持的指标写入形态；禁止无范围刷新')
        return super().execute(connection.rewrite_sources(statement), parameters)

    def _allocation(self, statement):
        connection = self.connection
        if connection.refresh_scope.full:
            return super().execute(statement)
        relations = re.findall(r"'(dwd\.[a-z_0-9]+|dws\.[a-z_0-9]+)'\s*::\s*REGCLASS", statement, re.I)
        if len(relations) != 2:
            raise ValueError('不支持的商品分摊过程参数')
        source, target = (tuple(r.split('.')) for r in relations)
        target_predicate = connection.refresh_scope.predicate(connection, target[1], connection.columns(*target))
        if target_predicate == 'FALSE':
            return super().execute('SELECT NULL WHERE FALSE')
        read = connection.read_view(*source, target)
        temp = '_allocation_' + hashlib.sha1(relations[1].encode()).hexdigest()[:12]
        qualified = sql.Identifier('pg_temp', temp).as_string(connection)
        with connection.raw_cursor() as cur:
            cur.execute(f'CREATE TEMP TABLE {sql.Identifier(temp).as_string(connection)} (LIKE {sql.Identifier(*target).as_string(connection)} INCLUDING ALL) ON COMMIT DROP')
        rewritten = statement.replace("'" + relations[0] + "'", sql.Literal(read).as_string(connection)).replace("'" + relations[1] + "'", sql.Literal(qualified).as_string(connection))
        super().execute(rewritten)
        super().execute(f'DELETE FROM {sql.Identifier(*target).as_string(connection)} WHERE {target_predicate}')
        super().execute(f'INSERT INTO {sql.Identifier(*target).as_string(connection)} SELECT * FROM {qualified} WHERE {target_predicate}')
        connection.refresh_events.append({'table': relations[1], 'operation': 'allocation', 'rows': self.rowcount})
        return None


def connection_factory(context):
    class ConfiguredRefreshConnection(RefreshConnection):
        refresh_context = context
    return ConfiguredRefreshConnection
