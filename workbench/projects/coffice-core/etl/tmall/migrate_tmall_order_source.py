#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将旧版天猫主订单ODS原子迁移到宝贝销售明细子订单ODS。"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import execute_values
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ETL_ROOT = PROJECT_ROOT / "etl"
SQL_DIR = PROJECT_ROOT / "sql"
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

from common.ingest_log import calculate_file_sha256  # noqa: E402
from common.ods_file_loader import (  # noqa: E402
    align_source_map,
    read_csv_rows,
    read_excel_rows,
    read_legacy_excel_rows,
    row_hash,
    validate_header,
)
from tmall.load_tmall_order_ods import CONFIG, EXPECTED_COLUMNS  # noqa: E402


STAGE_DDL = (
    SQL_DIR
    / "tmall/ods/297_ods_tmall_order_raw_item_grain_stage_postgres.sql"
)
CANONICAL_TABLE = "ods_tmall_order_raw"
STAGE_TABLE = "ods_tmall_order_raw_next"


@dataclass(frozen=True)
class ParsedFile:
    path: Path
    file_encoding: str | None
    source_sheet_name: str
    total_rows: int
    data_rows: list[tuple[int, list[str | None]]]
    retained_rows: list[tuple[int, list[str | None]]]
    file_hash: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "补导完整历史宝贝销售明细后，将旧版天猫主订单ODS归档，"
            "并原子切换到同名子订单ODS。"
        )
    )
    parser.add_argument(
        "--file",
        action="append",
        required=True,
        help="新格式宝贝销售明细文件；历史和当前文件分别重复传入本参数。",
    )
    parser.add_argument("--sheet", default=None, help="可选：所有Excel统一使用的工作表名称。")
    parser.add_argument("--shop-code", required=True, help="标准天猫店铺编码。")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="实际执行归档和切换；不传时只验证文件、旧ODS覆盖和店铺上下文。",
    )
    parser.add_argument(
        "--allow-incomplete-history-for-validation",
        action="store_true",
        help="仅供开发自测：允许只读验证文件结构但不满足旧订单全覆盖；与--execute互斥。",
    )
    parser.add_argument(
        "--allow-incomplete-history-for-test-cutover",
        action="store_true",
        help=(
            "仅用于用户明确确认可丢弃旧测试数据时：允许新文件未覆盖全部旧主订单"
            "仍执行归档和切换；必须与--execute同时使用。"
        ),
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def parse_source_file(path: Path, sheet_name: str | None) -> ParsedFile:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        encoding, resolved_sheet, total_rows, header, data_rows = read_csv_rows(
            CONFIG, path
        )
    elif suffix in (".xlsx", ".xlsm"):
        encoding, resolved_sheet, total_rows, header, data_rows = read_excel_rows(
            CONFIG, path, sheet_name
        )
    elif suffix == ".xls":
        encoding, resolved_sheet, total_rows, header, data_rows = (
            read_legacy_excel_rows(CONFIG, path, sheet_name)
        )
    else:
        raise ValueError(f"不支持的文件类型：{path.suffix}")

    validate_header(
        header,
        EXPECTED_COLUMNS,
        strict_header=False,
        optional_columns=(),
    )
    retained_rows: list[tuple[int, list[str | None]]] = []
    for source_row_no, source_values in data_rows:
        source_map = align_source_map(header, source_values, EXPECTED_COLUMNS)
        retained = [source_map.get(column) for column in EXPECTED_COLUMNS]
        retained_rows.append((source_row_no, retained))

    validate_retained_rows(path, retained_rows)
    return ParsedFile(
        path=path,
        file_encoding=encoding,
        source_sheet_name=resolved_sheet,
        total_rows=total_rows,
        data_rows=data_rows,
        retained_rows=retained_rows,
        file_hash=calculate_file_sha256(path),
    )


def validate_retained_rows(
    path: Path,
    retained_rows: list[tuple[int, list[str | None]]],
) -> None:
    if not retained_rows:
        raise ValueError(f"文件没有非空数据行：{path}")
    position = {name: index for index, name in enumerate(EXPECTED_COLUMNS)}
    errors: list[str] = []
    for source_row_no, values in retained_rows:
        for field in ("子订单编号", "主订单编号", "商品标题", "订单创建时间"):
            value = values[position[field]]
            if value is None or not str(value).strip():
                errors.append(f"第{source_row_no}行{field}为空")
        for field in ("购买数量", "买家应付货款", "买家实付金额"):
            value = values[position[field]]
            if value is None or not str(value).strip():
                continue
            normalized = (
                str(value)
                .strip()
                .replace(",", "")
                .replace("￥", "")
                .replace("¥", "")
                .replace("元", "")
            )
            try:
                float(normalized)
            except ValueError:
                errors.append(f"第{source_row_no}行{field}无法解析：{value}")
        if len(errors) >= 20:
            break
    if errors:
        raise ValueError(f"{path.name}关键字段校验失败：{'；'.join(errors)}")


def resolve_shop(cursor, shop_code: str) -> tuple[str, str, str, str, str]:
    cursor.execute(
        """
        SELECT platform_name, shop_code, shop_name, shop_identity_key, company_code
        FROM dim.dim_platform_shop_company
        WHERE platform_code = 'tmall'
          AND shop_code = %s
          AND is_active
          AND CURRENT_DATE >= valid_from
          AND (valid_to IS NULL OR CURRENT_DATE <= valid_to)
        """,
        (shop_code,),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            f"天猫店铺DIM必须唯一命中：shop_code={shop_code}, matched={len(rows)}"
        )
    return rows[0]


def inspect_legacy_ods(cursor) -> tuple[int, set[str], tuple]:
    cursor.execute("SELECT to_regclass('ods.ods_tmall_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少旧ODS：ods.ods_tmall_order_raw")
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_tmall_order_raw'
        """
    )
    columns = {row[0] for row in cursor.fetchall()}
    if "订单编号" not in columns:
        if "子订单编号" in columns:
            raise RuntimeError("天猫订单ODS已经是新子订单结构，不允许重复执行一次性迁移")
        raise RuntimeError("当前天猫订单ODS既不是旧结构也不是已确认的新结构")
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("订单编号"), '')),
            MIN(NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-')::timestamp::date),
            MAX(NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-')::timestamp::date)
        FROM ods.ods_tmall_order_raw
        """
    )
    row_count, order_count, min_date, max_date = cursor.fetchone()
    cursor.execute(
        """
        SELECT DISTINCT BTRIM("订单编号")
        FROM ods.ods_tmall_order_raw
        WHERE NULLIF(BTRIM("订单编号"), '') IS NOT NULL
        """
    )
    orders = {row[0] for row in cursor.fetchall()}
    if len(orders) != order_count:
        raise RuntimeError("旧ODS主订单覆盖集合读取不一致")
    return row_count, orders, (min_date, max_date)


def source_order_sets(files: list[ParsedFile]) -> tuple[set[str], set[str], int]:
    position = {name: index for index, name in enumerate(EXPECTED_COLUMNS)}
    main_orders: set[str] = set()
    sub_orders: set[str] = set()
    source_rows = 0
    for item in files:
        for _, values in item.retained_rows:
            source_rows += 1
            main_orders.add(str(values[position["主订单编号"]]).strip())
            sub_orders.add(str(values[position["子订单编号"]]).strip())
    return main_orders, sub_orders, source_rows


def validate_coverage(
    legacy_orders: set[str],
    new_orders: set[str],
    *,
    allow_incomplete: bool,
) -> tuple[int, list[str]]:
    missing = sorted(legacy_orders - new_orders)
    if missing and not allow_incomplete:
        preview = ", ".join(missing[:10])
        raise RuntimeError(
            f"新格式文件尚未覆盖旧ODS的{len(missing)}个主订单，禁止替换；"
            f"示例：{preview}"
        )
    return len(missing), missing[:10]


def reject_duplicate_successful_file(
    cursor,
    shop_identity_key: str,
    item: ParsedFile,
) -> None:
    cursor.execute(
        """
        SELECT batch_id
        FROM ods.ods_file_ingest_log
        WHERE platform_code = 'tmall'
          AND shop_identity_key = %s
          AND data_domain = 'order'
          AND target_table IN ('ods_tmall_order_raw', 'ods_tmall_order_raw_next')
          AND source_sheet_name = %s
          AND file_hash = %s
          AND ingest_status = 'success'
        ORDER BY batch_id
        LIMIT 1
        """,
        (shop_identity_key, item.source_sheet_name, item.file_hash),
    )
    row = cursor.fetchone()
    if row:
        raise RuntimeError(
            f"新格式文件已成功导入过，拒绝重复迁移：{item.path.name}, batch_id={row[0]}"
        )


def create_ingest_log(
    cursor,
    item: ParsedFile,
    shop: tuple[str, str, str, str, str],
) -> int:
    platform_name, shop_code, shop_name, shop_identity_key, company_code = shop
    cursor.execute(
        """
        INSERT INTO ods.ods_file_ingest_log (
            source_system, platform_code, platform_name, shop_code, shop_name,
            shop_identity_key, shop_mapping_status, shop_mapping_source,
            shop_mapping_message, data_domain, source_file_path, source_file_name,
            file_hash, file_size_bytes, file_encoding, source_sheet_name,
            header_row_no, data_start_row_no, total_rows, parsed_rows,
            success_rows, duplicate_rows, failed_rows, target_schema, target_table,
            ingest_status, started_at, finished_at, duration_seconds
        )
        VALUES (
            'file', 'tmall', %s, %s, %s, %s, 'mapped', 'manual_selected',
            %s, 'order', %s, %s, %s, %s, %s, %s, 1, 2, %s, %s,
            %s, 0, 0, 'ods', 'ods_tmall_order_raw', 'success',
            NOW(), NOW(), 0
        )
        RETURNING batch_id
        """,
        (
            platform_name,
            shop_code,
            shop_name,
            shop_identity_key,
            f"一次性子订单ODS迁移前通过DIM校验；company_code={company_code}",
            str(item.path.resolve()),
            item.path.name,
            item.file_hash,
            item.path.stat().st_size,
            item.file_encoding,
            item.source_sheet_name,
            item.total_rows,
            len(item.retained_rows),
            len(item.retained_rows),
        ),
    )
    return int(cursor.fetchone()[0])


def insert_stage_rows(cursor, item: ParsedFile, batch_id: int) -> int:
    rows: list[tuple] = []
    for source_row_no, values in item.retained_rows:
        digest = row_hash(
            item.path.name,
            item.source_sheet_name,
            source_row_no,
            values,
        )
        rows.append(
            (
                batch_id,
                item.path.name,
                item.source_sheet_name,
                source_row_no,
                digest,
                *values,
            )
        )
    columns = [
        "batch_id",
        "source_file_name",
        "source_sheet_name",
        "source_row_no",
        "row_hash",
        *EXPECTED_COLUMNS,
    ]
    statement = sql.SQL("INSERT INTO ods.{} ({}) VALUES %s").format(
        sql.Identifier(STAGE_TABLE),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    execute_values(cursor, statement.as_string(cursor), rows, page_size=1000)
    return len(rows)


def cutover(
    cursor,
    files: list[ParsedFile],
    shop: tuple[str, str, str, str, str],
    expected_source_rows: int,
) -> tuple[str, list[int], tuple]:
    cursor.execute(STAGE_DDL.read_text(encoding="utf-8"))
    new_batch_ids: list[int] = []
    inserted_rows = 0
    for item in files:
        reject_duplicate_successful_file(cursor, shop[3], item)
        batch_id = create_ingest_log(cursor, item, shop)
        new_batch_ids.append(batch_id)
        inserted_rows += insert_stage_rows(cursor, item, batch_id)
    if inserted_rows != expected_source_rows:
        raise RuntimeError(
            f"迁移暂存插入行数不一致：{inserted_rows}/{expected_source_rows}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("子订单编号"), '')),
            COUNT(DISTINCT NULLIF(BTRIM("主订单编号"), '')),
            MIN("订单创建时间"::timestamp::date),
            MAX("订单创建时间"::timestamp::date),
            COUNT(*) FILTER (
                WHERE NULLIF(BTRIM("子订单编号"), '') IS NULL
                   OR NULLIF(BTRIM("主订单编号"), '') IS NULL
            )
        FROM ods.ods_tmall_order_raw_next
        """
    )
    profile = cursor.fetchone()
    if profile[0] != inserted_rows or profile[5]:
        raise RuntimeError(f"迁移暂存ODS验收失败：{profile}")

    archive_name = (
        "ods_tmall_order_raw_legacy_"
        + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    cursor.execute(
        sql.SQL("LOCK TABLE ods.{} IN ACCESS EXCLUSIVE MODE").format(
            sql.Identifier(CANONICAL_TABLE)
        )
    )
    cursor.execute(
        sql.SQL("ALTER TABLE ods.{} RENAME TO {}").format(
            sql.Identifier(CANONICAL_TABLE),
            sql.Identifier(archive_name),
        )
    )
    cursor.execute(
        sql.SQL("ALTER TABLE ods.{} RENAME TO {}").format(
            sql.Identifier(STAGE_TABLE),
            sql.Identifier(CANONICAL_TABLE),
        )
    )
    cursor.execute(
        sql.SQL(
            """
            UPDATE ods.ods_file_ingest_log log
            SET target_table = %s, updated_at = NOW()
            WHERE log.batch_id IN (
                SELECT DISTINCT batch_id FROM ods.{}
            )
            """
        ).format(sql.Identifier(archive_name)),
        (archive_name,),
    )
    cursor.execute(
        """
        COMMENT ON TABLE ods.ods_tmall_order_raw IS
        '天猫宝贝销售明细ODS，一行一个来源子订单版本；保存当前GSV、运营、产品和达人指标需要的13个业务字段及导入审计字段。'
        """
    )
    return archive_name, new_batch_ids, profile


def main() -> None:
    args = build_parser().parse_args()
    if args.execute and args.allow_incomplete_history_for_validation:
        raise ValueError(
            "--allow-incomplete-history-for-validation仅允许只读验证，不能与--execute同时使用"
        )
    if (
        args.allow_incomplete_history_for_test_cutover
        and not args.execute
    ):
        raise ValueError(
            "--allow-incomplete-history-for-test-cutover必须与--execute同时使用"
        )
    if (
        args.allow_incomplete_history_for_validation
        and args.allow_incomplete_history_for_test_cutover
    ):
        raise ValueError("两个历史覆盖豁免参数不能同时使用")
    parsed_files = [
        parse_source_file(Path(file_name), args.sheet) for file_name in args.file
    ]
    new_main_orders, new_sub_orders, source_rows = source_order_sets(parsed_files)

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    archive_name = None
    batch_ids: list[int] = []
    stage_profile = None
    try:
        with connection.cursor() as cursor:
            shop = resolve_shop(cursor, args.shop_code)
            legacy_rows, legacy_orders, legacy_dates = inspect_legacy_ods(cursor)
            missing_count, missing_preview = validate_coverage(
                legacy_orders,
                new_main_orders,
                allow_incomplete=(
                    args.allow_incomplete_history_for_validation
                    or args.allow_incomplete_history_for_test_cutover
                ),
            )
            if args.execute:
                archive_name, batch_ids, stage_profile = cutover(
                    cursor,
                    parsed_files,
                    shop,
                    source_rows,
                )
                connection.commit()
            else:
                connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(f"标准店铺：tmall/{args.shop_code}")
    print(f"新格式文件数：{len(parsed_files)}")
    print(f"新格式来源行数/唯一子订单/唯一主订单：{source_rows}/{len(new_sub_orders)}/{len(new_main_orders)}")
    print(f"旧ODS来源行数/唯一主订单：{legacy_rows}/{len(legacy_orders)}")
    print(f"旧ODS日期范围：{legacy_dates[0]} 至 {legacy_dates[1]}")
    print(f"未覆盖旧主订单数：{missing_count}")
    if missing_preview:
        print(f"未覆盖示例：{missing_preview}")
    if args.execute:
        if args.allow_incomplete_history_for_test_cutover and missing_count:
            print(
                "测试数据覆盖豁免：已按用户明确确认，"
                f"允许规范ODS不再保留{missing_count}个未覆盖旧主订单"
            )
        print(f"已归档旧ODS：ods.{archive_name}")
        print(f"新格式导入批次：{batch_ids}")
        print(f"新ODS验收：{stage_profile}")
        print("迁移切换：已提交")
    else:
        print("迁移切换：未执行（只读验证）")


if __name__ == "__main__":
    main()
