#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用 ODS 文件导入器：支持 CSV/XLS/XLSX 原始字段入库。"""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc

from common.ingest_log import (
    calculate_file_sha256,
    create_file_ingest_log,
    finish_file_ingest_log,
    split_table_name,
)


META_COLUMNS = [
    "batch_id",
    "source_file_name",
    "source_sheet_name",
    "source_row_no",
    "row_hash",
]


@dataclass(frozen=True)
class OdsLoadConfig:
    platform_code: str
    platform_name: str
    data_domain: str
    table_name: str
    expected_columns: list[str]
    header_row_no: int
    data_start_row_no: int
    # 某些平台 CSV 没有 Excel 导出中的“总计”行，需要单独指定 CSV 起始行。
    # 未设置时沿用 data_start_row_no，保持现有 Loader 行为。
    csv_data_start_row_no: int | None = None
    default_sheet_name: str = "CSV"
    default_sheet_index: int = 0
    default_encoding_candidates: tuple[str, ...] = ("utf-8-sig", "utf-8", "gb18030", "gbk")
    optional_columns: tuple[str, ...] = ()
    # 平台导出字段偶尔会改名；键为源文件字段名，值为 ODS 标准字段名。
    # 映射只作用于表头对齐，不改变 ODS 原始字段定义。
    header_aliases: dict[str, str] | None = None
    # 保留该参数以兼容既有 Loader 配置；表头统一按字段名对齐，额外字段不再阻断导入。
    strict_header: bool = False
    stop_at_comment_rows: bool = False
    custom_row_transform: Callable[[dict[str, str | None], argparse.Namespace, Path], dict[str, str | None]] | None = None


def normalize_cell(value) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\ufeff", "").strip()
    return text if text != "" else None


def is_empty_row(values: Iterable[str | None]) -> bool:
    return all(value is None or str(value).strip() == "" for value in values)


def is_comment_row(values: list[str | None]) -> bool:
    first = next((value for value in values if value), None)
    return bool(first and first.strip().startswith("#"))


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def detect_csv_encoding(path: Path, candidates: tuple[str, ...]) -> str:
    sample = path.read_bytes()[:65536]
    for encoding in candidates:
        try:
            decoder = codecs.getincrementaldecoder(encoding)()
            decoder.decode(sample, final=False)
            return encoding
        except UnicodeDecodeError:
            continue
    return candidates[0]


def infer_date_from_file(path: Path) -> str:
    text = path.stem
    match = re.search(r"(20\d{2})[-_年.]?([01]\d)[-_月.]?([0-3]\d)", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.search(r"(20\d{2})([01]\d)([0-3]\d)", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return ""


def make_unique_header(header: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    output: list[str] = []
    for column_name in header:
        if not column_name:
            output.append(column_name)
            continue
        seen[column_name] = seen.get(column_name, 0) + 1
        if seen[column_name] == 1:
            output.append(column_name)
        else:
            output.append(f"{column_name}_{seen[column_name]}")
    return output


def row_hash(source_file_name: str, source_sheet_name: str, row_no: int, values: list[str | None]) -> str:
    hash_sheet_name = "" if source_sheet_name in ("", "CSV") else source_sheet_name
    raw = "\x1f".join([source_file_name, hash_sheet_name, str(row_no), *[(value or "") for value in values]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_csv_rows(config: OdsLoadConfig, path: Path) -> tuple[str, str, int, list[str], list[tuple[int, list[str | None]]]]:
    encoding = detect_csv_encoding(path, config.default_encoding_candidates)
    with path.open("r", encoding=encoding, newline="") as file:
        content = file.read()

    sample = content[:8192]
    candidate_delimiters: list[str] = []
    try:
        candidate_delimiters.append(csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter)
    except csv.Error:
        pass
    for delimiter in [",", "\t", ";", "|"]:
        if delimiter not in candidate_delimiters:
            candidate_delimiters.append(delimiter)

    rows: list[list[str]] = []
    best_score = -1
    for delimiter in candidate_delimiters:
        candidate_rows = list(csv.reader(io.StringIO(content), delimiter=delimiter))
        if len(candidate_rows) < config.header_row_no:
            continue
        header_score = sum(1 for cell in candidate_rows[config.header_row_no - 1] if normalize_cell(cell))
        if header_score > best_score:
            rows = candidate_rows
            best_score = header_score

    if len(rows) < config.header_row_no:
        raise ValueError(f"文件行数不足，找不到第 {config.header_row_no} 行表头：{path}")

    header = make_unique_header([normalize_cell(cell) or "" for cell in rows[config.header_row_no - 1]])
    data_rows: list[tuple[int, list[str | None]]] = []

    data_start_row_no = config.csv_data_start_row_no or config.data_start_row_no
    for row_no, row in enumerate(rows[data_start_row_no - 1 :], start=data_start_row_no):
        values = [normalize_cell(cell) for cell in row]
        if is_empty_row(values):
            continue
        if config.stop_at_comment_rows and is_comment_row(values):
            continue
        data_rows.append((row_no, values))

    return encoding, "CSV", len(rows), header, data_rows


def read_excel_rows(config: OdsLoadConfig, path: Path, sheet_name: str | None) -> tuple[str | None, str, int, list[str], list[tuple[int, list[str | None]]]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise SystemExit("缺少依赖：openpyxl。请先执行：pip install openpyxl") from exc

    warnings.filterwarnings("ignore", message="Workbook contains no default style")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name:
            worksheet = workbook[sheet_name]
        else:
            worksheet = workbook.worksheets[config.default_sheet_index]
            sheet_name = worksheet.title

        # Some ecommerce exports write an incorrect worksheet dimension such as A1,
        # causing openpyxl read-only mode to expose only the first cell.
        # Resetting dimensions makes openpyxl scan the actual sheet rows.
        if hasattr(worksheet, "reset_dimensions"):
            worksheet.reset_dimensions()

        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()
    if len(rows) < config.header_row_no:
        raise ValueError(f"工作表行数不足，找不到第 {config.header_row_no} 行表头：{path}::{sheet_name}")

    header = make_unique_header([normalize_cell(cell) or "" for cell in rows[config.header_row_no - 1]])
    data_rows: list[tuple[int, list[str | None]]] = []

    for row_no, row in enumerate(rows[config.data_start_row_no - 1 :], start=config.data_start_row_no):
        values = [normalize_cell(cell) for cell in row]
        if is_empty_row(values):
            continue
        if config.stop_at_comment_rows and is_comment_row(values):
            continue
        data_rows.append((row_no, values))

    return None, sheet_name or config.default_sheet_name, len(rows), header, data_rows


def read_legacy_excel_rows(
    config: OdsLoadConfig,
    path: Path,
    sheet_name: str | None,
) -> tuple[str | None, str, int, list[str], list[tuple[int, list[str | None]]]]:
    try:
        import xlrd
    except ImportError as exc:
        raise SystemExit("缺少依赖：xlrd。读取 .xls 文件前请先执行：pip install xlrd") from exc

    workbook = xlrd.open_workbook(path, on_demand=True)
    try:
        worksheet = (
            workbook.sheet_by_name(sheet_name)
            if sheet_name
            else workbook.sheet_by_index(config.default_sheet_index)
        )
        resolved_sheet_name = worksheet.name
        rows = [
            [worksheet.cell_value(row_index, column_index) for column_index in range(worksheet.ncols)]
            for row_index in range(worksheet.nrows)
        ]
    finally:
        workbook.release_resources()

    if len(rows) < config.header_row_no:
        raise ValueError(
            f"工作表行数不足，找不到第 {config.header_row_no} 行表头：{path}::{resolved_sheet_name}"
        )

    header = make_unique_header([normalize_cell(cell) or "" for cell in rows[config.header_row_no - 1]])
    data_rows: list[tuple[int, list[str | None]]] = []
    for row_no, row in enumerate(rows[config.data_start_row_no - 1 :], start=config.data_start_row_no):
        values = [normalize_cell(cell) for cell in row]
        if is_empty_row(values):
            continue
        if config.stop_at_comment_rows and is_comment_row(values):
            continue
        data_rows.append((row_no, values))

    return None, resolved_sheet_name, len(rows), header, data_rows


def validate_header(
    actual_header: list[str],
    expected_columns: list[str],
    strict_header: bool,
    optional_columns: tuple[str, ...] = (),
) -> None:
    """校验并接受平台导出表头。

    所有平台统一采用字段名匹配：

    * 必填字段（不在 ``optional_columns`` 中）缺失时失败；
    * 平台新增的未知字段自动忽略；
    * 已识别字段由 ``align_source_map`` 按字段名写入 ODS，不依赖列顺序；
    * ``strict_header`` 仅为兼容旧 Loader 配置保留，不再以额外字段或列顺序阻断导入。
    """
    normalized = [cell.replace("\ufeff", "").strip() for cell in actual_header]
    optional_set = set(optional_columns)
    missing_required = [column for column in expected_columns if column not in optional_set and column not in normalized]
    if missing_required:
        raise ValueError(f"表头缺少必填字段：{missing_required}")


def canonicalize_header(
    actual_header: list[str],
    header_aliases: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """把平台源字段名转换为 Loader 的标准字段名。

    返回值的第二项用于日志展示实际发生的别名转换。若同一文件同时包含
    标准字段和其别名，继续导入会导致两个源列竞争同一个 ODS 字段，因此
    明确报错而不是静默覆盖。
    """
    aliases = {
        str(source).replace("\ufeff", "").strip(): str(target).replace("\ufeff", "").strip()
        for source, target in (header_aliases or {}).items()
        if str(source).strip() and str(target).strip()
    }
    if not aliases:
        return actual_header, {}

    normalized = [cell.replace("\ufeff", "").strip() for cell in actual_header]
    canonical = [aliases.get(cell, cell) for cell in normalized]
    changed = {source: target for source, target in aliases.items() if source in normalized}

    seen: dict[str, str] = {}
    for source, target in zip(normalized, canonical):
        previous = seen.get(target)
        if previous is not None and previous != source:
            raise ValueError(
                f"表头字段别名冲突：字段{target!r}同时来自{previous!r}和{source!r}"
            )
        seen[target] = source
    return canonical, changed


def align_source_map(header: list[str], row_values: list[str | None], expected_columns: list[str]) -> dict[str, str | None]:
    source_map = {name: None for name in expected_columns}
    for idx, column_name in enumerate(header):
        if not column_name:
            continue
        if column_name in source_map and idx < len(row_values):
            source_map[column_name] = row_values[idx]
    return source_map


def build_insert_rows(
    config: OdsLoadConfig,
    args: argparse.Namespace,
    path: Path,
    source_sheet_name: str,
    batch_id: int,
    header: list[str],
    data_rows: list[tuple[int, list[str | None]]],
) -> list[tuple]:
    output = []
    for row_no, row_values in data_rows:
        source_map = align_source_map(header, row_values, config.expected_columns)
        if config.custom_row_transform:
            source_map = config.custom_row_transform(source_map, args, path)
        aligned = [source_map.get(column) for column in config.expected_columns]
        digest = row_hash(path.name, source_sheet_name, row_no, aligned)
        output.append((batch_id, path.name, source_sheet_name, row_no, digest, *aligned))
    return output


def insert_rows(
    conn,
    table_name: str,
    expected_columns: list[str],
    rows: list[tuple],
    batch_size: int,
    *,
    commit: bool = True,
) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0

    columns_sql = ", ".join(quote_ident(column) for column in [*META_COLUMNS, *expected_columns])
    sql = f"""
        INSERT INTO {table_name} AS tgt ({columns_sql})
        VALUES %s
        ON CONFLICT (row_hash) DO UPDATE
        SET
            batch_id = COALESCE(tgt.batch_id, EXCLUDED.batch_id),
            source_sheet_name = CASE
                WHEN tgt.source_sheet_name IS NULL OR tgt.source_sheet_name = ''
                    THEN EXCLUDED.source_sheet_name
                ELSE tgt.source_sheet_name
            END
        WHERE tgt.batch_id IS NULL
           OR tgt.source_sheet_name IS NULL
           OR tgt.source_sheet_name = ''
        RETURNING (xmax = 0) AS inserted
    """
    inserted = 0
    backfilled = 0
    with conn.cursor() as cursor:
        for start in range(0, len(rows), batch_size):
            result = execute_values(cursor, sql, rows[start : start + batch_size], page_size=batch_size, fetch=True)
            inserted += sum(1 for item in result if item[0])
            backfilled += sum(1 for item in result if not item[0])
    if commit:
        conn.commit()
    skipped = len(rows) - inserted - backfilled
    return inserted, backfilled, skipped


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--file", required=True, help="待导入文件路径。")
    parser.add_argument("--sheet", default=None, help="Excel 工作表名称。不填则使用脚本配置的默认工作表。")
    parser.add_argument("--table", default=None, help="目标表名。不填则使用脚本默认表。")
    parser.add_argument("--batch-id", type=int, default=None, help="可选：指定导入批次ID。不填则自动创建。")
    parser.add_argument("--shop-code", default=None, help="标准店铺ID。新建导入批次时必填，并由DIM自动带出店铺和公司。")
    parser.add_argument(
        "--shop-mapping-source",
        choices=("manual_selected", "robot_selected"),
        default="manual_selected",
        help="店铺参数来源；人工导入默认manual_selected，影刀批量导入使用robot_selected。",
    )
    parser.add_argument("--batch-size", type=int, default=1000, help="每批写入数据库的行数。")
    parser.add_argument(
        "--no-strict-header",
        action="store_true",
        help="兼容旧调用参数；当前所有 Loader 均按字段名校验并自动忽略额外字段。",
    )
    parser.add_argument("--bill-date", default=None, help="账单日期兜底值，适用于源文件没有账单日期字段的场景。格式建议 YYYY-MM-DD。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def resolve_shop_context(conn, platform_code: str, shop_code: str) -> dict[str, str]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT platform_name, shop_code, shop_name, shop_identity_key, company_code, company_name
            FROM dim.dim_platform_shop_company
            WHERE platform_code = %s
              AND shop_code = %s
              AND is_active
              AND CURRENT_DATE >= valid_from
              AND (valid_to IS NULL OR CURRENT_DATE <= valid_to)
            """,
            (platform_code, shop_code),
        )
        rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError(
            f"店铺映射必须唯一：platform_code={platform_code}, shop_code={shop_code}, matched_rows={len(rows)}"
        )
    platform_name, resolved_code, shop_name, identity_key, company_code, company_name = rows[0]
    return {
        "platform_name": platform_name,
        "shop_code": resolved_code,
        "shop_name": shop_name,
        "shop_identity_key": identity_key,
        "company_code": company_code,
        "company_name": company_name,
    }


def validate_existing_batch_context(conn, batch_id: int, platform_code: str, target_table: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT platform_code, target_table, shop_mapping_status
            FROM ods.ods_file_ingest_log
            WHERE batch_id = %s
            """,
            (batch_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"导入批次不存在：batch_id={batch_id}")
    if row[0] != platform_code or row[1] != target_table or row[2] != "mapped":
        raise ValueError(
            f"导入批次上下文不匹配：batch_id={batch_id}, platform={row[0]}, target={row[1]}, mapping={row[2]}"
        )


def reject_duplicate_successful_file(
    conn,
    *,
    platform_code: str,
    shop_identity_key: str,
    data_domain: str,
    target_table: str,
    source_sheet_name: str,
    file_hash: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT batch_id
            FROM ods.ods_file_ingest_log
            WHERE platform_code = %s
              AND shop_identity_key = %s
              AND data_domain = %s
              AND target_table = %s
              AND source_sheet_name = %s
              AND file_hash = %s
              AND ingest_status = 'success'
            ORDER BY batch_id
            LIMIT 1
            """,
            (platform_code, shop_identity_key, data_domain, target_table, source_sheet_name, file_hash),
        )
        row = cursor.fetchone()
    if row is not None:
        raise ValueError(f"相同文件已成功导入，拒绝创建重复批次：existing_batch_id={row[0]}")


def run_loader(config: OdsLoadConfig, description: str) -> None:
    parser = build_arg_parser(description)
    args = parser.parse_args()
    path = Path(args.file)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    suffix = path.suffix.lower()
    if suffix == ".csv":
        file_encoding, source_sheet_name, total_rows, header, data_rows = read_csv_rows(config, path)
    elif suffix in (".xlsx", ".xlsm"):
        file_encoding, source_sheet_name, total_rows, header, data_rows = read_excel_rows(config, path, args.sheet)
    elif suffix == ".xls":
        file_encoding, source_sheet_name, total_rows, header, data_rows = read_legacy_excel_rows(
            config,
            path,
            args.sheet,
        )
    else:
        raise ValueError(f"不支持的文件类型：{suffix}。请使用 .csv、.xls、.xlsx 或 .xlsm 文件。")

    header, applied_aliases = canonicalize_header(header, config.header_aliases)
    validate_header(
        header,
        config.expected_columns,
        strict_header=config.strict_header and not args.no_strict_header,
        optional_columns=config.optional_columns,
    )
    table_name = args.table or config.table_name

    conn = psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password)
    batch_id = args.batch_id
    inserted = 0
    backfilled = 0
    skipped = 0
    try:
        target_schema, target_table = split_table_name(table_name)
        if batch_id is None:
            if not args.shop_code:
                raise ValueError("新建导入批次必须传入 --shop-code，禁止以空店铺或静默default导入。")
            shop = resolve_shop_context(conn, config.platform_code, args.shop_code)
            file_hash = calculate_file_sha256(path)
            reject_duplicate_successful_file(
                conn,
                platform_code=config.platform_code,
                shop_identity_key=shop["shop_identity_key"],
                data_domain=config.data_domain,
                target_table=target_table,
                source_sheet_name=source_sheet_name,
                file_hash=file_hash,
            )
            batch_id = create_file_ingest_log(
                conn,
                platform_code=config.platform_code,
                platform_name=shop["platform_name"],
                shop_code=shop["shop_code"],
                shop_name=shop["shop_name"],
                shop_identity_key=shop["shop_identity_key"],
                shop_mapping_status="mapped",
                shop_mapping_source=args.shop_mapping_source,
                shop_mapping_message=(
                    f"导入前通过DIM校验；company_code={shop['company_code']}; "
                    f"company_name={shop['company_name']}"
                ),
                data_domain=config.data_domain,
                source_file_path=str(path.resolve()),
                source_file_name=path.name,
                file_hash=file_hash,
                file_size_bytes=path.stat().st_size,
                file_encoding=file_encoding,
                source_sheet_name=source_sheet_name,
                header_row_no=config.header_row_no,
                data_start_row_no=config.data_start_row_no,
                total_rows=total_rows,
                parsed_rows=len(data_rows),
                target_schema=target_schema,
                target_table=target_table,
            )
        else:
            validate_existing_batch_context(conn, batch_id, config.platform_code, target_table)
        rows = build_insert_rows(config, args, path, source_sheet_name, batch_id, header, data_rows)
        inserted, backfilled, skipped = insert_rows(
            conn, table_name, config.expected_columns, rows, args.batch_size, commit=False
        )
        if config.platform_code == "pdd" and target_table == "ods_pdd_settlement_raw":
            from common.report_sources import save_pdd_settlement_period
            save_pdd_settlement_period(conn, batch_id, path, file_encoding)
        finish_file_ingest_log(
            conn,
            batch_id=batch_id,
            ingest_status="success",
            parsed_rows=len(rows),
            success_rows=inserted,
            duplicate_rows=backfilled + skipped,
            failed_rows=0,
        )
    except Exception as exc:
        if batch_id is not None:
            # insert_rows 可能已经因为数据库约束失败使当前事务进入
            # aborted 状态；先回滚，才能把原始错误可靠写回导入日志，
            # 避免用 InFailedSqlTransaction 覆盖真正根因。
            conn.rollback()
            inserted = backfilled = skipped = 0
            finish_file_ingest_log(
                conn,
                batch_id=batch_id,
                ingest_status="failed",
                parsed_rows=len(data_rows),
                success_rows=inserted,
                duplicate_rows=backfilled + skipped,
                failed_rows=max(len(data_rows) - inserted - backfilled - skipped, 0),
                error_message=str(exc),
            )
        raise
    finally:
        conn.close()

    print(f"文件路径：{path}")
    print(f"导入批次ID：{batch_id}")
    print(f"来源工作表：{source_sheet_name}")
    if applied_aliases:
        print(
            "表头别名映射："
            + "; ".join(f"{source} -> {target}" for source, target in applied_aliases.items())
        )
    print(f"文件编码：{file_encoding or 'Excel文件无编码'}")
    print(f"解析到的非空数据行数：{len(data_rows)}")
    print(f"成功插入行数：{inserted}")
    print(f"重复但已回填批次信息行数：{backfilled}")
    print(f"重复且无需处理行数：{skipped}")
