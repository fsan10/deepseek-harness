"""Clear test-only facts and runtime history while preserving configuration.

This command is deliberately restricted to the ``mock_coffice`` database.  It
does not use ``CASCADE``: every table to be truncated must be in the explicit
cleanup categories, and foreign keys from any non-cleanup table cause an
abort.  The whole operation runs in one transaction so a failed validation
rolls back the cleanup.
"""

from __future__ import annotations

import argparse
import json

import psycopg2
from psycopg2 import sql

from .db_connection import add_connection_arguments


TEST_DATABASE = "mock_coffice"
DERIVED_SCHEMAS = ("dwd", "dws", "ads")

ACTIVE_ODS_TABLES = (
    "ods.ods_bank_statement",
    "ods.ods_douyin_fund_raw",
    "ods.ods_douyin_order_raw",
    "ods.ods_douyin_qianchuan_finance_raw",
    "ods.ods_douyin_settlement_raw",
    "ods.ods_jd_fund_raw",
    "ods.ods_jd_order_raw",
    "ods.ods_jd_settlement_raw",
    "ods.ods_jd_tong_promotion_expense_raw",
    "ods.ods_jd_union_promotion_expense_raw",
    "ods.ods_ks_fund_raw",
    "ods.ods_ks_order_raw",
    "ods.ods_ks_settlement_raw",
    "ods.ods_pdd_order_raw",
    "ods.ods_pdd_promotion_expense_raw",
    "ods.ods_pdd_settlement_raw",
    "ods.ods_tmall_aggregate_fund_raw",
    "ods.ods_tmall_alipay_fund_raw",
    "ods.ods_tmall_order_raw",
    "ods.ods_tmall_settlement_expense_raw",
    "ods.ods_tmall_settlement_income_raw",
    "ods.ods_tmall_taobao_union_promotion_expense_raw",
    "ods.ods_tmall_wanxiangtai_promotion_expense_raw",
    "ods.ods_wechat_channels_order_raw",
    "ods.ods_wechat_channels_settlement_raw",
    "ods.ods_xhs_fund_raw",
    "ods.ods_xhs_fund_ledger_raw",
    "ods.ods_xhs_order_raw",
    "ods.ods_xhs_settlement_expense_raw",
    "ods.ods_xhs_settlement_income_raw",
)

LEGACY_ODS_TABLES = (
    "ods.ods_tmall_fund_raw",
    "ods.ods_tmall_order_raw_legacy_20260728_164401",
)

IMPORT_AND_RUNTIME_TABLES = (
    "ods.ods_file_ingest_log",
    "fund.import_record",
    "fund.operation_log",
    "ops.ingest_run",
    "ops.ingest_file_task",
    "ops.ingest_file_task_batch",
    "ops.etl_run",
    "ops.etl_task",
    "ops.operation_log",
    "ops.worker_heartbeat",
    "ops.refresh_watermark",
    "iam.user_session",
    "iam.login_attempt",
    "iam.audit_log",
    "ai.conversation",
    "ai.message",
    "ai.tool_execution",
    "ai.query_audit",
    "ai.daily_report_run",
    "ai.feishu_event_dedup",
    "ai.verification_challenge",
)

PRESERVED_TABLES = (
    # DIM and mapping data used by loaders and metrics.
    "dim.dim_platform_shop_company",
    "dim.dim_expense_type",
    "dim.dim_account_entry",
    "dim.dim_account_entry_expense_type",
    "dim.dim_business_owner",
    "dim.dim_business_gmv_target_monthly",
    "dim.dim_company_influencer",
    "dim.dim_company_influencer_source_mapping",
    "dim.dim_company_influencer_business_assignment_monthly",
    "dim.dim_influencer_business_assignment_monthly",
    "dim.dim_influencer_product_category",
    "dim.dim_influencer_product",
    "dim.dim_company_product_code_mapping",
    "dim.dim_platform_fee_primary_category",
    "dim.dim_platform_fee_mapping",
    # Dashboard and operating configuration.
    "config.dashboard",
    "config.dashboard_widget",
    "config.finance_budget_monthly",
    "config.finance_marketing_budget_change_history",
    "config.finance_marketing_expense_detail",
    "config.finance_marketing_expense_type",
    "config.finance_promotion_budget_adjustment",
    "config.finance_promotion_recharge_detail",
    "config.finance_shop_plan_monthly",
    # AI configuration.
    "ai.provider_config",
    "ai.data_source",
    "ai.feishu_app",
    "ai.prompt_template",
    "ai.prompt_template_version",
    "ai.verification_relay_config",
    # IAM configuration and scheduled-operation configuration.
    "iam.department",
    "iam.department_permission",
    "iam.permission_resource",
    "iam.role",
    "iam.role_permission",
    "iam.user_account",
    "iam.user_permission",
    "iam.user_role",
    "ops.etl_nightly_schedule",
)

PRESERVED_VIEWS = (
    "common.v_ingest_batch_shop_context",
    "common.v_operating_sales_product_code_observation",
    "dwd.v_statement_split_detail",
    "dws.v_influencer_identity_resolved",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="清理mock_coffice测试库业务事实和运行历史")
    add_connection_arguments(parser)
    parser.add_argument("--execute", action="store_true", help="提交清理；默认仅检查并显示计划")
    parser.add_argument("--keep-legacy", action="store_true", help="保留两张已停用的天猫历史ODS表")
    return parser


def split_table(table_name: str) -> tuple[str, str]:
    schema_name, relation_name = table_name.split(".", 1)
    return schema_name, relation_name


def identifier(table_name: str) -> sql.Composed:
    return sql.Identifier(*split_table(table_name))


def relation_names(cursor, schemas: tuple[str, ...] | None = None) -> set[str]:
    if schemas is None:
        cursor.execute(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p')
              AND n.nspname NOT LIKE 'pg_%%'
              AND n.nspname <> 'information_schema'
            """
        )
    else:
        cursor.execute(
            """
            SELECT n.nspname || '.' || c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname=ANY(%s)
            """,
            (list(schemas),),
        )
    return {row[0] for row in cursor.fetchall()}


def derived_tables(cursor) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT n.nspname || '.' || c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE c.relkind IN ('r','p') AND n.nspname=ANY(%s)
        ORDER BY n.nspname,c.relname
        """,
        (list(DERIVED_SCHEMAS),),
    )
    return tuple(row[0] for row in cursor.fetchall())


def table_counts(cursor, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_name in tables:
        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {};").format(identifier(table_name)))
        counts[table_name] = int(cursor.fetchone()[0])
    return counts


def active_connections(cursor) -> list[dict[str, object]]:
    cursor.execute(
        """
        SELECT pid, COALESCE(application_name, '') AS application_name, state
        FROM pg_stat_activity
        WHERE datname=current_database()
          AND pid <> pg_backend_pid()
          AND state IN ('active','idle in transaction','idle in transaction (aborted)')
        ORDER BY pid
        """
    )
    return [
        {"pid": int(row[0]), "application_name": row[1], "state": row[2]}
        for row in cursor.fetchall()
    ]


def active_work(cursor) -> list[dict[str, object]]:
    checks = (
        ("ops.ingest_run", "status", ("processing",)),
        ("ops.ingest_file_task", "status", ("processing",)),
        ("ops.etl_run", "status", ("running",)),
        ("ops.etl_task", "status", ("running",)),
    )
    result: list[dict[str, object]] = []
    for table_name, status_column, statuses in checks:
        cursor.execute(
            sql.SQL("SELECT {},COUNT(*) FROM {} WHERE {}=ANY(%s) GROUP BY {} ORDER BY {};").format(
                sql.Identifier(status_column),
                identifier(table_name),
                sql.Identifier(status_column),
                sql.Identifier(status_column),
                sql.Identifier(status_column),
            ),
            (list(statuses),),
        )
        result.extend(
            {"table": table_name, "status": row[0], "row_count": int(row[1])}
            for row in cursor.fetchall()
        )
    return result


def foreign_key_violations(cursor, cleanup_tables: set[str]) -> list[dict[str, str]]:
    cursor.execute(
        """
        SELECT child_ns.nspname || '.' || child.relname AS child_table,
               parent_ns.nspname || '.' || parent.relname AS parent_table,
               con.conname
        FROM pg_constraint con
        JOIN pg_class child ON child.oid=con.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid=child.relnamespace
        JOIN pg_class parent ON parent.oid=con.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
        WHERE con.contype='f'
          AND (
              (child_ns.nspname || '.' || child.relname)=ANY(%s)
              OR (parent_ns.nspname || '.' || parent.relname)=ANY(%s)
          )
        ORDER BY child_table,parent_table,con.conname
        """,
        (list(cleanup_tables), list(cleanup_tables)),
    )
    violations = []
    for child_table, parent_table, constraint_name in cursor.fetchall():
        if parent_table in cleanup_tables and child_table not in cleanup_tables:
            violations.append(
                {
                    "child_table": child_table,
                    "parent_table": parent_table,
                    "constraint": constraint_name,
                }
            )
    return violations


def validate_plan(cursor, cleanup_tables: tuple[str, ...]) -> dict[str, object]:
    cursor.execute("SELECT current_database()")
    database_name = cursor.fetchone()[0]
    if database_name != TEST_DATABASE:
        raise RuntimeError(f"安全拒绝：当前数据库不是{TEST_DATABASE}，实际为{database_name}")

    all_tables = relation_names(cursor)
    missing = sorted((set(cleanup_tables) | set(PRESERVED_TABLES)) - all_tables)
    if missing:
        raise RuntimeError("清理/保护白名单中存在不存在的表：" + ", ".join(missing))
    collisions = sorted(set(cleanup_tables).intersection(PRESERVED_TABLES))
    if collisions:
        raise RuntimeError("清理表和保护表重叠：" + ", ".join(collisions))

    connections = active_connections(cursor)
    if connections:
        raise RuntimeError("数据库仍有活动或未提交事务连接：" + json.dumps(connections, ensure_ascii=False))
    work = active_work(cursor)
    if work:
        raise RuntimeError("仍有导入/ETL正在运行：" + json.dumps(work, ensure_ascii=False))

    cleanup_set = set(cleanup_tables)
    violations = foreign_key_violations(cursor, cleanup_set)
    if violations:
        raise RuntimeError("存在未纳入清理白名单的外键子表：" + json.dumps(violations, ensure_ascii=False))

    return {
        "database": database_name,
        "cleanup_table_count": len(cleanup_tables),
        "preserved_table_count": len(PRESERVED_TABLES),
        "preserved_views": list(PRESERVED_VIEWS),
    }


def clear_tables(cursor, cleanup_tables: tuple[str, ...]) -> None:
    cursor.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY").format(
            sql.SQL(", ").join(identifier(table_name) for table_name in cleanup_tables)
        )
    )


def main() -> None:
    args = build_parser().parse_args()
    requested_database = str(args.dbname or "")
    if requested_database.strip().lower() != TEST_DATABASE:
        raise RuntimeError(f"安全拒绝：清理脚本只允许--dbname {TEST_DATABASE}")

    connection = psycopg2.connect(
        **{
            "host": args.host,
            "port": args.port,
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        },
        application_name="mock_coffice_test_data_cleanup",
    )
    committed = False
    try:
        connection.set_session(autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='120s'")
            derived = derived_tables(cursor)
            cleanup_tables = tuple(
                dict.fromkeys(
                    list(derived)
                    + list(ACTIVE_ODS_TABLES)
                    + ([] if args.keep_legacy else list(LEGACY_ODS_TABLES))
                    + list(IMPORT_AND_RUNTIME_TABLES)
                )
            )
            plan = validate_plan(cursor, cleanup_tables)
            before_clear = table_counts(cursor, cleanup_tables)
            before_preserved = table_counts(cursor, PRESERVED_TABLES)

            if not args.execute:
                connection.rollback()
                print(json.dumps({
                    **plan,
                    "execute": False,
                    "planned_rows": sum(before_clear.values()),
                    "cleanup_tables": list(cleanup_tables),
                }, ensure_ascii=False))
                return

            clear_tables(cursor, cleanup_tables)
            after_clear = table_counts(cursor, cleanup_tables)
            after_preserved = table_counts(cursor, PRESERVED_TABLES)
            nonempty = {name: count for name, count in after_clear.items() if count}
            changed_preserved = {
                name: {"before": before_preserved[name], "after": after_preserved[name]}
                for name in PRESERVED_TABLES
                if before_preserved[name] != after_preserved[name]
            }
            if nonempty:
                raise RuntimeError("清理后仍有数据：" + json.dumps(nonempty, ensure_ascii=False))
            if changed_preserved:
                raise RuntimeError("保护表行数发生变化：" + json.dumps(changed_preserved, ensure_ascii=False))
            connection.commit()
            committed = True
            print(json.dumps({
                **plan,
                "execute": True,
                "committed": True,
                "cleared_rows": sum(before_clear.values()),
                "cleanup_tables": list(cleanup_tables),
                "preserved_row_counts": after_preserved,
            }, ensure_ascii=False))
    except Exception:
        if not committed:
            connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
