"""Choose report snapshots without changing ODS facts or metric formulas."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_SQL = "common/434_report_source_selection_postgres.sql"


def prepare_report_sources(cursor, platforms=(), *, pdd_settlement=False):
    runtime = getattr(cursor.connection, 'refresh_scope', None)
    if runtime is not None and not runtime.full:
        platforms = tuple(p for p in platforms if p in runtime.platforms)
        pdd_settlement = pdd_settlement and 'pdd' in runtime.platforms
    tables = [(p, f"ods_{p}_order_raw") for p in platforms]
    if pdd_settlement:
        tables.append(("pdd", "ods_pdd_settlement_raw"))
    for _, table in tables:
        cursor.execute("SELECT to_regclass(%s)", ('ods.' + table,))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少ODS来源表：ods.{table}")
    if tables:
        cursor.execute("SELECT to_regclass('common.v_ingest_batch_shop_context')")
        if cursor.fetchone()[0] is None:
            cursor.execute((PROJECT_ROOT / 'sql/common/52_ingest_batch_shop_context_postgres.sql').read_text(encoding='utf-8'))
    for _, table in tables:
        cursor.execute("SELECT to_regclass(%s)", ('common.v_current_' + table[4:],))
        if cursor.fetchone()[0] is None:
            cursor.execute((PROJECT_ROOT / "sql" / SOURCE_SQL).read_text(encoding="utf-8"))
            break
    for platform, table in tables:
        # Validate ALL historical batches, before choosing a version.
        cursor.execute(f"""
            WITH batches AS (SELECT batch_id FROM ods.{table} GROUP BY batch_id)
            SELECT b.batch_id FROM batches b
            LEFT JOIN common.v_ingest_batch_shop_context c ON c.batch_id=b.batch_id
                AND c.platform_code=%s AND c.target_table=%s
                AND c.shop_mapping_status='mapped' AND c.ingest_status='success'
                AND c.shop_identity_key IS NOT NULL AND c.shop_code IS NOT NULL
                AND c.company_code IS NOT NULL
            GROUP BY b.batch_id HAVING b.batch_id IS NULL OR COUNT(c.batch_id)<>1
        """, (platform, table))
        invalid = cursor.fetchall()
        if invalid:
            raise RuntimeError(f"{table}存在未成功、未映射或冲突批次：{invalid}")
    if pdd_settlement:
        backfill_pdd_settlement_periods(cursor)


def pdd_settlement_period(path: Path, encoding: str):
    if path.suffix.lower() != '.csv':
        return None
    with path.open(encoding=encoding, newline="") as stream:
        header = "\n".join(stream.readline() for _ in range(4))
    match = re.search(
        r"起始时间[：:]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
        r"\s+终止时间[：:]\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", header,
    )
    if not match:
        return None
    start, end = (datetime.fromisoformat(value) for value in match.groups())
    if start > end:
        raise ValueError("拼多多结算查询起止时间倒置")
    # Partial days do not authorize replacement of an entire day's flows.
    if start.time().isoformat() != "00:00:00" or end.time().isoformat() != "23:59:59":
        return None
    return start.date(), end.date()


def save_pdd_settlement_period(conn, batch_id, path, encoding):
    period = pdd_settlement_period(path, encoding)
    if period is None:
        return
    with conn.cursor() as cursor:
        # Standalone loaders may run before the web application's migration.
        cursor.execute("""
            ALTER TABLE ods.ods_file_ingest_log
                ADD COLUMN IF NOT EXISTS report_period_start DATE,
                ADD COLUMN IF NOT EXISTS report_period_end DATE
        """)
        cursor.execute("""
            COMMENT ON COLUMN ods.ods_file_ingest_log.report_period_start IS
                '源结算文件声明且已核验的完整查询起始自然日；未知为空。';
            COMMENT ON COLUMN ods.ods_file_ingest_log.report_period_end IS
                '源结算文件声明且已核验的完整查询结束自然日；用于选择计算覆盖来源。'
        """)
        cursor.execute("""
            SELECT COUNT(*) FROM ods.ods_pdd_settlement_raw WHERE batch_id=%s
              AND (NULLIF(BTRIM("发生时间"),'') IS NULL
                   OR BTRIM("发生时间")::timestamp::date NOT BETWEEN %s AND %s)
        """, (batch_id, *period))
        if cursor.fetchone()[0]:
            raise ValueError("拼多多结算明细超出源文件声明的查询范围")
        cursor.execute("""
            UPDATE ods.ods_file_ingest_log
            SET report_period_start=%s,report_period_end=%s
            WHERE batch_id=%s
        """, (*period, batch_id))


def backfill_pdd_settlement_periods(cursor):
    """Recover only verified header metadata; raw ODS rows remain untouched."""
    cursor.execute("""
        SELECT batch_id,source_file_path,file_encoding,file_hash
        FROM ods.ods_file_ingest_log
        WHERE platform_code='pdd' AND target_table='ods_pdd_settlement_raw'
          AND ingest_status='success' AND report_period_start IS NULL
          AND source_file_path IS NOT NULL
    """)
    for batch_id, filename, encoding, expected_hash in cursor.fetchall():
        path = Path(filename)
        if not path.is_file() or path.suffix.lower() != '.csv' or not expected_hash:
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            continue
        save_pdd_settlement_period(cursor.connection, batch_id, path, encoding or 'utf-8-sig')
