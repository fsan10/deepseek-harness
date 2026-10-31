from __future__ import annotations

import re

from psycopg2.extras import RealDictCursor


AI_READ_SCHEMAS = ("ads", "dim")
_SENSITIVE_COLUMN = re.compile(
    r"(^|_)(password|passwd|secret|token|api_key|app_secret|encrypt_key|id_card|mobile|phone|email)($|_)",
    re.IGNORECASE,
)


class MetadataDiscovery:
    """Discover the current read-only account's visible ADS/DIM metadata.

    This is an internal, controlled metadata query.  It does not persist a
    configurable catalog and never exposes pg_catalog to model-generated SQL.
    """

    def __init__(self, database, cipher):
        self.database = database
        self.cipher = cipher

    def discover(self, source_code: str | None = None) -> list[dict]:
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT * FROM ai.data_source
                   WHERE is_active AND deleted_at IS NULL
                     AND (%s IS NULL OR source_code = %s)
                   ORDER BY source_code""",
                (source_code, source_code),
            )
            sources = [dict(row) for row in cursor.fetchall()]

        rows: list[dict] = []
        for source in sources:
            rows.extend(self._discover_source(source))
        return rows

    def _discover_source(self, source: dict) -> list[dict]:
        import psycopg2

        password = self.cipher.decrypt(
            source["password_ciphertext"],
            source["password_nonce"],
            context=f"data-source:{source['source_code']}",
        )
        connection = psycopg2.connect(
            host=source["host"],
            port=source["port"],
            dbname=source["database_name"],
            user=source["readonly_username"],
            password=password,
            sslmode=source["ssl_mode"],
            connect_timeout=int(source["connect_timeout_seconds"]),
        )
        try:
            connection.set_session(readonly=True, autocommit=False)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", (int(source["statement_timeout_ms"]),))
                cursor.execute(
                    """SELECT n.nspname AS schema_name,
                              c.relname AS object_name,
                              CASE c.relkind
                                  WHEN 'r' THEN 'table'
                                  WHEN 'v' THEN 'view'
                                  WHEN 'm' THEN 'materialized_view'
                                  ELSE 'foreign_table'
                              END AS object_type,
                              obj_description(c.oid, 'pg_class') AS table_comment,
                              GREATEST(c.reltuples, 0)::BIGINT AS approximate_row_count,
                              a.attname AS column_name,
                              a.attnum AS ordinal_position,
                              format_type(a.atttypid, a.atttypmod) AS data_type,
                              NOT a.attnotnull AS is_nullable,
                              col_description(c.oid, a.attnum) AS column_comment,
                              EXISTS (
                                  SELECT 1 FROM pg_index i
                                  WHERE i.indrelid = c.oid
                                    AND i.indisprimary
                                    AND a.attnum = ANY(i.indkey)
                              ) AS is_primary_key,
                              EXISTS (
                                  SELECT 1 FROM pg_index i
                                  WHERE i.indrelid = c.oid
                                    AND i.indisunique
                                    AND array_length(i.indkey, 1) = 1
                                    AND a.attnum = ANY(i.indkey)
                              ) AS is_unique
                       FROM pg_class c
                       JOIN pg_namespace n ON n.oid = c.relnamespace
                       JOIN pg_attribute a ON a.attrelid = c.oid
                                              AND a.attnum > 0
                                              AND NOT a.attisdropped
                       WHERE n.nspname = ANY(%s)
                         AND c.relkind IN ('r', 'v', 'm', 'f')
                         AND has_schema_privilege(n.oid, 'USAGE')
                         AND has_table_privilege(c.oid, 'SELECT')
                         AND has_column_privilege(c.oid, a.attname, 'SELECT')
                       ORDER BY n.nspname, c.relname, a.attnum""",
                    (list(AI_READ_SCHEMAS),),
                )
                discovered = [dict(row) for row in cursor.fetchall()]
            connection.rollback()
        finally:
            connection.close()

        result: list[dict] = []
        for row in discovered:
            table_comment = str(row.get("table_comment") or "").strip()
            column_comment = str(row.get("column_comment") or "").strip()
            column_name = row["column_name"]
            sensitive = bool(_SENSITIVE_COLUMN.search(column_name))
            result.append(
                {
                    "data_source_id": source["data_source_id"],
                    "source_code": source["source_code"],
                    "database_name": source["database_name"],
                    "schema_name": row["schema_name"],
                    "object_name": row["object_name"],
                    "object_type": row["object_type"],
                    "table_comment": table_comment or None,
                    "candidate_description": table_comment or f"{row['schema_name']}.{row['object_name']}（根据实时结构识别，口径待核实）",
                    "metadata_status": "confirmed" if table_comment else "pending",
                    "approximate_row_count": row["approximate_row_count"],
                    "column_name": column_name,
                    "data_type": row["data_type"],
                    "is_nullable": row["is_nullable"],
                    "column_comment": column_comment or None,
                    "column_candidate": column_comment or f"字段 {column_name}（根据实时结构识别，含义待核实）",
                    "column_status": "confirmed" if column_comment else "pending",
                    "is_primary_key": row["is_primary_key"],
                    "is_unique": row["is_unique"],
                    "is_sensitive": sensitive,
                    "mask_rule": "partial" if sensitive else "none",
                }
            )
        return result
