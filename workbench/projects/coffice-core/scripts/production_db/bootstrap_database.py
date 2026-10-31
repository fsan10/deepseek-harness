"""Idempotently bring a non-test database to the current deployable state.

The bootstrap never creates, drops or connects for writes to ``mock_coffice``.
It applies the generated structure, compatibility migrations and approved
configuration seeds in one transaction so a failed step is fully rolled back.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg2

from .db_connection import add_connection_arguments, assert_not_source_database, connection_kwargs
from .migrate_schema import parse_steps


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = ROOT / "scripts/production_db/generated/001_schema.sql"

COMPATIBILITY_FILES = (
    "sql/common/370_iam_core_postgres.sql",
    "sql/common/370_xhs_settlement_multi_sheet_ingest_postgres.sql",
    "sql/common/371_dashboard_config_postgres.sql",
    "sql/common/372_seed_iam_permissions_and_dashboards_postgres.sql",
    "sql/ai/374_ai_configuration_catalog_postgres.sql",
    "sql/ai/375_ai_skill_permission_postgres.sql",
    "sql/ai/376_ai_conversation_feishu_audit_postgres.sql",
    "sql/ai/377_seed_ai_permissions_defaults_postgres.sql",
    "sql/ai/378_simplify_ai_daily_report_postgres.sql",
    "sql/ai/379_remove_ai_catalog_postgres.sql",
    "sql/ai/380_simplify_model_output_config_postgres.sql",
    "sql/ai/381_optimize_ai_daily_report_postgres.sql",
    # The verification relay is active in apps.feishu_ai and must be
    # bootstrapped explicitly; do not use the broad server --migrate path.
    "sql/ai/382_ai_verification_relay_postgres.sql",
    "sql/ai/383_ai_verification_challenge_type_postgres.sql",
    "sql/ai/433_ai_sms_forwarder_fallback_postgres.sql",
    "sql/ai/456_verification_answer_notice_postgres.sql",
    "sql/common/382_dashboard_origin_portability_postgres.sql",
    # The configuration center exposes the operating-budget pages and their
    # service writes to these tables. Keep their ETL key excluded from full
    # refresh, but create the empty config/DWD/DWS/ADS relations so the pages
    # remain usable in a fresh deployment.
    "sql/common/383_finance_operating_configuration_postgres.sql",
    "sql/common/384_dwd_finance_operating_configuration_detail_postgres.sql",
    "sql/common/385_dws_finance_operating_configuration_monthly_postgres.sql",
    "sql/ads/386_ads_finance_operating_configuration_monthly_postgres.sql",
    "sql/common/391_ingest_file_loader_diagnostics_postgres.sql",
    "sql/douyin/ods/392_ods_douyin_order_phone_text_postgres.sql",
    "sql/dim/393_dim_product_source_mapping_postgres.sql",
    "sql/dim/394_dim_company_influencer_postgres.sql",
    "sql/dim/395_migrate_company_influencer_legacy_postgres.sql",
    "sql/common/396_dws_influencer_identity_resolved_view_postgres.sql",
    "sql/ads/influencer_performance/397_alter_ads_influencer_identity_postgres.sql",
    "sql/common/398_operating_sales_product_code_observation_view_postgres.sql",
    "sql/common/399_finance_permission_granularity_postgres.sql",
    "sql/common/400_finance_configuration_console_postgres.sql",
    "sql/common/401_finance_configuration_merge_postgres.sql",
    "sql/common/402_dashboard_widget_config_postgres.sql",
    "sql/common/403_etl_deferred_status_postgres.sql",
    "sql/xhs/ods/415_ods_xhs_fund_ledger_raw_postgres.sql",
    "sql/wechat_channels/ods/419_ods_wechat_channels_order_discount_split_postgres.sql",
    "sql/common/420_platform_shop_company_admin_postgres.sql",
    "sql/common/421_platform_shop_company_current_context_postgres.sql",
    "sql/douyin/ods/422_mask_douyin_order_sensitive_fields_postgres.sql",
    "sql/common/423_normalize_dashboard_codes_postgres.sql",
    "sql/common/424_iam_user_password_view_postgres.sql",
    "sql/dim/426_dim_platform_fee_primary_category_auto_code_postgres.sql",
    "sql/common/430_automation_center_postgres.sql",
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


def reset_seed_sequences(cursor) -> None:
    """Make repeated static seeds safe for later identity inserts."""
    for table_name, column_name in SERIAL_COLUMNS:
        cursor.execute("SELECT pg_get_serial_sequence(%s, %s)", (table_name, column_name))
        sequence_name = cursor.fetchone()[0]
        if sequence_name is None:
            raise RuntimeError(f"初始化配置缺少自增序列：{table_name}.{column_name}")
        cursor.execute(f'SELECT MAX("{column_name}") FROM {table_name}')
        maximum = cursor.fetchone()[0]
        cursor.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence_name, maximum or 1, maximum is not None),
        )

CONFIG_SEED_FILES = (
    "sql/dim/32_dim_platform_shop_company_postgres.sql",
    "sql/dim/181_seed_bank_fund_classification_postgres.sql",
    "sql/dim/306_seed_douyin_platform_fee_mapping_postgres.sql",
    "sql/dim/313_seed_ks_platform_fee_mapping_postgres.sql",
    "sql/dim/318_seed_jd_platform_fee_mapping_postgres.sql",
    "sql/dim/331_seed_tmall_platform_fee_mapping_postgres.sql",
    "sql/dim/340_seed_pdd_wechat_xhs_platform_fee_mapping_postgres.sql",
    "sql/dim/425_xhs_appeal_adjustment_income_policy_postgres.sql",
    "sql/dim/369_dim_platform_fee_primary_category_postgres.sql",
    "scripts/production_db/generated/002_runtime_config_seed.sql",
    "sql/dim/373_dim_platform_finance_source_policy_postgres.sql",
)

EXISTING_DATABASE_UPGRADES = (
    ("dim.dim_platform_fee_mapping", "sql/dim/373_dim_platform_finance_source_policy_postgres.sql"),
    ("ods.ods_xhs_settlement_expense_raw", "sql/common/370_xhs_settlement_multi_sheet_ingest_postgres.sql"),
    (
        "ods.ods_wechat_channels_order_raw",
        "sql/wechat_channels/ods/419_ods_wechat_channels_order_discount_split_postgres.sql",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="幂等初始化或升级正式数据库")
    add_connection_arguments(parser)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    kwargs = connection_kwargs(args)
    requested_database = str(kwargs["dbname"])
    assert_not_source_database(requested_database)
    steps = parse_steps(args.schema_file.resolve().read_text(encoding="utf-8"))
    if not steps:
        raise RuntimeError("结构迁移文件没有 migration-step")

    connection = psycopg2.connect(**kwargs, application_name="coffice_production_bootstrap")
    current_step = "connection-check"
    applied: list[str] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            actual_database = cursor.fetchone()[0]
            assert_not_source_database(actual_database)
            if actual_database != requested_database:
                raise RuntimeError(f"连接数据库与请求不一致：{actual_database} != {requested_database}")

            # A database created by the 2026-08-06 migration has tables that
            # predate several columns used by indexes in the regenerated full
            # schema. Apply those ALTER migrations first only when the old
            # relation already exists; a brand-new database is created below.
            for relation_name, relative_path in EXISTING_DATABASE_UPGRADES:
                cursor.execute("SELECT to_regclass(%s)", (relation_name,))
                if cursor.fetchone()[0] is not None:
                    current_step = f"pre-upgrade:{relative_path}"
                    cursor.execute((ROOT / relative_path).read_text(encoding="utf-8"))
                    applied.append(relative_path)

            for current_step, sql_text in steps:
                cursor.execute(sql_text)
            applied.append(str(args.schema_file))

            for relative_path in COMPATIBILITY_FILES + CONFIG_SEED_FILES:
                current_step = relative_path
                cursor.execute((ROOT / relative_path).read_text(encoding="utf-8"))
                applied.append(relative_path)
            current_step = "reset-seeded-sequences"
            reset_seed_sequences(cursor)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        raise RuntimeError(f"正式库初始化失败，步骤={current_step}: {exc}") from exc
    finally:
        connection.close()

    print(json.dumps({
        "database": requested_database,
        "schema_steps": len(steps),
        "files": applied,
        "status": "success",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
