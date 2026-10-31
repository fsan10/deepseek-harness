"""Connection helpers for production migration tools without embedded credentials."""

from __future__ import annotations

import argparse
import os
from urllib.parse import unquote, urlparse


PROTECTED_SOURCE_DATABASE = "mock_coffice"


def add_connection_arguments(parser: argparse.ArgumentParser, *, url_env: str = "PRODUCTION_DATABASE_URL") -> None:
    parser.add_argument("--database-url", default=os.getenv(url_env))
    parser.add_argument("--host", default=os.getenv("PGHOST"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE"))
    parser.add_argument("--user", default=os.getenv("PGUSER"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))


def kwargs_from_url(database_url: str) -> dict[str, object]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("数据库 URL 必须使用 postgres:// 或 postgresql://")
    if not parsed.hostname or not parsed.path.lstrip("/") or not parsed.username:
        raise ValueError("数据库 URL 必须包含主机、数据库名和用户")
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": unquote(parsed.path.lstrip("/")),
        "user": unquote(parsed.username),
        "password": unquote(parsed.password) if parsed.password is not None else None,
    }


def connection_kwargs(args: argparse.Namespace) -> dict[str, object]:
    if args.database_url:
        return kwargs_from_url(args.database_url)
    missing = [name for name in ("host", "dbname", "user") if not getattr(args, name)]
    if missing:
        raise ValueError(
            "未提供完整数据库连接。请设置 PRODUCTION_DATABASE_URL，或显式传入 "
            + ", ".join(f"--{name}" for name in missing)
        )
    return {
        "host": args.host,
        "port": args.port,
        "dbname": args.dbname,
        "user": args.user,
        "password": args.password,
    }


def assert_not_source_database(dbname: str) -> None:
    if dbname.strip().lower() == PROTECTED_SOURCE_DATABASE:
        raise RuntimeError("安全拒绝：生产迁移工具禁止连接或写入 mock_coffice")
