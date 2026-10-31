#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""将公司产品编码Excel幂等导入统一商家编码映射DIM。"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path

import psycopg2
from openpyxl import load_workbook


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIM_SQL_FILES = [
    PROJECT_ROOT / "sql" / "dim" / "183_dim_influencer_product_category_postgres.sql",
    PROJECT_ROOT / "sql" / "dim" / "200_dim_company_product_code_mapping_postgres.sql",
    PROJECT_ROOT / "sql" / "dim" / "203_normalize_influencer_product_catalog_postgres.sql",
    PROJECT_ROOT / "sql" / "dim" / "204_enforce_product_code_one_to_one_postgres.sql",
    PROJECT_ROOT / "sql" / "dim" / "393_dim_product_source_mapping_postgres.sql",
    PROJECT_ROOT / "sql" / "dim" / "427_refactor_company_product_identity_postgres.sql",
]
ALIAS_SQL_FILE = PROJECT_ROOT / "sql" / "dim" / "428_seed_company_product_alias_rules_postgres.sql"
DEFAULT_FILE = PROJECT_ROOT / "data" / "产品分类" / "产品编码.xlsx"
DEFAULT_SHEET = "产品编码"
CODE_TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", re.IGNORECASE)


def _clean_text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _normalize_code_pattern(code: str, role: str) -> tuple[str, str, str, str]:
    """Return quantity-free company code, display pattern, prefix and rule.

    The workbook is company master data. A trailing X or integer is a quantity
    placeholder/sample, never a separate product identity.
    """
    del role  # Packaging role remains audit metadata, not parsing identity.
    code = code.upper().strip()
    if code.endswith("-X"):
        alias_code = code[:-2]
    else:
        alias_code = re.sub(r"-[1-9][0-9]*$", "", code)
    return alias_code, f"{alias_code}-X", f"{alias_code}-", "suffix_quantity"


def _stable_code(prefix: str, *parts: str) -> str:
    normalized = "|".join(part.strip().lower() for part in parts)
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}{digest}"


def parse_product_code_workbook(
    file_path: str | Path,
    sheet_name: str = DEFAULT_SHEET,
) -> list[dict[str, object]]:
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"产品编码文件不存在：{path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet_name not in workbook.sheetnames:
            raise ValueError(
                f"产品编码文件缺少Sheet“{sheet_name}”，实际Sheet：{', '.join(workbook.sheetnames)}"
            )
        sheet = workbook[sheet_name]
        headers = [
            _clean_text(cell.value)
            for cell in next(sheet.iter_rows(min_row=1, max_row=1))
        ]
        required_headers = {"一级分类", "产品分类（二级）", "产品名称", "盒装对应编码"}
        missing = sorted(required_headers - set(headers))
        if missing:
            raise ValueError(f"产品编码文件缺少必需表头：{', '.join(missing)}")
        header_index = {name: headers.index(name) for name in headers if name}
        code_columns = [("box", "盒装对应编码")]
        if "对应1小袋编码" in header_index:
            code_columns.append(("sachet", "对应1小袋编码"))

        mappings_by_pattern: dict[str, dict[str, object]] = {}
        for row_no, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
            values = list(row)
            source_category = (
                _clean_text(values[header_index["产品分类"]])
                if "产品分类" in header_index
                else None
            )
            large_category = _clean_text(values[header_index["一级分类"]])
            category_l2 = _clean_text(values[header_index["产品分类（二级）"]])
            product_name = _clean_text(values[header_index["产品名称"]])
            if not any((large_category, category_l2, product_name)):
                continue
            if not large_category or not category_l2 or not product_name:
                raise ValueError(
                    f"第{row_no}行必须同时填写一级分类、二级分类和产品名称"
                )

            for configured_role, column_name in code_columns:
                code_cell = _clean_text(values[header_index[column_name]])
                if not code_cell or code_cell == "/":
                    continue
                codes = CODE_TOKEN_RE.findall(code_cell.upper())
                if not codes:
                    raise ValueError(f"第{row_no}行编码文本无法提取商家编码：{code_cell}")
                for raw_code in codes:
                    role = configured_role
                    if (
                        configured_role == "box"
                        and ("小袋" in product_name or "试喝" in product_name)
                    ):
                        role = "sachet"
                    company_code, pattern, prefix, match_rule = _normalize_code_pattern(raw_code, role)
                    mapping = {
                        "source_product_category": source_category,
                        "large_product_category": large_category,
                        "product_category_l2": category_l2,
                        "product_name": product_name,
                        "product_id": _stable_code(
                            "PRD-", large_category, category_l2, product_name
                        ),
                        "company_product_code": company_code,
                        "alias_code": company_code,
                        "quantity_position": "suffix",
                        "code_pattern": pattern,
                        "code_prefix": prefix,
                        "match_rule": match_rule,
                        "code_role": role,
                        "source_file_name": path.name,
                        "source_sheet_name": sheet_name,
                        "source_row_no": row_no,
                    }
                    existing = mappings_by_pattern.get(pattern)
                    if existing and (
                        existing["large_product_category"],
                        existing["product_name"],
                        existing["code_role"],
                        existing["match_rule"],
                    ) != (
                        mapping["large_product_category"],
                        mapping["product_name"],
                        mapping["code_role"],
                        mapping["match_rule"],
                    ):
                        raise ValueError(
                            f"编码模式{pattern}在Excel中映射冲突："
                            f"{existing['product_name']} / {mapping['product_name']}"
                        )
                    mappings_by_pattern[pattern] = mapping
        if not mappings_by_pattern:
            raise ValueError("产品编码文件没有可导入的商家编码")
        return [mappings_by_pattern[key] for key in sorted(mappings_by_pattern)]
    finally:
        workbook.close()


def upsert_product_code_mappings(cursor, mappings: list[dict[str, object]]) -> dict[str, int]:
    category_ids: dict[tuple[str, str | None], int] = {}
    for mapping in mappings:
        large_category = str(mapping["large_product_category"])
        category_l2 = str(mapping["product_category_l2"] or large_category)
        l1_code = _stable_code("CAT-L1-", large_category)
        cursor.execute(
            """
            SELECT category_id, maintenance_source
            FROM dim.dim_influencer_product_category
            WHERE category_code = %s
               OR (
                   category_level = 1
                   AND LOWER(BTRIM(category_name)) = LOWER(BTRIM(%s))
               )
            ORDER BY (category_code = %s) DESC, category_id
            LIMIT 1
            """,
            (l1_code, large_category, l1_code),
        )
        l1 = cursor.fetchone()
        if l1 is None:
            cursor.execute(
                """
                INSERT INTO dim.dim_influencer_product_category (
                    category_name, category_level, category_code,
                    maintenance_source, is_active
                )
                VALUES (%s, 1, %s, 'file', TRUE)
                RETURNING category_id, maintenance_source
                """,
                (large_category, l1_code),
            )
            l1 = cursor.fetchone()
        elif l1[1] == "file":
            cursor.execute(
                """
                UPDATE dim.dim_influencer_product_category
                SET category_name = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE category_id = %s
                """,
                (large_category, l1[0]),
            )
        l1_id = int(l1[0])
        category_ids[(large_category, None)] = l1_id

        l2_code = _stable_code("CAT-L2-", large_category, category_l2)
        cursor.execute(
            """
            SELECT category_id, maintenance_source
            FROM dim.dim_influencer_product_category
            WHERE category_code = %s
               OR (
                   category_level = 2
                   AND parent_category_id = %s
                   AND LOWER(BTRIM(category_name)) = LOWER(BTRIM(%s))
               )
            ORDER BY (category_code = %s) DESC, category_id
            LIMIT 1
            """,
            (l2_code, l1_id, category_l2, l2_code),
        )
        l2 = cursor.fetchone()
        if l2 is None:
            cursor.execute(
                """
                INSERT INTO dim.dim_influencer_product_category (
                    category_name, category_level, parent_category_id,
                    category_code, maintenance_source, is_active
                )
                VALUES (%s, 2, %s, %s, 'file', TRUE)
                RETURNING category_id, maintenance_source
                """,
                (category_l2, l1_id, l2_code),
            )
            l2 = cursor.fetchone()
        elif l2[1] == "file":
            cursor.execute(
                """
                UPDATE dim.dim_influencer_product_category
                SET category_name = %s,
                    parent_category_id = %s,
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE category_id = %s
                """,
                (category_l2, l1_id, l2[0]),
            )
        category_ids[(large_category, category_l2)] = int(l2[0])

    product_ids: dict[str, str] = {}
    for mapping in mappings:
        large_category = str(mapping["large_product_category"])
        category_l2 = str(mapping["product_category_l2"])
        product_name = str(mapping["product_name"])
        company_product_code = str(mapping["company_product_code"])
        expected_product_id = str(mapping["product_id"])
        category_id = category_ids[(large_category, category_l2)]
        cursor.execute(
            """
            SELECT p.product_id, p.maintenance_source
            FROM dim.dim_influencer_product p
            WHERE p.product_id = %s
               OR (
                   p.category_id = %s
                   AND LOWER(BTRIM(p.product_name)) = LOWER(BTRIM(%s))
               )
            ORDER BY (p.product_id = %s) DESC, p.product_id
            LIMIT 1
            """,
            (
                expected_product_id,
                category_id,
                product_name,
                expected_product_id,
            ),
        )
        product = cursor.fetchone()
        if product is None:
            cursor.execute(
                """
                INSERT INTO dim.dim_influencer_product (
                    product_id, category_id, company_product_code, product_name,
                    product_type, maintenance_source, is_active
                )
                VALUES (%s, %s, %s, %s, 'merchandise', 'file', TRUE)
                RETURNING product_id, maintenance_source
                """,
                (expected_product_id, category_id, company_product_code, product_name),
            )
            product = cursor.fetchone()
        elif product[1] == "file":
            cursor.execute(
                """
                UPDATE dim.dim_influencer_product
                SET category_id = %s,
                    company_product_code = %s,
                    product_name = %s,
                    product_type = 'merchandise',
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE product_id = %s
                """,
                (category_id, company_product_code, product_name, product[0]),
            )
        product_ids[str(mapping["code_pattern"])] = str(product[0])

    aliases = [str(mapping["alias_code"]) for mapping in mappings]
    cursor.execute(
        """
        SELECT alias_code
        FROM dim.dim_company_product_code_mapping
        WHERE mapping_source = 'manual'
          AND quantity_position = 'suffix'
          AND UPPER(BTRIM(alias_code)) = ANY(%s)
        """,
        ([alias.upper().strip() for alias in aliases],),
    )
    manual_patterns = {str(row[0]).upper().strip() for row in cursor.fetchall()}
    file_mappings = [
        mapping
        for mapping in mappings
        if str(mapping["alias_code"]).upper().strip() not in manual_patterns
    ]

    for mapping in file_mappings:
        pattern = str(mapping["code_pattern"])
        alias_code = str(mapping["alias_code"])
        cursor.execute(
            """
            SELECT mapping_id
            FROM dim.dim_company_product_code_mapping
            WHERE quantity_position = 'suffix'
              AND UPPER(BTRIM(alias_code)) = UPPER(BTRIM(%s))
            LIMIT 1
            """,
            (alias_code,),
        )
        current = cursor.fetchone()
        values = (
            mapping["source_product_category"],
            product_ids[pattern],
            mapping["large_product_category"],
            mapping["product_category_l2"],
            mapping["product_name"],
            alias_code,
            pattern,
            pattern,
            mapping["code_prefix"],
            mapping["match_rule"],
            mapping["code_role"],
            mapping["source_file_name"],
            mapping["source_sheet_name"],
            mapping["source_row_no"],
        )
        if current is None:
            cursor.execute(
                """
                INSERT INTO dim.dim_company_product_code_mapping (
                    source_product_category, product_id,
                    legacy_large_product_category, legacy_product_category_l2,
                    legacy_product_name, platform_code, shop_code,
                    source_product_code, code_pattern, source_code_pattern,
                    code_prefix, match_rule, code_role, mapping_source,
                    source_file_name, source_sheet_name, source_row_no,
                    is_active, alias_code, quantity_position, mapping_kind,
                    updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, '*', NULL, %s, %s, %s,
                    %s, %s, %s, 'file', %s, %s, %s, TRUE,
                    %s, 'suffix', 'company_code', NOW()
                )
                """,
                (*values, alias_code),
            )
        else:
            cursor.execute(
                """
                UPDATE dim.dim_company_product_code_mapping
                SET source_product_category = %s,
                    product_id = %s,
                    legacy_large_product_category = %s,
                    legacy_product_category_l2 = %s,
                    legacy_product_name = %s,
                    source_product_code = %s,
                    code_pattern = %s,
                    source_code_pattern = %s,
                    code_prefix = %s,
                    match_rule = %s,
                    code_role = %s,
                    mapping_source = 'file',
                    source_file_name = %s,
                    source_sheet_name = %s,
                    source_row_no = %s,
                    alias_code = %s,
                    quantity_position = 'suffix',
                    mapping_kind = 'company_code',
                    is_active = TRUE,
                    updated_at = NOW()
                WHERE mapping_id = %s
                  AND mapping_source <> 'manual'
                """,
                (*values, alias_code, current[0]),
            )

    cursor.execute(
        """
        UPDATE dim.dim_company_product_code_mapping
        SET is_active = FALSE,
            updated_at = NOW()
        WHERE mapping_source = 'file'
          AND mapping_kind = 'company_code'
          AND quantity_position = 'suffix'
          AND NOT (alias_code = ANY(%s))
          AND is_active
        """,
        (aliases,),
    )
    deactivated_count = cursor.rowcount

    cursor.execute(
        """
        UPDATE dim.dim_influencer_product p
        SET is_active = EXISTS (
                SELECT 1
                FROM dim.dim_company_product_code_mapping m
                WHERE m.product_id = p.product_id
                  AND m.is_active
            ),
            updated_at = NOW()
        WHERE p.maintenance_source = 'file'
        """
    )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT m.product_id)
        FROM dim.dim_company_product_code_mapping m
        JOIN dim.dim_influencer_product p ON p.product_id = m.product_id
        WHERE m.is_active
        """
    )
    active_mapping_count, active_product_count = cursor.fetchone()
    return {
        "source_mapping_count": len(mappings),
        "loaded_file_mapping_count": len(file_mappings),
        "manual_override_count": len(manual_patterns),
        "deactivated_file_mapping_count": deactivated_count,
        "active_mapping_count": active_mapping_count,
        "active_product_count": active_product_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入公司统一产品商家编码映射。")
    parser.add_argument("--file", default=str(DEFAULT_FILE))
    parser.add_argument("--sheet", default=DEFAULT_SHEET)
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    mappings = parse_product_code_workbook(args.file, args.sheet)
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with connection.cursor() as cursor:
            for sql_file in DIM_SQL_FILES:
                cursor.execute(sql_file.read_text(encoding="utf-8"))
            result = upsert_product_code_mappings(cursor, mappings)
            cursor.execute(ALIAS_SQL_FILE.read_text(encoding="utf-8"))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"源映射数：{result['source_mapping_count']}")
    print(f"文件映射写入数：{result['loaded_file_mapping_count']}")
    print(f"人工覆盖跳过数：{result['manual_override_count']}")
    print(f"本次停用旧文件映射数：{result['deactivated_file_mapping_count']}")
    print(f"当前启用映射数：{result['active_mapping_count']}")
    print(f"当前启用公司产品数：{result['active_product_count']}")


if __name__ == "__main__":
    main()
