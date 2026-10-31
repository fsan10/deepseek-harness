#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将达人归属月更Excel作为指定月份的初始版本写入DIM。

本导入只补充不存在的“平台+达人ID+生效月”，不覆盖配置网页已维护的版本。
"""

from __future__ import annotations

import argparse
import os
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

try:
    import openpyxl
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError as exc:
    raise SystemExit("缺少依赖：openpyxl或psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIM_SQL = PROJECT_ROOT / "sql" / "dim" / "166_dim_influencer_business_config_postgres.sql"

PLATFORM_MAP = {
    "抖音": ("douyin", "抖音"),
    "快手": ("ks", "快手"),
    "视频号": ("wechat_channels", "视频号"),
    "天猫": ("tmall", "天猫"),
    "小红书": ("xhs", "小红书"),
    "京东": ("jd", "京东"),
    "拼多多": ("pdd", "拼多多"),
}


def clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_month(value: str):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("月份必须使用YYYY-MM-01") from exc
    if parsed.day != 1:
        raise argparse.ArgumentTypeError("月份必须是自然月首日，例如2026-07-01")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="初始导入达人商务归属月度版本。")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--month", required=True, type=parse_month)
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def read_assignments(file_path: Path) -> tuple[list[dict], list[tuple]]:
    if not file_path.is_file():
        raise FileNotFoundError(f"达人归属文件不存在：{file_path}")

    workbook = openpyxl.load_workbook(file_path, data_only=True, read_only=False)
    sheet = workbook[workbook.sheetnames[0]]
    headers = [clean(cell.value) for cell in sheet[1][:5]]
    expected_headers = ["渠道", "达人名称", "达人UID", "商务归属", "店铺归属"]
    if headers != expected_headers:
        raise RuntimeError(f"达人归属表头不匹配：{headers}")

    grouped: OrderedDict[tuple[str, str], dict] = OrderedDict()
    incomplete_rows: list[tuple] = []
    prior_identity = [None, None, None, None]

    for row_number, values in enumerate(
        sheet.iter_rows(min_row=2, max_col=5, values_only=True),
        start=2,
    ):
        row = [clean(value) for value in values]
        if not any(row):
            continue
        if not any(row[:4]) and row[4]:
            row[:4] = prior_identity
        else:
            for index in range(4):
                if row[index] is not None:
                    prior_identity[index] = row[index]

        platform_label, influencer_name, influencer_id, owner_name, shop_name = row
        if not platform_label or not influencer_id or not owner_name:
            incomplete_rows.append((row_number, *row))
            continue
        if platform_label not in PLATFORM_MAP:
            raise RuntimeError(f"第{row_number}行存在未支持平台：{platform_label}")

        platform_code, platform_name = PLATFORM_MAP[platform_label]
        key = (platform_code, influencer_id)
        display_name = "其他" if influencer_id == "0" else (influencer_name or "未命名达人")
        if key not in grouped:
            grouped[key] = {
                "platform_code": platform_code,
                "platform_name": platform_name,
                "influencer_id": influencer_id,
                "influencer_name": display_name,
                "owner_name": owner_name,
                "shop_names": [],
            }
        elif grouped[key]["owner_name"] != owner_name:
            raise RuntimeError(
                f"同一平台达人归属多个商务：{platform_name}/{influencer_id}/"
                f"{grouped[key]['owner_name']}/{owner_name}"
            )
        if shop_name and shop_name not in grouped[key]["shop_names"]:
            grouped[key]["shop_names"].append(shop_name)

    return list(grouped.values()), incomplete_rows


def run(args: argparse.Namespace) -> None:
    assignments, incomplete_rows = read_assignments(args.file.resolve())
    if not assignments:
        raise RuntimeError("达人归属文件没有可导入记录")

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(DIM_SQL.read_text(encoding="utf-8"))

            owner_names = sorted({item["owner_name"] for item in assignments})
            execute_values(
                cursor,
                """
                INSERT INTO dim.dim_business_owner (business_owner_name)
                VALUES %s
                ON CONFLICT (business_owner_name) DO NOTHING
                """,
                [(name,) for name in owner_names],
            )
            cursor.execute(
                """
                SELECT business_owner_id, business_owner_name
                FROM dim.dim_business_owner
                WHERE business_owner_name = ANY(%s)
                """,
                (owner_names,),
            )
            owner_ids = {name: owner_id for owner_id, name in cursor.fetchall()}

            rows = [
                (
                    item["platform_code"],
                    item["platform_name"],
                    item["influencer_id"],
                    item["influencer_name"],
                    args.month,
                    owner_ids[item["owner_name"]],
                    "excel_seed",
                    args.file.name,
                    item["shop_names"],
                )
                for item in assignments
            ]
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM dim.dim_influencer_business_assignment_monthly
                WHERE effective_month = %s
                """,
                (args.month,),
            )
            before_month_rows = cursor.fetchone()[0]
            execute_values(
                cursor,
                """
                INSERT INTO dim.dim_influencer_business_assignment_monthly (
                    platform_code,
                    platform_name,
                    influencer_id,
                    influencer_name,
                    effective_month,
                    business_owner_id,
                    assignment_source,
                    source_file_name,
                    source_shop_names
                )
                VALUES %s
                ON CONFLICT (platform_code, influencer_id, effective_month) DO NOTHING
                """,
                rows,
            )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM dim.dim_influencer_business_assignment_monthly
                WHERE effective_month = %s
                """,
                (args.month,),
            )
            month_rows = cursor.fetchone()[0]
            inserted_rows = month_rows - before_month_rows
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(f"来源文件：{args.file.resolve()}")
    print(f"归属生效月：{args.month}")
    print(f"文件唯一平台达人：{len(assignments)}")
    print(f"本次新增归属版本：{inserted_rows}")
    print(f"该月现有归属版本：{month_rows}")
    print(f"跳过缺少平台/UID/商务的行：{len(incomplete_rows)}")
    for row in incomplete_rows:
        print(f"  {row}")


if __name__ == "__main__":
    run(build_parser().parse_args())
