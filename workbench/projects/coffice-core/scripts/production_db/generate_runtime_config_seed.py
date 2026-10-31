"""Generate a reviewable seed snapshot for web-console runtime configuration.

The generator is deliberately read-only and accepts only ``mock_coffice`` as
its source.  The generated SQL contains no ODS, metric, upload, task, or audit
rows.  It uses ``ON CONFLICT DO NOTHING`` so a later rerun cannot overwrite
configuration maintained in the production web console.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from .db_connection import PROTECTED_SOURCE_DATABASE, add_connection_arguments, connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "scripts" / "production_db" / "generated" / "002_runtime_config_seed.sql"

TABLES = (
    {
        "name": "dim.dim_business_owner",
        "columns": ("business_owner_id", "business_owner_name", "is_active"),
        "order_by": "business_owner_id",
    },
    {
        "name": "dim.dim_influencer_business_assignment_monthly",
        "columns": (
            "platform_code",
            "platform_name",
            "influencer_id",
            "influencer_name",
            "effective_month",
            "business_owner_id",
            "assignment_source",
            "source_file_name",
            "source_shop_names",
            "note",
            "is_active",
        ),
        "order_by": "platform_code, influencer_id, effective_month",
    },
    {
        "name": "dim.dim_business_gmv_target_monthly",
        "columns": ("target_month", "business_owner_id", "gmv_target", "note"),
        "order_by": "target_month, business_owner_id",
    },
    {
        "name": "dim.dim_influencer_product_category",
        "columns": (
            "category_id",
            "category_name",
            "is_active",
            "category_level",
            "parent_category_id",
            "category_code",
            "maintenance_source",
        ),
        "order_by": "category_level, category_id",
    },
    {
        "name": "dim.dim_influencer_product",
        "columns": (
            "product_id",
            "category_id",
            "product_name",
            "is_active",
            "maintenance_source",
        ),
        "order_by": "product_id",
    },
    {
        "name": "dim.dim_company_product_code_mapping",
        "columns": (
            "mapping_id",
            "platform_code",
            "shop_code",
            "source_product_code",
            "product_id",
            "source_product_category",
            "legacy_large_product_category",
            "legacy_product_category_l2",
            "legacy_product_name",
            "code_pattern",
            "source_code_pattern",
            "code_prefix",
            "match_rule",
            "code_role",
            "mapping_source",
            "source_file_name",
            "source_sheet_name",
            "source_row_no",
            "is_active",
        ),
        "order_by": "mapping_id",
    },
)

# These tables receive explicit surrogate IDs in the approved snapshot.  Keep
# their sequences aligned when the generated SQL is replayed against a fresh
# database (or replayed after a partial initialization).  Product IDs are
# stable text keys and therefore intentionally absent from this list.
EXPLICIT_ID_SEQUENCES = (
    ("dim.dim_business_owner", "business_owner_id"),
    ("dim.dim_influencer_product_category", "category_id"),
    ("dim.dim_company_product_code_mapping", "mapping_id"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成经营配置中心运行配置 seed SQL")
    add_connection_arguments(parser, url_env="TEST_DATABASE_URL")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def render_insert(cursor, table: dict, rows: list[tuple]) -> str:
    columns = table["columns"]
    column_sql = ", ".join(quote_ident(column) for column in columns)
    values = []
    placeholder = "(" + ", ".join(["%s"] * len(columns)) + ")"
    for row in rows:
        values.append(cursor.mogrify(placeholder, row).decode("utf-8"))
    if not values:
        return f"-- {table['name']}: 0 rows\n"
    return (
        f"-- {table['name']}: {len(rows)} rows\n"
        f"INSERT INTO {table['name']} ({column_sql})\nVALUES\n    "
        + ",\n    ".join(values)
        + "\nON CONFLICT DO NOTHING;\n"
    )


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    connection = psycopg2.connect(
        **kwargs,
        application_name="coffice_runtime_config_seed_generator",
    )
    connection.set_session(readonly=True, autocommit=True)
    row_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    sections: list[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_database = cursor.fetchone()[0]
            if actual_database.lower() != PROTECTED_SOURCE_DATABASE:
                raise RuntimeError(
                    "安全拒绝：配置快照只能从只读 mock_coffice 生成，"
                    f"当前数据库为 {actual_database}"
                )
            for table in TABLES:
                columns = ", ".join(quote_ident(column) for column in table["columns"])
                cursor.execute(
                    f"SELECT {columns} FROM {table['name']} ORDER BY {table['order_by']}"
                )
                rows = cursor.fetchall()
                if table["name"] == "dim.dim_business_gmv_target_monthly":
                    # A test operator may have entered a real target after
                    # the approved zero-target snapshot was created.  Never
                    # promote that business value to a fresh production DB;
                    # retain only the required 0 元 initialization rows and
                    # report how many non-zero rows were intentionally left
                    # out.
                    nonzero_count = sum(row[2] != 0 for row in rows)
                    if nonzero_count:
                        skipped_counts[table["name"]] = nonzero_count
                        rows = [row for row in rows if row[2] == 0]
                row_counts[table["name"]] = len(rows)
                sections.append(render_insert(cursor, table, rows))
    finally:
        connection.close()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sql = """-- Generated by scripts/production_db/generate_runtime_config_seed.py.
-- Approved initialization only: business owners, influencer assignments,
-- zero-value GMV targets, product categories, products and merchant-code mappings.
-- No ODS, business facts, ETL outputs, task history or operation logs are included.
-- Re-execution never overwrites web-maintained configuration.

""" + "\n".join(sections)
    sql += "\n\n-- Synchronize explicit-ID sequences for subsequent web-console inserts.\n"
    for table_name, column_name in EXPLICIT_ID_SEQUENCES:
        sql += f"""SELECT setval(
    pg_get_serial_sequence('{table_name}', '{column_name}'),
    COALESCE((SELECT MAX(\"{column_name}\") FROM {table_name}), 1),
    (SELECT COUNT(*) > 0 FROM {table_name})
);\n"""
    output.write_text(sql, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "source_database": PROTECTED_SOURCE_DATABASE,
                "output": str(output),
                "rows": row_counts,
                "skipped_nonzero_rows": skipped_counts,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
