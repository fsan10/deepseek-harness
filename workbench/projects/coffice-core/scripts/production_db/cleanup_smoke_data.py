"""Remove only the exact API smoke-test records created by this migration run."""

from __future__ import annotations

import argparse
import json

import psycopg2

from db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs


SMOKE_IDEMPOTENCY_KEY = "prod-schema-smoke-20260806"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理正式库迁移接口烟测记录")
    add_connection_arguments(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    assert_not_source_database(str(kwargs["dbname"]))
    connection = psycopg2.connect(**kwargs, application_name="coffice_production_smoke_cleanup")
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT run_id::text FROM ops.ingest_run WHERE source='manual' AND idempotency_key=%s FOR UPDATE",
                (SMOKE_IDEMPOTENCY_KEY,),
            )
            run_ids = [row[0] for row in cursor.fetchall()]
            cursor.execute(
                "DELETE FROM ops.operation_log WHERE target_type='ingest_run' AND target_key = ANY(%s)",
                (run_ids,),
            )
            deleted_logs = cursor.rowcount
            cursor.execute(
                "DELETE FROM ops.ingest_run WHERE source='manual' AND idempotency_key=%s",
                (SMOKE_IDEMPOTENCY_KEY,),
            )
            deleted_runs = cursor.rowcount
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps({"deleted_runs": deleted_runs, "deleted_logs": deleted_logs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
