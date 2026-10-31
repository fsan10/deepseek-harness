from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

from psycopg2.extras import RealDictCursor

from .sql_safety import ReadonlySqlValidator
from .metadata_discovery import MetadataDiscovery


@dataclass(slots=True)
class QueryResult:
    columns: list[str]
    rows: list[dict]
    row_count: int
    elapsed_ms: int
    sql_hash: str
    tables: tuple[str, ...]
    was_masked: bool


class ReadonlyQueryExecutor:
    def __init__(self, database, cipher):
        self.database = database
        self.cipher = cipher
        self.validator = ReadonlySqlValidator()
        self.metadata_discovery = MetadataDiscovery(database, cipher)

    def discover_metadata(self, source_code: str | None = None) -> list[dict]:
        return self.metadata_discovery.discover(source_code)

    def execute(self, context, *, channel: str, source_code: str, sql: str, cancel_event=None,
                metadata_rows=None) -> QueryResult:
        metadata = metadata_rows if metadata_rows is not None else self.discover_metadata(source_code)
        source_rows = [row for row in metadata if row["source_code"] == source_code]
        allowed_tables = {
            f"{row['schema_name']}.{row['object_name']}" for row in source_rows
        }
        allowed_columns = {
            f"{row['schema_name']}.{row['object_name']}.{row['column_name']}" for row in source_rows
        }
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT * FROM ai.data_source
                   WHERE source_code=%s AND is_active AND deleted_at IS NULL""", (source_code,)
            )
            source = cursor.fetchone()
        if not source:
            raise ValueError("数据源不存在或未启用")
        validated = self.validator.validate(
            sql, allowed_tables=allowed_tables, allowed_columns=allowed_columns,
        )
        scoped_sql = validated.sql
        password = self.cipher.decrypt(
            source["password_ciphertext"], source["password_nonce"], context=f"data-source:{source_code}"
        )
        connection = None
        query_done = threading.Event()
        started = time.perf_counter()
        status, error_category, row_count, was_masked = "failed", None, 0, False
        digest = hashlib.sha256(scoped_sql.encode("utf-8")).hexdigest()
        try:
            import psycopg2
            connection = psycopg2.connect(
                host=source["host"], port=source["port"], dbname=source["database_name"],
                user=source["readonly_username"], password=password, sslmode=source["ssl_mode"],
                connect_timeout=int(source["connect_timeout_seconds"]),
            )
            connection.set_session(readonly=True, autocommit=False)
            if cancel_event is not None:
                def watch_cancel():
                    while not query_done.wait(0.1):
                        if cancel_event.is_set():
                            try: connection.cancel()
                            except Exception: pass
                            return
                threading.Thread(target=watch_cancel, name="ai-query-cancel", daemon=True).start()
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", (int(source["statement_timeout_ms"]),))
                cursor.execute("SET LOCAL lock_timeout = %s", (int(source["lock_timeout_ms"]),))
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = %s", (int(source["idle_transaction_timeout_ms"]),))
                if cancel_event is not None and cancel_event.is_set():
                    connection.cancel()
                    raise RuntimeError("查询已取消")
                cursor.execute(scoped_sql)
                raw_rows = [dict(row) for row in cursor.fetchall()]
            connection.rollback()
            sensitive = {
                row["column_name"]: row.get("mask_rule") or "partial"
                for row in source_rows if row.get("is_sensitive")
            }
            for row in raw_rows:
                for name, rule in sensitive.items():
                    if name in row and row[name] is not None:
                        row[name] = self._mask(row[name], rule)
                        was_masked = True
            row_count = len(raw_rows)
            status = "success"
            return QueryResult(list(raw_rows[0].keys()) if raw_rows else [], raw_rows, row_count,
                               int((time.perf_counter()-started)*1000), digest, validated.tables, was_masked)
        except Exception as exc:
            error_category = "cancelled" if "取消" in str(exc) else type(exc).__name__[:64]
            status = "cancelled" if error_category == "cancelled" else "failed"
            raise
        finally:
            query_done.set()
            if connection is not None:
                connection.close()
            elapsed = int((time.perf_counter()-started)*1000)
            with self.database.transaction() as cursor:
                cursor.execute(
                    """INSERT INTO ai.query_audit
                       (user_id,department_id,channel,external_actor_id,data_source_id,accessed_objects,accessed_columns,
                        sql_hash,elapsed_ms,returned_rows,was_masked,status,error_category,retention_until)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,NOW()+INTERVAL '365 days')""",
                    (context.user_id if context.user_id > 0 else None,context.department_id,channel,
                     context.username if context.user_id <= 0 else None,source["data_source_id"],
                     __import__("json").dumps(validated.tables),__import__("json").dumps(validated.columns),
                     digest,elapsed,row_count,was_masked,status,error_category),
                )

    @staticmethod
    def _mask(value, rule: str):
        text = str(value)
        if rule == "null":
            return None
        if rule == "hash":
            return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        if rule == "full":
            return "***"
        return text[:2] + "****" + text[-2:] if len(text) > 4 else "****"
