"""Create the production database without dropping or replacing any database."""

from __future__ import annotations

import argparse
import json
import os

import psycopg2
from psycopg2 import sql

from .db_connection import assert_not_source_database, kwargs_from_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="安全创建正式数据测试库")
    parser.add_argument("--target-db", default="coffice_production")
    parser.add_argument("--admin-url", default=os.getenv("DATABASE_ADMIN_URL"))
    parser.add_argument("--host", default=os.getenv("PGHOST"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--maintenance-db", default=os.getenv("PGMAINTENANCE_DB", "postgres"))
    parser.add_argument("--user", default=os.getenv("PGUSER"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    assert_not_source_database(args.target_db)
    if args.admin_url:
        kwargs = kwargs_from_url(args.admin_url)
    else:
        missing = [name for name in ("host", "user") if not getattr(args, name)]
        if missing:
            raise ValueError("请设置 DATABASE_ADMIN_URL 或显式传入 --host 和 --user")
        kwargs = {
            "host": args.host,
            "port": args.port,
            "dbname": args.maintenance_db,
            "user": args.user,
            "password": args.password,
        }
    connection = psycopg2.connect(**kwargs, application_name="coffice_production_database_creator")
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.target_db,))
            if cursor.fetchone():
                status = "already_exists"
            else:
                cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(args.target_db)))
                status = "created"
    finally:
        connection.close()
    print(json.dumps({"database": args.target_db, "status": status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
