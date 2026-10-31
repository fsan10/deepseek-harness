"""Verified settlement coverage, immutable ODS, and explicit conflict gates.

New registrations require a database-verified automation receipt. Manual
selection uses FileIngest preflight; existing historical registrations survive.
The caller owns the transaction, including subsequent DWD/DWS/ADS refreshes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path

from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SQL = 'common/436_settlement_source_registry_postgres.sql'
TABLES = {
    'douyin': ('ods_douyin_settlement_raw',),
    'ks': ('ods_ks_settlement_raw',),
    'xhs': ('ods_xhs_settlement_income_raw', 'ods_xhs_settlement_expense_raw'),
    'tmall': ('ods_tmall_aggregate_fund_raw', 'ods_tmall_alipay_fund_raw'),
}


def load_pg_env(path=ROOT / '.env'):
    """Load only PG settings into this process; never print credentials."""
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(PGHOST|PGPORT|PGDATABASE|PGUSER|PGPASSWORD)\s*=\s*(.*?)\s*$', line)
            if match:
                os.environ.setdefault(match[1], match[2].strip('\"\''))


def ensure_schema(cursor):
    cursor.execute((ROOT / 'sql/common/468_ingest_source_day_selection_postgres.sql').read_text(encoding='utf-8'))
    cursor.execute((ROOT / 'sql' / SOURCE_SQL).read_text(encoding='utf-8'))


def register_source(cursor, batch_id, start, end, evidence_type, evidence, *, group_key=None):
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if start > end or not evidence or not isinstance(evidence, dict):
        raise ValueError('完整查询范围或覆盖证据无效')
    with cursor.connection.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT * FROM common.v_settlement_source_batch WHERE batch_id=%s', (batch_id,))
        batch = cur.fetchone()
        if not batch or not batch['file_hash']:
            raise ValueError(f'批次{batch_id}缺少成功、已映射的原始文件摘要')
        cur.execute('SELECT source_file_path,parsed_rows,failed_rows FROM ods.ods_file_ingest_log WHERE batch_id=%s', (batch_id,))
        log = cur.fetchone()
        path = Path(log['source_file_path'])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != batch['file_hash']:
            raise ValueError(f'批次{batch_id}原始文件不存在或摘要不符，不能登记覆盖')
        cur.execute('SELECT MIN(stat_date) low,MAX(stat_date) high,COALESCE(SUM(source_rows),0) rows FROM common.v_settlement_source_days WHERE batch_id=%s', (batch_id,))
        bounds = cur.fetchone()
        low, high = bounds['low'],bounds['high']
        if log['failed_rows'] or bounds['rows'] != log['parsed_rows']:
            raise ValueError(f'批次{batch_id}导入行数不完整，不能授权覆盖旧来源')
        if low is not None and (low < start or high > end):
            raise ValueError(f'批次{batch_id}业务日期超出声明查询范围')
    key = group_key or f'batch:{batch_id}'
    cursor.execute('SELECT period_start,period_end,file_hash,source_group_key FROM common.settlement_source_registry WHERE batch_id=%s', (batch_id,))
    old = cursor.fetchone()
    expected = (start, end, batch['file_hash'], key)
    if old:
        values = tuple(old[k] for k in ('period_start','period_end','file_hash','source_group_key')) if isinstance(old,dict) else tuple(old)
        if values != expected:
            raise ValueError(f'批次{batch_id}已有不同覆盖登记，禁止静默覆盖')
        return
    if evidence_type != 'automation_receipt':
        raise ValueError('禁止新增人工范围登记旁路；抖音请通过网页或 apps.file_ingest.cli 的预检、确认采信流程处理。'
                         '其他平台尚未开放人工范围替换，请使用可信自动化回执；已登记历史来源继续保留。')
    _verify_receipt(cursor, batch, start, end, evidence)
    if group_key is not None:
        raise ValueError('新增回执登记不接受手工分片组；未经验证的分片不能合并采信')
    cursor.execute('''INSERT INTO common.settlement_source_registry
        (batch_id,source_group_key,period_start,period_end,file_hash,evidence_type,evidence)
        VALUES (%s,%s,%s,%s,%s,%s,%s)''',
        (batch_id,key,start,end,batch['file_hash'],evidence_type,Json(evidence)))


def _verify_receipt(cursor, batch, start, end, evidence):
    """Validate at the write boundary, including callers outside backfill."""
    artifact_id = evidence.get('artifact_id')
    cursor.execute("SELECT to_regclass('ops.automation_artifact')")
    row = cursor.fetchone()
    exists = next(iter(row.values())) if isinstance(row,dict) else row[0]
    if not artifact_id or not exists:
        raise ValueError('新增范围登记必须绑定真实、已验证的自动化回执')
    with cursor.connection.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''SELECT a.file_hash,a.batch_id,a.coverage_verified,a.business_date_start,a.business_date_end,
            s.platform_code,s.shop_code,s.business_date_start request_start,s.business_date_end request_end,
            c.shop_code batch_shop_code
            FROM ops.automation_artifact a JOIN ops.automation_step_run s USING(step_run_id)
            JOIN common.v_ingest_batch_shop_context c ON c.batch_id=%s
            WHERE a.artifact_id=%s''',(batch['batch_id'],artifact_id))
        receipts=cur.fetchall()
        r=receipts[0] if len(receipts)==1 else None
        if not r or not r['coverage_verified'] or r['file_hash'] != batch['file_hash'] or r['platform_code'] != batch['platform_code'] or r['shop_code'] != r['batch_shop_code'] or (r['business_date_start'],r['business_date_end']) != (start,end) or (r['request_start'],r['request_end']) != (start,end):
            raise ValueError('自动化回执与文件摘要、标准店铺或完整查询范围不一致')
        if r['batch_id'] is not None and r['batch_id'] != batch['batch_id']:
            cur.execute('''SELECT 1 FROM common.v_settlement_source_batch WHERE batch_id=%s
                AND platform_code='xhs' AND shop_identity_key=%s AND file_hash=%s''',
                (r['batch_id'],batch['shop_identity_key'],batch['file_hash']))
            if batch['platform_code'] != 'xhs' or cur.fetchone() is None:
                raise ValueError('回执绑定了其他批次，不能授权本批次覆盖')


def backfill_receipts(cursor, platform):
    cursor.execute("SELECT to_regclass('ops.automation_artifact')")
    if cursor.fetchone()[0] is None:
        return
    # A Xiaohongshu receipt identifies the whole workbook, even when its task
    # stores only the primary sheet's batch. Resolve the companion by the same
    # file hash and mapped shop, including successful zero-row sheet imports.
    # Other platforms retain their existing single-batch/account boundary.
    cursor.execute('''SELECT a.artifact_id,l.batch_id,a.business_date_start,a.business_date_end
        FROM ops.automation_artifact a
        JOIN ods.ods_file_ingest_log l ON l.file_hash=a.file_hash
            AND (a.batch_id IS NULL OR l.batch_id=a.batch_id OR (
                l.platform_code='xhs' AND EXISTS (
                    SELECT 1 FROM common.v_settlement_source_batch anchor
                    WHERE anchor.batch_id=a.batch_id AND anchor.platform_code='xhs'
                      AND anchor.shop_identity_key=l.shop_identity_key
                      AND anchor.file_hash=l.file_hash
                )
            ))
        JOIN ops.automation_step_run s ON s.step_run_id=a.step_run_id
            AND s.platform_code=l.platform_code AND s.shop_code=l.shop_code
        WHERE a.coverage_verified AND a.business_date_start IS NOT NULL
          AND a.business_date_end IS NOT NULL AND l.platform_code=%s
          AND s.business_date_start=a.business_date_start AND s.business_date_end=a.business_date_end
          AND l.target_table=ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM common.settlement_source_registry r WHERE r.batch_id=l.batch_id)
        ORDER BY a.artifact_id''', (platform,list(TABLES[platform])))
    receipts = cursor.fetchall()
    for artifact, batch, start, end in receipts:
        register_source(cursor,batch,start,end,'automation_receipt',{'artifact_id':artifact})
    invalidate = getattr(cursor.connection, 'invalidate_source_cache', None)
    if receipts and invalidate is not None:
        invalidate()


def prepare_settlement_sources(cursor, platform):
    prepared = getattr(cursor.connection, 'prepared_sources', None)
    if prepared is not None and ('settlement', platform) in prepared:
        return
    ensure_schema(cursor)
    tables = list(TABLES[platform])
    # No source selection may conceal an unmapped historical raw batch.
    for table in tables:
        cursor.execute(sql.SQL('''WITH b AS (SELECT batch_id FROM ods.{} GROUP BY batch_id)
            SELECT b.batch_id FROM b LEFT JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id=b.batch_id AND c.platform_code=%s AND c.target_table=%s
              AND c.ingest_status='success' AND c.shop_mapping_status='mapped'
              AND c.shop_identity_key IS NOT NULL AND c.company_code IS NOT NULL
            GROUP BY b.batch_id HAVING COUNT(c.batch_id)<>1''').format(sql.Identifier(table)), (platform,table))
        invalid = cursor.fetchall()
        if invalid:
            raise RuntimeError(f'{table}存在未映射、失败或冲突批次：{invalid}')
    backfill_receipts(cursor,platform)
    cursor.execute('''SELECT r.batch_id FROM common.settlement_source_registry r
        JOIN ods.ods_file_ingest_log l USING(batch_id)
        LEFT JOIN common.v_settlement_source_days d USING(batch_id)
        WHERE l.platform_code=%s AND (r.file_hash<>l.file_hash
            OR d.stat_date NOT BETWEEN r.period_start AND r.period_end) GROUP BY r.batch_id''',(platform,))
    invalid = cursor.fetchall()
    if invalid:
        raise RuntimeError(f'覆盖范围或原始文件版本不符：{invalid}')
    cursor.execute('''SELECT l.batch_id FROM common.settlement_source_registry r
        JOIN ods.ods_file_ingest_log l USING(batch_id)
        LEFT JOIN common.v_settlement_source_days d USING(batch_id)
        WHERE l.platform_code=%s GROUP BY l.batch_id,l.parsed_rows,l.failed_rows
        HAVING COALESCE(SUM(d.source_rows),0)<>l.parsed_rows OR l.failed_rows<>0''',(platform,))
    if cursor.fetchall():
        raise RuntimeError('覆盖来源导入行数不完整，停止刷新')
    # A group is an explicitly approved shard set with one period, never an ingest session guess.
    cursor.execute('''SELECT shop_identity_key,target_table,source_group_key FROM common.v_settlement_source_batch
        WHERE platform_code=%s GROUP BY 1,2,3
        HAVING COUNT(DISTINCT (period_start,period_end))>1''',(platform,))
    if cursor.fetchall():
        raise RuntimeError('配套或分片来源范围不一致')
    if platform == 'xhs':
        cursor.execute('''SELECT shop_identity_key,file_hash FROM common.v_settlement_source_batch
            WHERE platform_code='xhs' GROUP BY 1,2
            HAVING COUNT(DISTINCT target_table)<>2 OR COUNT(DISTINCT (period_start,period_end))>1''')
        if cursor.fetchall():
            raise RuntimeError('小红书工作簿两张配套表缺失或覆盖范围不一致')
        cursor.execute('''SELECT shop_identity_key,stat_date FROM common.v_effective_settlement_source
            WHERE platform_code='xhs' GROUP BY 1,2 HAVING COUNT(DISTINCT file_hash)>1''')
        if cursor.fetchall():
            raise RuntimeError('小红书两张配套表选择了不同文件版本，停止刷新')
    cursor.execute('''SELECT shop_identity_key,target_table,stat_date,ARRAY_AGG(batch_id ORDER BY batch_id)
        FROM common.v_effective_settlement_source WHERE platform_code=%s
        GROUP BY 1,2,3 HAVING COUNT(DISTINCT source_group_key)>1''',(platform,))
    conflicts = cursor.fetchall()
    if conflicts:
        raise RuntimeError(f'结算来源覆盖不明或范围交叉，请登记完整查询参数后重试：{conflicts[:10]}')
    cursor.execute('''SELECT COUNT(*) FROM common.v_settlement_source_days d
        JOIN ods.ods_file_ingest_log l USING(batch_id) WHERE l.platform_code=%s AND d.stat_date IS NULL''',(platform,))
    if cursor.fetchone()[0]:
        raise RuntimeError('结算日期为空，停止来源选择')
    if prepared is not None:
        prepared.add(('settlement', platform))


def main():
    parser = argparse.ArgumentParser(description='登记可信自动化回执；人工采信请使用网页或 apps.file_ingest.cli。')
    parser.add_argument('--manifest', required=True, help='JSON列表：batch_id/start/end/evidence_type=automation_receipt/evidence.artifact_id')
    parser.add_argument('--env-file', default=str(ROOT / '.env'))
    args = parser.parse_args()
    import psycopg2
    load_pg_env(args.env_file)
    entries = json.loads(Path(args.manifest).read_text(encoding='utf-8-sig'))
    if not isinstance(entries,list) or not entries or any(e.get('evidence_type') != 'automation_receipt' or not e.get('evidence',{}).get('artifact_id') for e in entries):
        parser.error('旧人工 --manifest 写入口已停用；请通过网页或 apps.file_ingest.cli 预检和确认采信。此命令仅接受真实自动化回执。')
    with psycopg2.connect() as conn:
        with conn.cursor() as cursor:
            ensure_schema(cursor)
            for item in entries:
                register_source(cursor,item['batch_id'],item['start'],item['end'],
                    item['evidence_type'],item['evidence'],group_key=item.get('group_key'))
    print(f'成功登记{len(entries)}个结算来源的确认范围')


if __name__ == '__main__':
    main()
