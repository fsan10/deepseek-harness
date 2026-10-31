"""Apply generated schema steps transactionally to a non-source database."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import psycopg2

from .db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_FILE = ROOT / "scripts/production_db/generated/001_schema.sql"
STEP_PATTERN = re.compile(r"^-- migration-step: (.+)$", re.MULTILINE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="事务内执行正式库空结构迁移")
    add_connection_arguments(parser)
    parser.add_argument("--schema-file", type=Path, default=DEFAULT_SCHEMA_FILE)
    return parser


def parse_steps(text: str) -> list[tuple[str, str]]:
    matches = list(STEP_PATTERN.finditer(text))
    result: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sql_text = text[start:end].strip()
        if sql_text:
            result.append((match.group(1).strip(), sql_text))
    return result


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    assert_not_source_database(str(kwargs["dbname"]))
    steps = parse_steps(args.schema_file.read_text(encoding="utf-8"))
    if not steps:
        raise RuntimeError("迁移文件没有 migration-step")
    connection = psycopg2.connect(**kwargs, application_name="coffice_production_schema_migration")
    current_step = "connection-check"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_db = cursor.fetchone()[0]
            assert_not_source_database(actual_db)
            if actual_db != kwargs["dbname"]:
                raise RuntimeError(f"连接数据库与请求不一致：{actual_db} != {kwargs['dbname']}")
            for current_step, sql_text in steps:
                cursor.execute(sql_text)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise RuntimeError(f"结构迁移失败，步骤={current_step}: {exc}") from exc
    finally:
        connection.close()
    print(json.dumps({"database": kwargs["dbname"], "steps": len(steps), "status": "success"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
