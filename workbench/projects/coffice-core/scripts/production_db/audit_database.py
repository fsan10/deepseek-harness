"""Read-only PostgreSQL catalog audit used by the production database migration.

The script never executes DDL or DML.  It opens a read-only transaction and writes
the discovered catalog metadata to a local JSON file for review and later checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


DEFAULT_SCHEMAS = (
    "ods",
    "dwd",
    "dws",
    "dim",
    "ads",
    "ops",
    "fund",
    "common",
    "iam",
    "config",
    "ai",
    "public",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读导出 PostgreSQL 对象目录")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/production_database/mock_coffice_catalog.json"),
    )
    parser.add_argument("--exact-counts", action="store_true")
    return parser


def fetch_all(cursor: RealDictCursor, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def fetch_one(cursor: RealDictCursor, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cursor.execute(query, params)
    row = cursor.fetchone()
    return dict(row) if row else {}


def relation_counts(cursor: RealDictCursor, tables: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        qualified = f'"{table["schema_name"]}"."{table["relation_name"]}"'
        cursor.execute(f"SELECT COUNT(*) AS row_count FROM {qualified}")
        counts[f'{table["schema_name"]}.{table["relation_name"]}'] = int(cursor.fetchone()["row_count"])
    return counts


def main() -> None:
    args = build_parser().parse_args()
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
        application_name="mock_coffice_readonly_catalog_audit",
    )
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            server = fetch_one(
                cursor,
                """
                SELECT current_database() AS database_name,
                       current_user AS database_user,
                       current_setting('server_version') AS server_version,
                       current_setting('server_version_num')::integer AS server_version_num
                """,
            )
            schemas = fetch_all(
                cursor,
                """
                SELECT nspname AS schema_name, pg_get_userbyid(nspowner) AS owner
                FROM pg_namespace
                WHERE nspname NOT LIKE 'pg_%%' AND nspname <> 'information_schema'
                ORDER BY nspname
                """,
            )
            relations = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name,
                       c.relname AS relation_name,
                       c.relkind,
                       CASE c.relkind
                           WHEN 'r' THEN 'table'
                           WHEN 'p' THEN 'partitioned_table'
                           WHEN 'v' THEN 'view'
                           WHEN 'm' THEN 'materialized_view'
                           WHEN 'S' THEN 'sequence'
                           WHEN 'f' THEN 'foreign_table'
                           ELSE c.relkind::text
                       END AS relation_type,
                       pg_get_userbyid(c.relowner) AS owner,
                       obj_description(c.oid, 'pg_class') AS comment,
                       c.reltuples::bigint AS estimated_rows,
                       pg_total_relation_size(c.oid) AS total_bytes
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s)
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                ORDER BY n.nspname, c.relname
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            columns = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name,
                       c.relname AS relation_name,
                       a.attnum AS ordinal_position,
                       a.attname AS column_name,
                       pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                       a.attnotnull AS not_null,
                       pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                       NULLIF(a.attidentity, '') AS identity_kind,
                       NULLIF(a.attgenerated, '') AS generated_kind,
                       col_description(c.oid, a.attnum) AS comment
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
                WHERE n.nspname = ANY(%s)
                  AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND a.attnum > 0 AND NOT a.attisdropped
                ORDER BY n.nspname, c.relname, a.attnum
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            constraints = fetch_all(
                cursor,
                """
                SELECT src_ns.nspname AS schema_name,
                       src.relname AS relation_name,
                       con.conname AS constraint_name,
                       con.contype AS constraint_type,
                       pg_get_constraintdef(con.oid, true) AS definition,
                       dst_ns.nspname AS referenced_schema,
                       dst.relname AS referenced_relation,
                       con.condeferrable AS deferrable,
                       con.condeferred AS initially_deferred,
                       con.convalidated AS validated
                FROM pg_constraint con
                JOIN pg_class src ON src.oid = con.conrelid
                JOIN pg_namespace src_ns ON src_ns.oid = src.relnamespace
                LEFT JOIN pg_class dst ON dst.oid = con.confrelid
                LEFT JOIN pg_namespace dst_ns ON dst_ns.oid = dst.relnamespace
                WHERE src_ns.nspname = ANY(%s)
                ORDER BY src_ns.nspname, src.relname, con.conname
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            indexes = fetch_all(
                cursor,
                """
                SELECT idx_ns.nspname AS schema_name,
                       tbl.relname AS relation_name,
                       idx.relname AS index_name,
                       pg_get_indexdef(idx.oid) AS definition,
                       con.conname AS backing_constraint_name
                FROM pg_index i
                JOIN pg_class idx ON idx.oid = i.indexrelid
                JOIN pg_namespace idx_ns ON idx_ns.oid = idx.relnamespace
                JOIN pg_class tbl ON tbl.oid = i.indrelid
                LEFT JOIN pg_constraint con
                  ON con.conindid = idx.oid AND con.contype IN ('p', 'u', 'x')
                WHERE idx_ns.nspname = ANY(%s)
                ORDER BY idx_ns.nspname, tbl.relname, idx.relname
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            views = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name,
                       c.relname AS relation_name,
                       c.relkind AS relation_kind,
                       pg_get_viewdef(c.oid, true) AS definition
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND c.relkind IN ('v', 'm')
                ORDER BY n.nspname, c.relname
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            view_dependencies = fetch_all(
                cursor,
                """
                SELECT DISTINCT view_ns.nspname AS view_schema,
                       view_cls.relname AS view_name,
                       dep_ns.nspname AS referenced_schema,
                       dep_cls.relname AS referenced_relation
                FROM pg_rewrite rw
                JOIN pg_class view_cls ON view_cls.oid = rw.ev_class
                JOIN pg_namespace view_ns ON view_ns.oid = view_cls.relnamespace
                JOIN pg_depend d ON d.objid = rw.oid
                JOIN pg_class dep_cls ON dep_cls.oid = d.refobjid
                JOIN pg_namespace dep_ns ON dep_ns.oid = dep_cls.relnamespace
                WHERE view_ns.nspname = ANY(%s)
                  AND view_cls.relkind IN ('v', 'm')
                  AND dep_ns.nspname = ANY(%s)
                  AND dep_cls.oid <> view_cls.oid
                ORDER BY view_ns.nspname, view_cls.relname, dep_ns.nspname, dep_cls.relname
                """,
                (list(DEFAULT_SCHEMAS), list(DEFAULT_SCHEMAS)),
            )
            functions = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name,
                       p.proname AS function_name,
                       pg_get_function_identity_arguments(p.oid) AS identity_arguments,
                       l.lanname AS language,
                       pg_get_function_result(p.oid) AS result_type,
                       pg_get_functiondef(p.oid) AS definition
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                JOIN pg_language l ON l.oid = p.prolang
                WHERE n.nspname = ANY(%s)
                ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            triggers = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name,
                       c.relname AS relation_name,
                       t.tgname AS trigger_name,
                       pg_get_triggerdef(t.oid, true) AS definition,
                       t.tgenabled AS enabled
                FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = ANY(%s) AND NOT t.tgisinternal
                ORDER BY n.nspname, c.relname, t.tgname
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            sequences = fetch_all(
                cursor,
                """
                SELECT seq.schemaname AS schema_name,
                       seq.sequencename AS sequence_name,
                       seq.data_type,
                       seq.start_value,
                       seq.min_value,
                       seq.max_value,
                       seq.increment_by,
                       seq.cache_size,
                       seq.cycle,
                       dep_ns.nspname AS owned_by_schema,
                       dep_cls.relname AS owned_by_relation,
                       dep_att.attname AS owned_by_column,
                       dep.deptype AS ownership_type
                FROM pg_sequences seq
                JOIN pg_class seq_cls ON seq_cls.relname = seq.sequencename
                JOIN pg_namespace seq_ns ON seq_ns.oid = seq_cls.relnamespace AND seq_ns.nspname = seq.schemaname
                LEFT JOIN pg_depend dep ON dep.objid = seq_cls.oid AND dep.deptype IN ('a', 'i')
                LEFT JOIN pg_class dep_cls ON dep_cls.oid = dep.refobjid
                LEFT JOIN pg_namespace dep_ns ON dep_ns.oid = dep_cls.relnamespace
                LEFT JOIN pg_attribute dep_att ON dep_att.attrelid = dep.refobjid AND dep_att.attnum = dep.refobjsubid
                WHERE seq.schemaname = ANY(%s)
                ORDER BY seq.schemaname, seq.sequencename
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            extensions = fetch_all(
                cursor,
                """
                SELECT extname AS extension_name, extversion AS version,
                       n.nspname AS schema_name
                FROM pg_extension e
                JOIN pg_namespace n ON n.oid = e.extnamespace
                ORDER BY extname
                """,
            )
            enum_values = fetch_all(
                cursor,
                """
                SELECT n.nspname AS schema_name, t.typname AS type_name,
                       e.enumsortorder, e.enumlabel
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE n.nspname = ANY(%s)
                ORDER BY n.nspname, t.typname, e.enumsortorder
                """,
                (list(DEFAULT_SCHEMAS),),
            )
            tables = [item for item in relations if item["relation_type"] in {"table", "partitioned_table"}]
            exact_counts = relation_counts(cursor, tables) if args.exact_counts else {}
            connection.rollback()
    finally:
        connection.close()

    catalog: dict[str, Any] = {
        "server": server,
        "audited_schemas": list(DEFAULT_SCHEMAS),
        "schemas": schemas,
        "relations": relations,
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "views": views,
        "view_dependencies": view_dependencies,
        "functions": functions,
        "triggers": triggers,
        "sequences": sequences,
        "extensions": extensions,
        "enum_values": enum_values,
        "exact_row_counts": exact_counts,
    }
    signature_payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, default=str)
    catalog["catalog_sha256"] = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "database": server.get("database_name"),
                "relations": len(relations),
                "tables": len(tables),
                "views": len(views),
                "functions": len(functions),
                "triggers": len(triggers),
                "constraints": len(constraints),
                "indexes": len(indexes),
                "catalog_sha256": catalog["catalog_sha256"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
