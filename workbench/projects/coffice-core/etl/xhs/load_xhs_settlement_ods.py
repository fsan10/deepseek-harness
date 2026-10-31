#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将一个小红书结算工作簿的两个业务工作表原样分流至 ODS。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ETL_ROOT = Path(__file__).resolve().parents[1]
if str(ETL_ROOT) not in sys.path:
    sys.path.insert(0, str(ETL_ROOT))

import psycopg2  # noqa: E402
from common.ingest_log import (  # noqa: E402
    calculate_file_sha256,
    create_file_ingest_log,
    finish_file_ingest_log,
    split_table_name,
)
from common.ods_file_loader import (  # noqa: E402
    OdsLoadConfig,
    build_arg_parser,
    build_insert_rows,
    canonicalize_header,
    insert_rows,
    read_excel_rows,
    reject_duplicate_successful_file,
    resolve_shop_context,
    validate_header,
)
from xhs.load_xhs_settlement_expense_ods import CONFIG as EXPENSE_CONFIG  # noqa: E402
from xhs.load_xhs_settlement_income_ods import CONFIG as INCOME_CONFIG  # noqa: E402


@dataclass(frozen=True)
class SheetPlan:
    config: OdsLoadConfig
    sheet_name: str
    file_encoding: str | None
    total_rows: int
    header: list[str]
    data_rows: list[tuple[int, list[str | None]]]


SHEET_CONFIGS: tuple[tuple[str, OdsLoadConfig], ...] = (
    ("订单结算", INCOME_CONFIG),
    ("其他服务款", EXPENSE_CONFIG),
)


def parse_workbook(path: Path, *, no_strict_header: bool) -> list[SheetPlan]:
    if path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("小红书结算仅支持 .xlsx 或 .xlsm 文件。")
    plans: list[SheetPlan] = []
    for sheet_name, config in SHEET_CONFIGS:
        file_encoding, resolved_sheet, total_rows, header, data_rows = read_excel_rows(
            config, path, sheet_name
        )
        header, _ = canonicalize_header(header, config.header_aliases)
        validate_header(
            header,
            config.expected_columns,
            strict_header=config.strict_header and not no_strict_header,
            optional_columns=config.optional_columns,
        )
        if resolved_sheet != sheet_name:
            raise ValueError(f"工作表名称异常：期望 {sheet_name}，实际 {resolved_sheet}")
        plans.append(SheetPlan(config, resolved_sheet, file_encoding, total_rows, header, data_rows))
    return plans


def import_workbook(args) -> list[tuple[str, int, int, int, int]]:
    path = Path(args.file)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")
    if args.batch_id is not None:
        raise ValueError("小红书结算会为两个工作表分别创建批次，不支持 --batch-id。")
    if not args.shop_code:
        raise ValueError("新建导入批次必须传入 --shop-code，禁止以空店铺或静默default导入。")

    plans = parse_workbook(path, no_strict_header=args.no_strict_header)
    connection = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password
    )
    try:
        with connection:
            shop = resolve_shop_context(connection, "xhs", args.shop_code)
            file_hash = calculate_file_sha256(path)
            for plan in plans:
                _, target_table = split_table_name(plan.config.table_name)
                reject_duplicate_successful_file(
                    connection,
                    platform_code="xhs",
                    shop_identity_key=shop["shop_identity_key"],
                    data_domain="settlement",
                    target_table=target_table,
                    source_sheet_name=plan.sheet_name,
                    file_hash=file_hash,
                )

            results: list[tuple[str, int, int, int, int]] = []
            for plan in plans:
                target_schema, target_table = split_table_name(plan.config.table_name)
                batch_id = create_file_ingest_log(
                    connection,
                    platform_code="xhs",
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
                    data_domain="settlement",
                    source_file_path=str(path.resolve()),
                    source_file_name=path.name,
                    file_hash=file_hash,
                    file_size_bytes=path.stat().st_size,
                    file_encoding=plan.file_encoding,
                    source_sheet_name=plan.sheet_name,
                    header_row_no=plan.config.header_row_no,
                    data_start_row_no=plan.config.data_start_row_no,
                    total_rows=plan.total_rows,
                    parsed_rows=len(plan.data_rows),
                    target_schema=target_schema,
                    target_table=target_table,
                    commit=False,
                )
                rows = build_insert_rows(
                    plan.config, args, path, plan.sheet_name, batch_id, plan.header, plan.data_rows
                )
                inserted, backfilled, skipped = insert_rows(
                    connection,
                    plan.config.table_name,
                    plan.config.expected_columns,
                    rows,
                    args.batch_size,
                    commit=False,
                )
                finish_file_ingest_log(
                    connection,
                    batch_id=batch_id,
                    ingest_status="success",
                    parsed_rows=len(rows),
                    success_rows=inserted,
                    duplicate_rows=backfilled + skipped,
                    failed_rows=0,
                    commit=False,
                )
                results.append((plan.sheet_name, batch_id, inserted, backfilled, skipped))
        return results
    finally:
        connection.close()


def main() -> int:
    parser = build_arg_parser("将小红书结算工作簿按工作表自动分流导入两个 ODS 原始表。")
    args = parser.parse_args()
    try:
        results = import_workbook(args)
    except Exception as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1
    print("导入批次ID：" + ",".join(str(batch_id) for _, batch_id, *_ in results))
    for sheet_name, batch_id, inserted, backfilled, skipped in results:
        print(
            f"工作表 {sheet_name}：batch_id={batch_id}，成功插入={inserted}，"
            f"回填={backfilled}，重复={skipped}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
