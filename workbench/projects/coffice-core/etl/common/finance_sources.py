"""Verified calculation sources for the seven-platform operating finance chain.

Settlement exports retain their evidence-backed coverage policy. Native wallet
flow identities select identical export versions within a standard shop/account;
unknown identities, incomplete imports and conflicting versions stop refresh.
All ODS rows and financial formulas remain unchanged.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from etl.common.settlement_sources import ROOT, TABLES, prepare_settlement_sources
from etl.common.report_sources import prepare_report_sources

SOURCE_SQL = 'common/460_finance_source_selection_postgres.sql'
NATIVE_SOURCES = {
    'douyin': ('ods_douyin_fund_raw', '动帐流水号', '动账账户'),
    'ks': ('ods_ks_fund_raw', '账务流水号', None),
    'wechat_channels': ('ods_wechat_channels_settlement_raw', '流水单号', None),
}
METADATA = ['id', 'batch_id', 'source_file_name', 'source_sheet_name',
            'source_row_no', 'row_hash', 'ingest_time']


def verify_fund_files(cursor, entries):
    """Bind explicit fund references to complete ODS imports and every raw field.

    A local export without a successful batch is a gap, not a confirmed zero.
    The manifest carries the already validated standard shop, never a filename
    guess. Tmall account files are covered by the settlement reference manifest.
    """
    if str(ROOT / 'etl') not in sys.path:
        sys.path.insert(0, str(ROOT / 'etl'))
    from common.ods_file_loader import (
        align_source_map, canonicalize_header, normalize_cell,
        read_csv_rows, read_excel_rows,
    )
    checks=[]
    for entry in entries:
        platform=entry['platform_code']
        if platform not in ('douyin','ks','jd'):
            raise ValueError(f'不支持的独立资金来源：{platform}')
        config=importlib.import_module(f'etl.{platform}.load_{platform}_fund_ods').CONFIG
        path=Path(entry['path'])
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        table=config.table_name.split('.')[1]
        cursor.execute('''SELECT l.batch_id,l.parsed_rows FROM ods.ods_file_ingest_log l
            JOIN common.v_ingest_batch_shop_context c USING(batch_id)
            WHERE l.platform_code=%s AND l.target_table=%s AND l.file_hash=%s
              AND l.ingest_status='success' AND l.failed_rows=0
              AND c.shop_code=%s AND c.shop_mapping_status='mapped' ''',
            (platform,table,digest,entry['shop_code']))
        batches=cursor.fetchall()
        if len(batches)!=1:
            raise RuntimeError(f'{path.name}缺少唯一完整资金导入批次，不能将缺失视为零')
        batch,parsed=batches[0]
        if path.suffix.lower()=='.csv':
            _,_,_,header,source_rows=read_csv_rows(config,path)
        else:
            _,_,_,header,source_rows=read_excel_rows(config,path,entry.get('sheet'))
        header,_=canonicalize_header(header,config.header_aliases)
        with cursor.connection.cursor(cursor_factory=RealDictCursor) as raw:
            raw.execute(sql.SQL('SELECT * FROM ods.{} WHERE batch_id=%s ORDER BY source_row_no').format(
                sql.Identifier(table)),(batch,))
            actual={r['source_row_no']:r for r in raw.fetchall()}
        if len(source_rows)!=parsed or len(actual)!=parsed:
            raise RuntimeError(f'{path.name}资金文件/导入日志/ODS行数不一致')
        for row_no,values in source_rows:
            expected=align_source_map(header,values,config.expected_columns)
            row=actual.get(row_no)
            if row is None or any(normalize_cell(row[k])!=v for k,v in expected.items()):
                raise RuntimeError(f'{path.name}第{row_no}行资金原始字段与ODS不一致')
        checks.append({'platform_code':platform,'shop_code':entry['shop_code'],
                       'batch_id':batch,'file':path.name,'file_hash':digest,
                       'rows':parsed,'all_raw_fields_equal':True})
    return checks


def source_relation(table):
    if table in {'ods_jd_settlement_raw', 'ods_jd_fund_raw'}:
        # JD already versions documents / seven-field wallet events in its DWD.
        return 'common.v_selected_' + table.removeprefix('ods_')
    return 'common.v_current_' + table.removeprefix('ods_')


def effective_count(cursor, table):
    cursor.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(*source_relation(table).split('.'))))
    return cursor.fetchone()[0]


def validate_native_source(cursor, platform):
    table, key, account = NATIVE_SOURCES[platform]
    cursor.execute(sql.SQL('''WITH batches AS (
        SELECT batch_id,COUNT(*) n FROM ods.{} GROUP BY batch_id
    ) SELECT b.batch_id FROM batches b
      LEFT JOIN common.v_ingest_batch_shop_context c ON c.batch_id=b.batch_id
        AND c.platform_code=%s AND c.target_table=%s AND c.ingest_status='success'
        AND c.shop_mapping_status='mapped' AND c.shop_identity_key IS NOT NULL
        AND c.shop_code IS NOT NULL AND c.company_code IS NOT NULL
      LEFT JOIN ods.ods_file_ingest_log l ON l.batch_id=b.batch_id
      GROUP BY b.batch_id,b.n,l.parsed_rows,l.failed_rows
      HAVING COUNT(c.batch_id)<>1 OR b.n IS DISTINCT FROM l.parsed_rows
          OR l.failed_rows IS DISTINCT FROM 0''').format(sql.Identifier(table)), (platform, table))
    bad = cursor.fetchall()
    if bad:
        raise RuntimeError(f'{table}历史批次未映射、失败或导入不完整：{bad[:10]}')
    identity = sql.SQL('BTRIM(r.{})').format(sql.Identifier(key))
    account_expr = sql.SQL("COALESCE(BTRIM(r.{}),'')").format(sql.Identifier(account)) if account else sql.SQL("''::text")
    cursor.execute(sql.SQL('SELECT COUNT(*) FROM ods.{} r WHERE {} IS NULL OR {} IN (\'\',\'-\')').format(
        sql.Identifier(table), identity, identity))
    if cursor.fetchone()[0]:
        raise RuntimeError(f'{table}平台流水身份缺失，不能按订单或金额猜测来源')
    cursor.execute(sql.SQL('''SELECT r.batch_id,{},{} FROM ods.{} r
        GROUP BY 1,2,3 HAVING COUNT(*)>1 LIMIT 10''').format(identity, account_expr, sql.Identifier(table)))
    bad = cursor.fetchall()
    if bad:
        raise RuntimeError(f'{table}同一批次平台流水身份不唯一，保留ODS并停止刷新：{bad}')
    relation = (sql.Identifier('common','v_selected_'+table.removeprefix('ods_'))
                if platform in ('douyin','wechat_channels') else sql.Identifier('ods',table))
    cursor.execute(sql.SQL('''SELECT c.shop_identity_key,{},{} FROM {} r
        JOIN common.v_ingest_batch_shop_context c USING(batch_id)
        GROUP BY 1,2,3 HAVING COUNT(DISTINCT (TO_JSONB(r)-%s::text[]))>1 LIMIT 10''').format(
        account_expr, identity, relation), (METADATA,))
    bad = cursor.fetchall()
    if bad:
        raise RuntimeError(f'{table}相同平台流水存在业务字段冲突，不能静默选版本：{bad}')
    # Bind overlapping exports to intact source files, not their names or dates.
    cursor.execute(sql.SQL('''WITH repeated AS (
        SELECT c.shop_identity_key shop,{} account,{} flow
        FROM ods.{} r JOIN common.v_ingest_batch_shop_context c USING(batch_id)
        GROUP BY 1,2,3 HAVING COUNT(*)>1
    ) SELECT DISTINCT l.batch_id,l.source_file_path,l.file_hash
      FROM ods.{} r JOIN common.v_ingest_batch_shop_context c USING(batch_id)
      JOIN repeated d ON d.shop=c.shop_identity_key AND d.account={} AND d.flow={}
      JOIN ods.ods_file_ingest_log l ON l.batch_id=r.batch_id''').format(
        account_expr, identity, sql.Identifier(table), sql.Identifier(table), account_expr, identity))
    for batch, filename, digest in cursor.fetchall():
        path = Path(filename) if filename else None
        if not path or not path.is_file() or not digest or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'{table}重叠来源批次{batch}文件缺失或SHA256不符，停止刷新')


def prepare_finance_sources(cursor, platform, *, include_fund=True):
    prepared = getattr(cursor.connection, 'prepared_sources', None)
    key = ('finance', platform, include_fund)
    if prepared is not None and key in prepared:
        return
    if platform in TABLES:
        prepare_settlement_sources(cursor, platform)
    elif platform == 'pdd':
        prepare_report_sources(cursor, (), pdd_settlement=True)
    if platform=='wechat_channels':
        cursor.execute((ROOT/'sql/common/470_wechat_settlement_source_selection_postgres.sql').read_text(encoding='utf-8'))
    if platform in NATIVE_SOURCES and (platform != 'douyin' or include_fund):
        validate_native_source(cursor, platform)
        cursor.execute((ROOT / 'sql' / SOURCE_SQL).read_text(encoding='utf-8'))
    if platform in ('jd', 'tmall'):
        if platform == 'jd':
            cursor.execute((ROOT / 'sql/common/468_ingest_source_day_selection_postgres.sql').read_text(encoding='utf-8'))
        cursor.execute((ROOT / 'sql' / 'common/461_finance_source_shop_identity_postgres.sql').read_text(encoding='utf-8'))
    if prepared is not None:
        prepared.add(key)
