#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from apps.fund_split_adjust.database import Database  # noqa: E402
from apps.fund_split_adjust.server import UPLOAD_DIR  # noqa: E402


def json_default(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="导入银行原始流水到ODS，并将可选的整理后Sheet写入DWD。")
    result.add_argument("--file", required=True, help="银行.xlsx文件路径")
    result.add_argument("--operator", default="ETL")
    result.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    result.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    result.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    result.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    result.add_argument("--password", default=os.getenv("PGPASSWORD"))
    result.add_argument("--migrate", action="store_true", help="导入前执行本系统SQL")
    return result


def main() -> None:
    args = parser().parse_args()
    database = Database(host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password, upload_dir=UPLOAD_DIR)
    if args.migrate:
        database.migrate()
    imported = database.import_workbook(args.file, original_name=Path(args.file).name, operator=args.operator, ip_address="127.0.0.1")
    print(json.dumps(imported, ensure_ascii=False, default=json_default, indent=2))
    print(
        f"验收摘要：ODS={imported['record_count']}，DWD={imported['dwd_record_count']}，"
        f"日期={imported['date_from']}~{imported['date_to']}，"
        f"借方={imported['total_debit']}，贷方={imported['total_credit']}，"
        f"调账净差={imported['adjustment_balance']}"
    )


if __name__ == "__main__":
    main()

