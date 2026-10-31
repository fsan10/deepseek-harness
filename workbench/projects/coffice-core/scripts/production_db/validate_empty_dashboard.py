"""Verify every migrated ADS table is queryable and returns no business rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2
from psycopg2 import sql

from db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "scripts/production_db/generated/migration_manifest.json"
OUTPUT = ROOT / "docs/production_database/empty_dashboard_validation.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证空正式库ADS查询")
    add_connection_arguments(parser)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    assert_not_source_database(str(kwargs["dbname"]))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    ads_tables = sorted(name for name in manifest["included_tables"] if name.startswith("ads."))
    results = []
    connection = psycopg2.connect(**kwargs, application_name="coffice_production_empty_dashboard_validation")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            for qualified_name in ads_tables:
                schema, table = qualified_name.split(".", 1)
                cursor.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
                )
                count = cursor.fetchone()[0]
                cursor.execute(
                    sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(sql.Identifier(schema), sql.Identifier(table))
                )
                results.append({"table": qualified_name, "row_count": count, "first_row": cursor.fetchone()})
            connection.rollback()
    finally:
        connection.close()
    report = {
        "database": kwargs["dbname"],
        "ads_table_count": len(results),
        "query_success": True,
        "all_empty": all(item["row_count"] == 0 and item["first_row"] is None for item in results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("database", "ads_table_count", "query_success", "all_empty")}, ensure_ascii=False))
    if not report["all_empty"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
