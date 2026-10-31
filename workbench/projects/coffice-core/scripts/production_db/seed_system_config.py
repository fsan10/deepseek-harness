"""Seed approved static dictionaries and required web-console configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from .db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs


ROOT = Path(__file__).resolve().parents[2]
SEED_FILES = (
    "sql/dim/32_dim_platform_shop_company_postgres.sql",
    "sql/dim/181_seed_bank_fund_classification_postgres.sql",
    "sql/dim/306_seed_douyin_platform_fee_mapping_postgres.sql",
    "sql/dim/313_seed_ks_platform_fee_mapping_postgres.sql",
    "sql/dim/318_seed_jd_platform_fee_mapping_postgres.sql",
    "sql/dim/331_seed_tmall_platform_fee_mapping_postgres.sql",
    "sql/dim/340_seed_pdd_wechat_xhs_platform_fee_mapping_postgres.sql",
    "sql/dim/369_dim_platform_fee_primary_category_postgres.sql",
    "sql/dim/426_dim_platform_fee_primary_category_auto_code_postgres.sql",
    "scripts/production_db/generated/002_runtime_config_seed.sql",
)

SERIAL_COLUMNS = (
    ("dim.dim_platform_shop_company", "shop_company_sk"),
    ("dim.dim_expense_type", "id"),
    ("dim.dim_account_entry", "id"),
    ("dim.dim_platform_fee_mapping", "mapping_id"),
    ("dim.dim_business_owner", "business_owner_id"),
    ("dim.dim_influencer_product_category", "category_id"),
    ("dim.dim_company_product_code_mapping", "mapping_id"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="写入正式库必要静态字典")
    add_connection_arguments(parser)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    assert_not_source_database(str(kwargs["dbname"]))
    connection = psycopg2.connect(**kwargs, application_name="coffice_production_system_seed")
    current_file = "connection-check"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_db = cursor.fetchone()[0]
            assert_not_source_database(actual_db)
            for current_file in SEED_FILES:
                cursor.execute((ROOT / current_file).read_text(encoding="utf-8"))
            # INSERT ... ON CONFLICT still consumes sequence values. Reset each
            # approved dictionary sequence to the current maximum so rerunning
            # the seed is data- and sequence-idempotent.
            for table_name, column_name in SERIAL_COLUMNS:
                cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (table_name, column_name))
                sequence_name = cursor.fetchone()[0]
                cursor.execute(f"SELECT MAX(\"{column_name}\") FROM {table_name}")
                maximum = cursor.fetchone()[0]
                if maximum is None:
                    cursor.execute("SELECT setval(%s::regclass, 1, false)", (sequence_name,))
                else:
                    cursor.execute("SELECT setval(%s::regclass, %s, true)", (sequence_name, maximum))
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise RuntimeError(f"初始化配置失败，文件={current_file}: {exc}") from exc
    finally:
        connection.close()
    print(json.dumps({"database": kwargs["dbname"], "seed_files": list(SEED_FILES), "status": "success"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
