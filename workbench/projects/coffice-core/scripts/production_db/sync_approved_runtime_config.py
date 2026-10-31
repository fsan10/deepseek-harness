"""Synchronize only approved runtime configuration from test to production.

No ODS, DWD, DWS, ADS, upload, ETL, conversation, audit or login history is
read or written.  Encrypted AI credentials can be transferred in memory; they
are never printed or written to a file.
"""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import unquote, urlparse

import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor, Json

from .db_connection import PROTECTED_SOURCE_DATABASE, assert_not_source_database, kwargs_from_url


DIM_TABLES = (
    "dim.dim_platform_shop_company",
    "dim.dim_expense_type",
    "dim.dim_account_entry",
    "dim.dim_account_entry_expense_type",
    "dim.dim_business_owner",
    "dim.dim_company_influencer",
    "dim.dim_company_influencer_source_mapping",
    "dim.dim_company_influencer_business_assignment_monthly",
    "dim.dim_influencer_business_assignment_monthly",
    "dim.dim_business_gmv_target_monthly",
    "dim.dim_platform_fee_primary_category",
    "dim.dim_platform_fee_mapping",
    "dim.dim_influencer_product_category",
    "dim.dim_influencer_product",
    "dim.dim_company_product_code_mapping",
)

NATURAL_KEY_TABLES = {
    "dim.dim_platform_fee_mapping": (("platform_code", "source_document_type", "secondary_category_code"), {"mapping_id"}),
    "dim.dim_company_influencer_source_mapping": (("platform_code", "source_influencer_id"), {"mapping_id"}),
    "config.finance_marketing_expense_type": (("expense_type_code",), {"expense_type_id"}),
}

FINANCE_CONFIGURATION_TABLES = (
    "config.finance_budget_monthly",
    "config.finance_shop_plan_monthly",
    "config.finance_promotion_recharge_detail",
    "config.finance_promotion_budget_adjustment",
    "config.finance_marketing_expense_detail",
    "config.finance_marketing_budget_change_history",
    "config.finance_marketing_expense_type",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同步正式运行必需配置，不复制业务事实和历史")
    parser.add_argument("--source-url", default=os.getenv("TEST_DATABASE_URL"))
    parser.add_argument("--target-url", default=os.getenv("PRODUCTION_DATABASE_URL"))
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument("--source-db", default=PROTECTED_SOURCE_DATABASE)
    parser.add_argument("--target-db", default="coffice_production")
    parser.add_argument("--include-encrypted-ai-config", action="store_true")
    parser.add_argument(
        "--include-gmv-targets",
        action="store_true",
        help="同步DIM中的当前GMV目标；不传时仅接受0元初始化记录",
    )
    parser.add_argument("--grant-ai-reader", action="store_true")
    return parser


def connection_kwargs(url: str | None, args: argparse.Namespace, database: str) -> dict:
    if url:
        return kwargs_from_url(url)
    return {
        "host": args.host,
        "port": args.port,
        "dbname": database,
        "user": args.user,
        "password": args.password,
    }


def split_table(name: str) -> tuple[str, str]:
    return tuple(name.split(".", 1))  # type: ignore[return-value]


def table_columns(cursor, table_name: str) -> list[str]:
    schema_name, relation_name = split_table(table_name)
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s AND is_generated='NEVER'
           ORDER BY ordinal_position""",
        (schema_name, relation_name),
    )
    return [row[0] for row in cursor.fetchall()]


def jsonb_columns(cursor, table_name: str) -> set[str]:
    schema_name, relation_name = split_table(table_name)
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema=%s AND table_name=%s AND udt_name='jsonb'""",
        (schema_name, relation_name),
    )
    return {row[0] for row in cursor.fetchall()}


def adapt_rows_for_database(cursor, table_name: str, columns: list[str], rows: list[list[object]]) -> list[list[object]]:
    """Adapt JSONB values returned by psycopg2 before executemany()."""
    json_columns = jsonb_columns(cursor, table_name)
    if not json_columns:
        return rows
    return [
        [Json(value) if column in json_columns and value is not None else value for column, value in zip(columns, row)]
        for row in rows
    ]


def primary_key_columns(cursor, table_name: str) -> list[str]:
    schema_name, relation_name = split_table(table_name)
    cursor.execute(
        """SELECT att.attname
           FROM pg_index idx
           JOIN pg_class cls ON cls.oid=idx.indrelid
           JOIN pg_namespace ns ON ns.oid=cls.relnamespace
           JOIN unnest(idx.indkey) WITH ORDINALITY key(attnum,ord) ON TRUE
           JOIN pg_attribute att ON att.attrelid=cls.oid AND att.attnum=key.attnum
           WHERE ns.nspname=%s AND cls.relname=%s AND idx.indisprimary
           ORDER BY key.ord""",
        (schema_name, relation_name),
    )
    return [row[0] for row in cursor.fetchall()]


def sync_table(source, target, table_name: str, *, allow_nonzero_gmv_target: bool = False) -> int:
    source_columns = table_columns(source, table_name)
    target_columns = set(table_columns(target, table_name))
    columns = [name for name in source_columns if name in target_columns]
    primary_key = primary_key_columns(target, table_name)
    if not columns or not primary_key:
        raise RuntimeError(f"配置表缺少公共字段或主键：{table_name}")
    identifiers = sql.SQL(",").join(sql.Identifier(name) for name in columns)
    source.execute(
        sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
            identifiers,
            sql.Identifier(*split_table(table_name)),
            sql.SQL(",").join(sql.Identifier(name) for name in primary_key),
        )
    )
    rows = [list(row) for row in source.fetchall()]
    if (
        table_name == "dim.dim_business_gmv_target_monthly"
        and not allow_nonzero_gmv_target
        and any(row[columns.index("gmv_target")] != 0 for row in rows)
    ):
        raise RuntimeError("GMV目标只允许同步0元初始化记录")
    if not rows:
        return 0
    rows = adapt_rows_for_database(source, table_name, columns, rows)
    if table_name == "dim.dim_platform_shop_company":
        # The first production seed generated a different surrogate key order
        # from the current test DIM.  Match by the stable identity key and keep
        # the target surrogate key so existing foreign keys remain valid.
        business_columns = [name for name in columns if name != "shop_company_sk"]
        update_columns = [name for name in business_columns if name not in {"platform_code", "shop_code"}]
        update_sql = sql.SQL(
            "UPDATE {} SET {} WHERE LOWER(BTRIM(platform_code))=LOWER(BTRIM(%s)) AND BTRIM(shop_code)=BTRIM(%s)"
        ).format(
            sql.Identifier(*split_table(table_name)),
            sql.SQL(",").join(
                sql.SQL("{}=%s").format(sql.Identifier(name)) for name in update_columns
            ),
        )
        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(*split_table(table_name)),
            sql.SQL(",").join(sql.Identifier(name) for name in business_columns),
            sql.SQL(",").join(sql.Placeholder() for _ in business_columns),
        )
        for row in rows:
            row_values = dict(zip(columns, row))
            target.execute(update_sql, [row_values[name] for name in update_columns] + [
                row_values["platform_code"], row_values["shop_code"],
            ])
            if target.rowcount == 0:
                target.execute(insert_sql, [row_values[name] for name in business_columns])
        return len(rows)
    if table_name in NATURAL_KEY_TABLES:
        conflict_columns, excluded_columns = NATURAL_KEY_TABLES[table_name]
        natural_columns = [name for name in columns if name not in excluded_columns]
        update_columns = [name for name in natural_columns if name not in conflict_columns]
        positions = [columns.index(name) for name in natural_columns]
        statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
            sql.Identifier(*split_table(table_name)),
            sql.SQL(",").join(sql.Identifier(name) for name in natural_columns),
            sql.SQL(",").join(sql.Placeholder() for _ in natural_columns),
            sql.SQL(",").join(sql.Identifier(name) for name in conflict_columns),
            sql.SQL(",").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
                for name in update_columns
            ),
        )
        target.executemany(statement, [[row[position] for position in positions] for row in rows])
        return len(rows)
    update_columns = [name for name in columns if name not in primary_key]
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) {}").format(
        sql.Identifier(*split_table(table_name)),
        identifiers,
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
        sql.SQL(",").join(sql.Identifier(name) for name in primary_key),
        sql.SQL("DO UPDATE SET ") + sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in update_columns
        ) if update_columns else sql.SQL("DO NOTHING"),
    )
    target.executemany(statement, rows)
    return len(rows)


def sync_company_product_code_mappings(source, target) -> int:
    """Sync product-code mappings using the current partial natural indexes.

    Since the post-393 schema allows both platform-level and shop-level rows,
    ``code_pattern`` is no longer unique.  Match by platform, optional shop
    and normalized source code instead of using a stale surrogate key.
    """
    table_name = "dim.dim_company_product_code_mapping"
    source_columns = table_columns(source, table_name)
    target_columns = set(table_columns(target, table_name))
    required = {"platform_code", "shop_code", "source_product_code"}
    if not required.issubset(source_columns) or not required.issubset(target_columns):
        raise RuntimeError(f"商品编码映射缺少当前自然键字段：{table_name}")
    columns = [name for name in source_columns if name in target_columns and name != "mapping_id"]
    source.execute(
        sql.SQL("SELECT {} FROM {} ORDER BY platform_code,shop_code,source_product_code").format(
            sql.SQL(",").join(sql.Identifier(name) for name in columns),
            sql.Identifier(*split_table(table_name)),
        )
    )
    rows = [dict(zip(columns, row)) for row in source.fetchall()]
    update_columns = [name for name in columns if name not in {"platform_code", "shop_code", "source_product_code"}]
    update_statement = sql.SQL("UPDATE {} SET {} WHERE mapping_id=%s").format(
        sql.Identifier(*split_table(table_name)),
        sql.SQL(",").join(
            sql.SQL("{}=%s").format(sql.Identifier(name)) for name in update_columns
        ),
    )
    insert_statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(*split_table(table_name)),
        sql.SQL(",").join(sql.Identifier(name) for name in columns),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
    )
    for row in rows:
        target.execute(
            """SELECT mapping_id
               FROM dim.dim_company_product_code_mapping
               WHERE platform_code=%s
                 AND shop_code IS NOT DISTINCT FROM %s
                 AND UPPER(BTRIM(source_product_code))=UPPER(BTRIM(%s))
               ORDER BY mapping_id
               LIMIT 1""",
            (row["platform_code"], row["shop_code"], row["source_product_code"]),
        )
        existing = target.fetchone()
        if existing:
            target.execute(update_statement, [row[name] for name in update_columns] + [existing[0]])
        else:
            target.execute(insert_statement, [row[name] for name in columns])
    return len(rows)


def sync_by_code(source, target, table_name: str, code_column: str, excluded: set[str] | None = None,
                 overrides: dict[str, object] | None = None) -> int:
    excluded = set(excluded or ())
    source_columns = table_columns(source, table_name)
    target_columns = set(table_columns(target, table_name))
    columns = [name for name in source_columns if name in target_columns and name not in excluded]
    select_identifiers = sql.SQL(",").join(sql.Identifier(name) for name in columns)
    source.execute(sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
        select_identifiers, sql.Identifier(*split_table(table_name)), sql.Identifier(code_column)
    ))
    rows = [list(row) for row in source.fetchall()]
    for column_name, value in (overrides or {}).items():
        if column_name in columns:
            position = columns.index(column_name)
            for row in rows:
                row[position] = value
    if not rows:
        return 0
    rows = adapt_rows_for_database(source, table_name, columns, rows)
    update_columns = [name for name in columns if name != code_column]
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier(*split_table(table_name)),
        sql.SQL(",").join(sql.Identifier(name) for name in columns),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
        sql.Identifier(code_column),
        sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in update_columns
        ),
    )
    target.executemany(statement, rows)
    return len(rows)


def sync_permission_resources(source, target) -> int:
    source.execute(
        """SELECT resource.resource_code,resource.resource_name,resource.resource_type,
                  resource.module_code,parent.resource_code AS parent_code,
                  resource.route_path,resource.display_order,resource.is_active
           FROM iam.permission_resource resource
           LEFT JOIN iam.permission_resource parent
             ON parent.resource_id=resource.parent_resource_id
           ORDER BY resource.resource_id"""
    )
    pending = [dict(row) for row in source.fetchall()]
    completed = 0
    while pending:
        deferred = []
        for row in pending:
            parent_id = None
            if row["parent_code"]:
                target.execute("SELECT resource_id FROM iam.permission_resource WHERE resource_code=%s", (row["parent_code"],))
                parent = target.fetchone()
                if not parent:
                    deferred.append(row)
                    continue
                parent_id = parent[0]
            target.execute(
                """INSERT INTO iam.permission_resource(
                       resource_code,resource_name,resource_type,module_code,parent_resource_id,
                       route_path,display_order,is_active,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT(resource_code) DO UPDATE SET
                       resource_name=EXCLUDED.resource_name,
                       resource_type=EXCLUDED.resource_type,
                       module_code=EXCLUDED.module_code,
                       parent_resource_id=EXCLUDED.parent_resource_id,
                       route_path=EXCLUDED.route_path,
                       display_order=EXCLUDED.display_order,
                       is_active=EXCLUDED.is_active,
                       updated_at=NOW()""",
                (row["resource_code"], row["resource_name"], row["resource_type"], row["module_code"],
                 parent_id, row["route_path"], row["display_order"], row["is_active"]),
            )
            completed += 1
        if len(deferred) == len(pending):
            raise RuntimeError("IAM权限资源存在无法解析的父级")
        pending = deferred
    return completed


def sync_dashboards(source, target) -> int:
    source.execute(
        """SELECT dashboard.*,resource.resource_code
           FROM config.dashboard dashboard
           JOIN iam.permission_resource resource
             ON resource.resource_id=dashboard.permission_resource_id
           ORDER BY dashboard.dashboard_code"""
    )
    rows = [dict(row) for row in source.fetchall()]
    columns = (
        "dashboard_code", "dashboard_name", "dashboard_description", "share_url", "icon_name",
        "display_order", "allow_fullscreen", "is_active", "permission_resource_id", "created_at",
        "updated_at", "deleted_at", "renderer", "dashboard_slug", "category_code", "default_filters",
        "is_navigation_visible",
    )
    statement = """INSERT INTO config.dashboard(
                       dashboard_code,dashboard_name,dashboard_description,share_url,icon_name,
                       display_order,allow_fullscreen,is_active,permission_resource_id,created_at,updated_at,deleted_at,
                       renderer,dashboard_slug,category_code,default_filters,is_navigation_visible)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(dashboard_code) DO UPDATE SET
                       dashboard_name=EXCLUDED.dashboard_name,
                       dashboard_description=EXCLUDED.dashboard_description,
                       share_url=EXCLUDED.share_url,
                       icon_name=EXCLUDED.icon_name,
                       display_order=EXCLUDED.display_order,
                       allow_fullscreen=EXCLUDED.allow_fullscreen,
                       is_active=EXCLUDED.is_active,
                       permission_resource_id=EXCLUDED.permission_resource_id,
                       updated_at=EXCLUDED.updated_at,
                       deleted_at=EXCLUDED.deleted_at,
                       renderer=EXCLUDED.renderer,
                       dashboard_slug=EXCLUDED.dashboard_slug,
                       category_code=EXCLUDED.category_code,
                       default_filters=EXCLUDED.default_filters,
                       is_navigation_visible=EXCLUDED.is_navigation_visible"""
    values = []
    for row in rows:
        target.execute("SELECT resource_id FROM iam.permission_resource WHERE resource_code=%s", (row["resource_code"],))
        resource = target.fetchone()
        if not resource:
            raise RuntimeError(f"看板权限资源不存在：{row['resource_code']}")
        row["permission_resource_id"] = resource[0]
        values.append([
            Json(row[name]) if name == "default_filters" and row[name] is not None else row[name]
            for name in columns
        ])
    target.executemany(statement, values)
    return len(values)


TARGET_ID_COLUMNS = {
    "iam.department": "department_id",
    "iam.role": "role_id",
    "iam.user_account": "user_id",
    "iam.permission_resource": "resource_id",
    "config.dashboard": "dashboard_id",
    "ai.feishu_app": "feishu_app_id",
}


def target_find_id(target, table_name: str, key_column: str, key_value: object) -> int | None:
    if key_value is None:
        return None
    id_column = TARGET_ID_COLUMNS.get(table_name)
    if id_column is None:
        raise RuntimeError(f"没有配置引用主键：{table_name}")
    target.execute(
        sql.SQL("SELECT {} FROM {} WHERE {}=%s").format(
            sql.Identifier(id_column),
            sql.Identifier(*split_table(table_name)),
            sql.Identifier(key_column),
        ),
        (key_value,),
    )
    row = target.fetchone()
    return int(row[0]) if row else None


def target_lookup_id(target, table_name: str, key_column: str, key_value: object, label: str) -> int | None:
    row_id = target_find_id(target, table_name, key_column, key_value)
    if key_value is not None and row_id is None:
        raise RuntimeError(f"正式库缺少配置引用：{label}={key_value}")
    return row_id


def sync_iam_departments(source, target) -> int:
    source.execute(
        """SELECT department.department_code,department.department_name,
                  parent.department_code AS parent_code,department.display_order,
                  department.is_active,department.created_at,department.updated_at,department.deleted_at
           FROM iam.department department
           LEFT JOIN iam.department parent ON parent.department_id=department.parent_department_id
           ORDER BY department.department_code"""
    )
    pending = [dict(row) for row in source.fetchall()]
    completed = 0
    while pending:
        deferred = []
        for row in pending:
            parent_id = target_find_id(target, "iam.department", "department_code", row["parent_code"])
            if row["parent_code"] and parent_id is None:
                deferred.append(row)
                continue
            target.execute(
                """INSERT INTO iam.department(
                       department_code,department_name,parent_department_id,display_order,is_active,
                       created_at,updated_at,deleted_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(department_code) DO UPDATE SET
                       department_name=EXCLUDED.department_name,
                       parent_department_id=EXCLUDED.parent_department_id,
                       display_order=EXCLUDED.display_order,
                       is_active=EXCLUDED.is_active,
                       updated_at=EXCLUDED.updated_at,
                       deleted_at=EXCLUDED.deleted_at
                   RETURNING department_id""",
                (row["department_code"], row["department_name"], parent_id, row["display_order"],
                 row["is_active"], row["created_at"], row["updated_at"], row["deleted_at"]),
            )
            target.fetchone()
            completed += 1
        if len(deferred) == len(pending):
            unresolved = ", ".join(row["department_code"] for row in deferred)
            raise RuntimeError(f"正式库部门父级无法解析：{unresolved}")
        pending = deferred
    return completed


def sync_iam_roles(source, target) -> int:
    source.execute(
        """SELECT role_code,role_name,role_description,is_active,created_at,updated_at,deleted_at
           FROM iam.role ORDER BY role_code"""
    )
    rows = source.fetchall()
    target.executemany(
        """INSERT INTO iam.role(
               role_code,role_name,role_description,is_active,created_at,updated_at,deleted_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT(role_code) DO UPDATE SET
               role_name=EXCLUDED.role_name,
               role_description=EXCLUDED.role_description,
               is_active=EXCLUDED.is_active,
               updated_at=EXCLUDED.updated_at,
               deleted_at=EXCLUDED.deleted_at""",
        rows,
    )
    return len(rows)


def sync_iam_users(source, target) -> int:
    source.execute(
        """SELECT account.username,account.display_name,account.password_hash,
                  account.password_ciphertext,account.password_nonce,
                  department.department_code,account.is_active,account.is_super_admin,
                  account.password_changed_at,account.created_at,account.updated_at,account.deleted_at
           FROM iam.user_account account
           LEFT JOIN iam.department department ON department.department_id=account.department_id
           ORDER BY account.username"""
    )
    rows = source.fetchall()
    for row in rows:
        department_id = target_lookup_id(
            target, "iam.department", "department_code", row["department_code"], "department_code"
        )
        target.execute(
            """INSERT INTO iam.user_account(
                   username,display_name,password_hash,password_ciphertext,password_nonce,department_id,is_active,is_super_admin,
                   failed_login_count,locked_until,session_version,password_changed_at,last_login_at,
                   created_at,updated_at,deleted_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,NULL,1,%s,NULL,%s,%s,%s)
               ON CONFLICT(username) DO UPDATE SET
                   display_name=EXCLUDED.display_name,
                   password_hash=EXCLUDED.password_hash,
                   password_ciphertext=EXCLUDED.password_ciphertext,
                   password_nonce=EXCLUDED.password_nonce,
                   department_id=EXCLUDED.department_id,
                   is_active=EXCLUDED.is_active,
                   is_super_admin=EXCLUDED.is_super_admin,
                   failed_login_count=0,
                   locked_until=NULL,
                   session_version=1,
                   password_changed_at=EXCLUDED.password_changed_at,
                   last_login_at=NULL,
                   updated_at=EXCLUDED.updated_at,
                   deleted_at=EXCLUDED.deleted_at
               RETURNING user_id""",
            (row["username"], row["display_name"], row["password_hash"], row["password_ciphertext"], row["password_nonce"], department_id,
             row["is_active"], row["is_super_admin"], row["password_changed_at"],
             row["created_at"], row["updated_at"], row["deleted_at"]),
        )
        target.fetchone()
    return len(rows)


def sync_iam_relationships(source, target) -> dict[str, int]:
    source.execute(
        """SELECT department.department_code,resource.resource_code,permission.granted_at,
                  granted_by.username AS granted_by_username
           FROM iam.department_permission permission
           JOIN iam.department department ON department.department_id=permission.department_id
           JOIN iam.permission_resource resource ON resource.resource_id=permission.resource_id
           LEFT JOIN iam.user_account granted_by ON granted_by.user_id=permission.granted_by
           ORDER BY department.department_code,resource.resource_code"""
    )
    department_permissions = source.fetchall()
    for row in department_permissions:
        department_id = target_lookup_id(target, "iam.department", "department_code", row[0], "department_code")
        resource_id = target_lookup_id(target, "iam.permission_resource", "resource_code", row[1], "resource_code")
        granted_by = target_lookup_id(target, "iam.user_account", "username", row[3], "username")
        target.execute(
            """INSERT INTO iam.department_permission(department_id,resource_id,granted_at,granted_by)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT(department_id,resource_id) DO UPDATE SET
                   granted_at=EXCLUDED.granted_at,granted_by=EXCLUDED.granted_by""",
            (department_id, resource_id, row[2], granted_by),
        )

    source.execute(
        """SELECT role.role_code,resource.resource_code,permission.granted_at,
                  granted_by.username AS granted_by_username
           FROM iam.role_permission permission
           JOIN iam.role role ON role.role_id=permission.role_id
           JOIN iam.permission_resource resource ON resource.resource_id=permission.resource_id
           LEFT JOIN iam.user_account granted_by ON granted_by.user_id=permission.granted_by
           ORDER BY role.role_code,resource.resource_code"""
    )
    role_permissions = source.fetchall()
    for row in role_permissions:
        role_id = target_lookup_id(target, "iam.role", "role_code", row[0], "role_code")
        resource_id = target_lookup_id(target, "iam.permission_resource", "resource_code", row[1], "resource_code")
        granted_by = target_lookup_id(target, "iam.user_account", "username", row[3], "username")
        target.execute(
            """INSERT INTO iam.role_permission(role_id,resource_id,granted_at,granted_by)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT(role_id,resource_id) DO UPDATE SET
                   granted_at=EXCLUDED.granted_at,granted_by=EXCLUDED.granted_by""",
            (role_id, resource_id, row[2], granted_by),
        )

    source.execute(
        """SELECT account.username,role.role_code,assignment.granted_at,
                  granted_by.username AS granted_by_username
           FROM iam.user_role assignment
           JOIN iam.user_account account ON account.user_id=assignment.user_id
           JOIN iam.role role ON role.role_id=assignment.role_id
           LEFT JOIN iam.user_account granted_by ON granted_by.user_id=assignment.granted_by
           ORDER BY account.username,role.role_code"""
    )
    user_roles = source.fetchall()
    for row in user_roles:
        user_id = target_lookup_id(target, "iam.user_account", "username", row[0], "username")
        role_id = target_lookup_id(target, "iam.role", "role_code", row[1], "role_code")
        granted_by = target_lookup_id(target, "iam.user_account", "username", row[3], "username")
        target.execute(
            """INSERT INTO iam.user_role(user_id,role_id,granted_at,granted_by)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT(user_id,role_id) DO UPDATE SET
                   granted_at=EXCLUDED.granted_at,granted_by=EXCLUDED.granted_by""",
            (user_id, role_id, row[2], granted_by),
        )

    source.execute(
        """SELECT account.username,resource.resource_code,permission.permission_effect,permission.granted_at,
                  granted_by.username AS granted_by_username
           FROM iam.user_permission permission
           JOIN iam.user_account account ON account.user_id=permission.user_id
           JOIN iam.permission_resource resource ON resource.resource_id=permission.resource_id
           LEFT JOIN iam.user_account granted_by ON granted_by.user_id=permission.granted_by
           ORDER BY account.username,resource.resource_code"""
    )
    user_permissions = source.fetchall()
    for row in user_permissions:
        user_id = target_lookup_id(target, "iam.user_account", "username", row[0], "username")
        resource_id = target_lookup_id(target, "iam.permission_resource", "resource_code", row[1], "resource_code")
        granted_by = target_lookup_id(target, "iam.user_account", "username", row[4], "username")
        target.execute(
            """INSERT INTO iam.user_permission(user_id,resource_id,permission_effect,granted_at,granted_by)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT(user_id,resource_id) DO UPDATE SET
                   permission_effect=EXCLUDED.permission_effect,
                   granted_at=EXCLUDED.granted_at,
                   granted_by=EXCLUDED.granted_by""",
            (user_id, resource_id, row[2], row[3], granted_by),
        )
    return {
        "iam.department_permission": len(department_permissions),
        "iam.role_permission": len(role_permissions),
        "iam.user_role": len(user_roles),
        "iam.user_permission": len(user_permissions),
    }


def sync_dashboard_widgets(source, target) -> int:
    source.execute(
        """SELECT widget.*,dashboard.dashboard_code,
                  creator.username AS created_by_username,
                  updater.username AS updated_by_username
           FROM config.dashboard_widget widget
           JOIN config.dashboard dashboard ON dashboard.dashboard_id=widget.dashboard_id
           LEFT JOIN iam.user_account creator ON creator.user_id=widget.created_by
           LEFT JOIN iam.user_account updater ON updater.user_id=widget.updated_by
           ORDER BY dashboard.dashboard_code,widget.widget_key"""
    )
    rows = [dict(row) for row in source.fetchall()]
    source_columns = table_columns(source, "config.dashboard_widget")
    target_columns = set(table_columns(target, "config.dashboard_widget"))
    excluded = {"widget_id", "dashboard_id", "created_by", "updated_by"}
    business_columns = [
        name for name in source_columns
        if name in target_columns and name not in excluded
    ]
    insert_columns = ["dashboard_id", *business_columns, "created_by", "updated_by"]
    update_columns = [name for name in insert_columns if name not in {"dashboard_id", "widget_key"}]
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier("config", "dashboard_widget"),
        sql.SQL(",").join(sql.Identifier(name) for name in insert_columns),
        sql.SQL(",").join(sql.Placeholder() for _ in insert_columns),
        sql.SQL(",").join(sql.Identifier(name) for name in ("dashboard_id", "widget_key")),
        sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in update_columns
        ),
    )
    json_columns = jsonb_columns(source, "config.dashboard_widget")
    values = []
    for row in rows:
        dashboard_id = target_lookup_id(
            target, "config.dashboard", "dashboard_code", row["dashboard_code"], "dashboard_code"
        )
        created_by = target_lookup_id(target, "iam.user_account", "username", row["created_by_username"], "username")
        updated_by = target_lookup_id(target, "iam.user_account", "username", row["updated_by_username"], "username")
        business_values = [
            Json(row[name]) if name in json_columns and row[name] is not None else row[name]
            for name in business_columns
        ]
        values.append([dashboard_id, *business_values, created_by, updated_by])
    if not values:
        return 0
    target.executemany(statement, values)
    return len(values)


def sync_prompt_versions(source, target) -> int:
    source.execute(
        """SELECT template.template_code,version.version_no,version.template_content,
                  version.output_format,version.change_note,version.created_at
           FROM ai.prompt_template_version version
           JOIN ai.prompt_template template ON template.prompt_template_id=version.prompt_template_id
           ORDER BY template.template_code,version.version_no"""
    )
    rows = source.fetchall()
    statement = """INSERT INTO ai.prompt_template_version(
                       prompt_template_id,version_no,template_content,output_format,change_note,created_at)
                   SELECT prompt_template_id,%s,%s,%s,%s,%s
                   FROM ai.prompt_template WHERE template_code=%s
                   ON CONFLICT(prompt_template_id,version_no) DO UPDATE SET
                       template_content=EXCLUDED.template_content,
                       output_format=EXCLUDED.output_format,
                       change_note=EXCLUDED.change_note"""
    target.executemany(statement, [
        (row[1], row[2], Json(row[3]), row[4], row[5], row[0]) for row in rows
    ])
    return len(rows)


def sync_feishu_apps(source, target) -> int:
    source.execute(
        """SELECT app.*,default_prompt.template_code AS default_prompt_code,
                  daily_prompt.template_code AS daily_prompt_code
           FROM ai.feishu_app app
           LEFT JOIN ai.prompt_template default_prompt
             ON default_prompt.prompt_template_id=app.default_prompt_template_id
           LEFT JOIN ai.prompt_template daily_prompt
             ON daily_prompt.prompt_template_id=app.daily_report_prompt_template_id
           ORDER BY app.config_code"""
    )
    rows = [dict(row) for row in source.fetchall()]
    target_columns = set(table_columns(target, "ai.feishu_app"))
    excluded = {"feishu_app_id", "created_by", "updated_by", "default_prompt_template_id", "daily_report_prompt_template_id"}
    columns = [name for name in table_columns(source, "ai.feishu_app") if name in target_columns and name not in excluded]
    columns += ["default_prompt_template_id", "daily_report_prompt_template_id"]
    values = []
    for row in rows:
        target.execute("SELECT prompt_template_id FROM ai.prompt_template WHERE template_code=%s", (row["default_prompt_code"],))
        default_prompt = target.fetchone()
        target.execute("SELECT prompt_template_id FROM ai.prompt_template WHERE template_code=%s", (row["daily_prompt_code"],))
        daily_prompt = target.fetchone()
        row_values = []
        for name in columns[:-2]:
            value = row.get(name)
            row_values.append(Json(value) if name in {"allowed_chat_ids", "daily_report_chat_ids"} else value)
        values.append(row_values + [
            default_prompt[0] if default_prompt else None,
            daily_prompt[0] if daily_prompt else None,
        ])
    if not values:
        return 0
    update_columns = [name for name in columns if name != "config_code"]
    statement = sql.SQL("INSERT INTO ai.feishu_app ({}) VALUES ({}) ON CONFLICT (config_code) DO UPDATE SET {}").format(
        sql.SQL(",").join(sql.Identifier(name) for name in columns),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
        sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in update_columns
        ),
    )
    target.executemany(statement, values)
    return len(values)


def sync_verification_relays(source, target) -> int:
    source.execute(
        """SELECT relay.*,app.config_code AS feishu_config_code,
                  creator.username AS created_by_username,
                  updater.username AS updated_by_username
           FROM ai.verification_relay_config relay
           JOIN ai.feishu_app app ON app.feishu_app_id=relay.feishu_app_id
           LEFT JOIN iam.user_account creator ON creator.user_id=relay.created_by
           LEFT JOIN iam.user_account updater ON updater.user_id=relay.updated_by
           ORDER BY relay.config_code"""
    )
    rows = [dict(row) for row in source.fetchall()]
    source_columns = table_columns(source, "ai.verification_relay_config")
    target_columns = set(table_columns(target, "ai.verification_relay_config"))
    excluded = {
        "verification_relay_config_id",
        "feishu_app_id",
        "created_by",
        "updated_by",
    }
    business_columns = [
        name for name in source_columns
        if name in target_columns and name not in excluded
    ]
    insert_columns = [*business_columns, "feishu_app_id", "created_by", "updated_by"]
    update_columns = [name for name in insert_columns if name != "config_code"]
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier("ai", "verification_relay_config"),
        sql.SQL(",").join(sql.Identifier(name) for name in insert_columns),
        sql.SQL(",").join(sql.Placeholder() for _ in insert_columns),
        sql.Identifier("config_code"),
        sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
            for name in update_columns
        ),
    )
    json_columns = jsonb_columns(source, "ai.verification_relay_config")
    values = []
    for row in rows:
        feishu_app_id = target_lookup_id(
            target, "ai.feishu_app", "config_code", row["feishu_config_code"], "config_code"
        )
        created_by = target_lookup_id(target, "iam.user_account", "username", row["created_by_username"], "username")
        updated_by = target_lookup_id(target, "iam.user_account", "username", row["updated_by_username"], "username")
        business_values = [
            Json(row[name]) if name in json_columns and row[name] is not None else row[name]
            for name in business_columns
        ]
        values.append([*business_values, feishu_app_id, created_by, updated_by])
    if not values:
        return 0
    target.executemany(statement, values)
    return len(values)


def sync_finance_configuration(source, target) -> dict[str, int]:
    return {
        table_name: sync_table(source, target, table_name)
        for table_name in FINANCE_CONFIGURATION_TABLES
    }


def grant_ai_reader(source, target, target_database: str) -> list[str]:
    source.execute("SELECT DISTINCT readonly_username FROM ai.data_source WHERE is_active AND deleted_at IS NULL")
    roles = [row[0] for row in source.fetchall()]
    granted: list[str] = []
    for role in roles:
        target.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,))
        if not target.fetchone():
            raise RuntimeError(f"AI只读角色不存在，需先由DBA创建：{role}")
        target.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(target_database), sql.Identifier(role)
        ))
        target.execute(sql.SQL("GRANT USAGE ON SCHEMA ads,dim TO {}").format(sql.Identifier(role)))
        target.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA ads,dim TO {}").format(sql.Identifier(role)))
        for setting, value in (
            ("default_transaction_read_only", "on"),
            ("statement_timeout", "30s"),
            ("lock_timeout", "3s"),
            ("idle_in_transaction_session_timeout", "30s"),
        ):
            target.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET {} TO %s").format(
                sql.Identifier(role), sql.Identifier(target_database), sql.Identifier(setting)
            ), (value,))
        target.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path TO ads,dim").format(
            sql.Identifier(role), sql.Identifier(target_database)
        ))
        granted.append(role)
    return granted


def reset_owned_sequences(cursor, schemas: tuple[str, ...]) -> None:
    cursor.execute(
        """SELECT ns.nspname,seq.relname,tbl.relname,att.attname
           FROM pg_class seq
           JOIN pg_namespace ns ON ns.oid=seq.relnamespace
           JOIN pg_depend dep ON dep.objid=seq.oid AND dep.deptype='a'
           JOIN pg_class tbl ON tbl.oid=dep.refobjid
           JOIN pg_attribute att ON att.attrelid=tbl.oid AND att.attnum=dep.refobjsubid
           WHERE seq.relkind='S' AND ns.nspname=ANY(%s)""",
        (list(schemas),),
    )
    for schema_name, sequence_name, table_name, column_name in cursor.fetchall():
        cursor.execute(sql.SQL("SELECT MAX({}) FROM {}.{}").format(
            sql.Identifier(column_name), sql.Identifier(schema_name), sql.Identifier(table_name)
        ))
        maximum = cursor.fetchone()[0]
        cursor.execute("SELECT setval(%s::regclass,%s,%s)", (
            f'"{schema_name}"."{sequence_name}"', maximum or 1, maximum is not None
        ))


def main() -> None:
    args = build_parser().parse_args()
    source_kwargs = connection_kwargs(args.source_url, args, args.source_db)
    target_kwargs = connection_kwargs(args.target_url, args, args.target_db)
    if str(source_kwargs["dbname"]).lower() != PROTECTED_SOURCE_DATABASE:
        raise RuntimeError("配置同步源只允许mock_coffice")
    assert_not_source_database(str(target_kwargs["dbname"]))

    source_connection = psycopg2.connect(**source_kwargs, application_name="coffice_config_source_readonly")
    target_connection = psycopg2.connect(**target_kwargs, application_name="coffice_config_target_sync")
    source_connection.set_session(readonly=True, autocommit=True)
    counts: dict[str, int] = {}
    granted_roles: list[str] = []
    try:
        with source_connection.cursor(cursor_factory=DictCursor) as source, target_connection.cursor() as target:
            for table_name in DIM_TABLES:
                if table_name == "dim.dim_company_product_code_mapping":
                    counts[table_name] = sync_company_product_code_mappings(source, target)
                else:
                    counts[table_name] = sync_table(
                        source,
                        target,
                        table_name,
                        allow_nonzero_gmv_target=args.include_gmv_targets,
                    )
            counts["iam.permission_resource"] = sync_permission_resources(source, target)
            counts["iam.department"] = sync_iam_departments(source, target)
            counts["iam.role"] = sync_iam_roles(source, target)
            counts["iam.user_account"] = sync_iam_users(source, target)
            counts.update(sync_iam_relationships(source, target))
            counts["config.dashboard"] = sync_dashboards(source, target)
            counts["config.dashboard_widget"] = sync_dashboard_widgets(source, target)
            counts.update(sync_finance_configuration(source, target))
            if args.include_encrypted_ai_config:
                counts["ai.provider_config"] = sync_by_code(
                    source, target, "ai.provider_config", "config_code",
                    {"provider_config_id", "created_by", "updated_by"},
                )
                counts["ai.data_source"] = sync_by_code(
                    source, target, "ai.data_source", "source_code",
                    {"data_source_id", "created_by", "updated_by"},
                    {"database_name": str(target_kwargs["dbname"])},
                )
                counts["ai.prompt_template"] = sync_by_code(
                    source, target, "ai.prompt_template", "template_code",
                    {"prompt_template_id", "created_by", "updated_by"},
                )
                counts["ai.prompt_template_version"] = sync_prompt_versions(source, target)
                counts["ai.feishu_app"] = sync_feishu_apps(source, target)
                counts["ai.verification_relay_config"] = sync_verification_relays(source, target)
                if args.grant_ai_reader:
                    granted_roles = grant_ai_reader(source, target, str(target_kwargs["dbname"]))
            reset_owned_sequences(target, ("dim", "ai", "config", "iam"))
        target_connection.commit()
    except Exception:
        target_connection.rollback()
        raise
    finally:
        source_connection.close()
        target_connection.close()

    print(json.dumps({
        "source_database": source_kwargs["dbname"],
        "target_database": target_kwargs["dbname"],
        "rows_upserted": counts,
        "encrypted_ai_config_transferred": args.include_encrypted_ai_config,
        "gmv_targets_transferred": args.include_gmv_targets,
        "ai_reader_roles_granted": granted_roles,
        "status": "success",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
