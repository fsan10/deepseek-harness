#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新拼多多、视频号和小红书主营财务链路。

该文件保留为三平台历史兼容入口。生产调度使用同目录下的三个薄包装：
``run_pdd_main_business_finance_etl.py``、
``run_wechat_channels_main_business_finance_etl.py`` 和
``run_xhs_main_business_finance_etl.py``；每个包装只刷新自己的DWD/DWS，
再重建共享平台费用ADS。
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.report_sources import prepare_report_sources


PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "dim/305_dim_platform_fee_mapping_postgres.sql",
]
CREATE_SQL_FILES = [
    "pdd/main_business_finance/341_dwd_pdd_main_business_finance_source_detail_postgres.sql",
    "pdd/main_business_finance/342_dws_pdd_main_business_finance_shop_daily_category_postgres.sql",
    "wechat_channels/main_business_finance/345_dwd_wechat_channels_main_business_finance_source_detail_postgres.sql",
    "wechat_channels/main_business_finance/346_dws_wechat_channels_main_business_finance_shop_daily_category_postgres.sql",
    "xhs/main_business_finance/349_dwd_xhs_main_business_finance_source_detail_postgres.sql",
    "xhs/main_business_finance/350_dws_xhs_main_business_finance_shop_daily_category_postgres.sql",
    "ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql",
]
REFRESH_SQL_FILES = [
    "dim/340_seed_pdd_wechat_xhs_platform_fee_mapping_postgres.sql",
    "dim/425_xhs_appeal_adjustment_income_policy_postgres.sql",
    "dim/373_dim_platform_finance_source_policy_postgres.sql",
    "pdd/main_business_finance/343_refresh_dwd_pdd_main_business_finance_source_detail_postgres.sql",
    "pdd/main_business_finance/344_refresh_dws_pdd_main_business_finance_shop_daily_category_postgres.sql",
    "wechat_channels/main_business_finance/347_refresh_dwd_wechat_channels_main_business_finance_source_detail_postgres.sql",
    "wechat_channels/main_business_finance/348_refresh_dws_wechat_channels_main_business_finance_shop_daily_category_postgres.sql",
    "xhs/main_business_finance/351_refresh_dwd_xhs_main_business_finance_source_detail_postgres.sql",
    "xhs/main_business_finance/352_refresh_dws_xhs_main_business_finance_shop_daily_category_postgres.sql",
    "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
]

PLATFORM_SCOPES = ("pdd", "wechat_channels", "xhs")
VALID_SCOPES = frozenset((*PLATFORM_SCOPES, "legacy"))
PLATFORM_ODS_KEYS = {
    "pdd": ("pdd",),
    "wechat_channels": ("wechat_channels",),
    "xhs": ("xhs_income", "xhs_expense"),
    "legacy": tuple(),  # 在ODS_TABLES定义后展开为全部来源。
}
PLATFORM_CREATE_SQL_FILES = {
    "pdd": tuple(CREATE_SQL_FILES[0:2]),
    "wechat_channels": tuple(CREATE_SQL_FILES[2:4]),
    "xhs": tuple(CREATE_SQL_FILES[4:6]),
}
PLATFORM_REFRESH_SQL_FILES = {
    "pdd": tuple(REFRESH_SQL_FILES[3:5]),
    "wechat_channels": tuple(REFRESH_SQL_FILES[5:7]),
    "xhs": tuple(REFRESH_SQL_FILES[7:9]),
}
SHARED_CREATE_SQL_FILES = (CREATE_SQL_FILES[6],)
SHARED_PREPARE_REFRESH_SQL_FILES = tuple(REFRESH_SQL_FILES[0:3])
SHARED_REFRESH_SQL_FILES = (REFRESH_SQL_FILES[9],)

ODS_TABLES = {
    "pdd": (
        "ods_pdd_settlement_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "商户订单号", "发生时间", "收入金额（+元）",
            "支出金额（-元）", "账务类型", "业务描述",
        },
    ),
    "wechat_channels": (
        "ods_wechat_channels_settlement_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "流水单号", "记账时间", "动帐类型", "收支类型",
            "收支金额", "关联订单号", "关联售后单号", "详情",
        },
    ),
    "xhs_income": (
        "ods_xhs_settlement_income_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "订单号", "售后单号", "结算时间", "交易类型",
            "动账金额", "平台佣金", "买手佣金", "花呗分期手续费",
        },
    ),
    "xhs_expense": (
        "ods_xhs_settlement_expense_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "订单号", "业务款项", "结算时间", "动账金额",
        },
    ),
}

COMMENTED_TABLES = [
    ("dwd", "dwd_pdd_main_business_income_source_detail"),
    ("dwd", "dwd_pdd_platform_expense_source_detail"),
    ("dws", "dws_pdd_main_business_income_shop_daily_category"),
    ("dws", "dws_pdd_platform_expense_shop_daily_category"),
    ("dwd", "dwd_wechat_channels_main_business_income_source_detail"),
    ("dwd", "dwd_wechat_channels_platform_expense_source_detail"),
    ("dws", "dws_wechat_channels_main_business_income_shop_daily_category"),
    ("dws", "dws_wechat_channels_platform_expense_shop_daily_category"),
    ("dwd", "dwd_xhs_main_business_income_source_detail"),
    ("dwd", "dwd_xhs_platform_expense_source_detail"),
    ("dws", "dws_xhs_main_business_income_shop_daily_category"),
    ("dws", "dws_xhs_platform_expense_shop_daily_category"),
]
PLATFORM_COMMENTED_TABLES = {
    "pdd": tuple(COMMENTED_TABLES[0:4]),
    "wechat_channels": tuple(COMMENTED_TABLES[4:8]),
    "xhs": tuple(COMMENTED_TABLES[8:12]),
}
SHARED_COMMENTED_TABLES = (
    ("ads", "ads_platform_expense_company_shop_daily_category"),
)

MAY_BASELINE = {
    "pdd": (Decimal("315100.14"), Decimal("6356.68")),
    "wechat_channels": (Decimal("115536.56"), Decimal("36969.22")),
    "xhs": (Decimal("25808.05"), Decimal("10828.45")),
}


def parser(description: str = "刷新拼多多、视频号和小红书主营业务收入与平台费用。") -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=description
    )
    result.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    result.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    result.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    result.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    result.add_argument("--password", default=os.getenv("PGPASSWORD"))
    result.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="强制校验当前2026年5月专项基准。",
    )
    return result


def platforms_for_scope(scope: str) -> tuple[str, ...]:
    if scope not in VALID_SCOPES:
        raise ValueError(f"不支持的主营财务范围：{scope}")
    return PLATFORM_SCOPES if scope == "legacy" else (scope,)


def files_for_scope(scope: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """返回指定范围需要执行的建表和刷新SQL，供包装入口和测试复用。"""
    platforms_for_scope(scope)
    if scope == "legacy":
        return tuple(CREATE_SQL_FILES), tuple(REFRESH_SQL_FILES)
    return (
        (*PLATFORM_CREATE_SQL_FILES[scope], *SHARED_CREATE_SQL_FILES),
        (
            *SHARED_PREPARE_REFRESH_SQL_FILES,
            *PLATFORM_REFRESH_SQL_FILES[scope],
            *SHARED_REFRESH_SQL_FILES,
        ),
    )


def execute_files(cursor, files: list[str]) -> None:
    prepare_report_sources(cursor, (), pdd_settlement=any(path.startswith("pdd/") for path in files))
    from etl.platform_finance.operating_treatment import execute_finance_files
    execute_finance_files(cursor, files)


def validate_ods(cursor, scope: str = "legacy") -> dict[str, int]:
    platforms_for_scope(scope)
    ods_keys = (
        tuple(ODS_TABLES)
        if scope == "legacy"
        else PLATFORM_ODS_KEYS[scope]
    )
    rows: dict[str, int] = {}
    for key in ods_keys:
        table_name, required_columns = ODS_TABLES[key]
        cursor.execute("SELECT to_regclass(%s)", (f"ods.{table_name}",))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少来源表ods.{table_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='ods' AND table_name=%s
            """,
            (table_name,),
        )
        actual = {row[0] for row in cursor.fetchall()}
        missing = sorted(required_columns - actual)
        if missing:
            raise RuntimeError(f"ods.{table_name}缺少必需字段：{missing}")
        cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT id), COUNT(DISTINCT row_hash) FROM ods.{table_name}")
        count_rows, unique_ids, unique_hashes = cursor.fetchone()
        if count_rows == 0:
            print(f"警告：ods.{table_name}为空，本次按0值刷新对应平台链路")
            rows[key] = count_rows
            continue
        if count_rows != unique_ids or count_rows != unique_hashes:
            raise RuntimeError(
                f"ods.{table_name}粒度异常："
                f"rows={count_rows}, ids={unique_ids}, hashes={unique_hashes}"
            )
        from etl.common.finance_sources import prepare_finance_sources, effective_count
        platform = next(p for p in ("pdd", "wechat_channels", "xhs") if table_name.startswith("ods_" + p + "_"))
        prepare_finance_sources(cursor, platform)
        rows[key] = effective_count(cursor, table_name)
    return rows


def validate_batch_mapping(cursor, scope: str = "legacy") -> list[tuple]:
    selected_platforms = set(platforms_for_scope(scope))
    specs = [
        ("pdd", "ods_pdd_settlement_raw"),
        ("wechat_channels", "ods_wechat_channels_settlement_raw"),
        ("xhs", "ods_xhs_settlement_income_raw"),
        ("xhs", "ods_xhs_settlement_expense_raw"),
    ]
    result: list[tuple] = []
    for platform_code, table_name in specs:
        if platform_code not in selected_platforms:
            continue
        cursor.execute(
            f"""
            WITH source_batches AS (
                SELECT batch_id, COUNT(*) source_rows
                FROM ods.{table_name}
                GROUP BY batch_id
            )
            SELECT b.batch_id, b.source_rows, COUNT(c.batch_id),
                   MAX(c.shop_code), MAX(c.shop_name), MAX(c.shop_mapping_status)
            FROM source_batches b
            LEFT JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id=b.batch_id
             AND c.platform_code=%s
             AND c.target_table=%s
             AND c.shop_mapping_status='mapped'
            GROUP BY b.batch_id,b.source_rows
            ORDER BY b.batch_id
            """,
            (platform_code, table_name),
        )
        found = cursor.fetchall()
        invalid = [row for row in found if row[0] is None or row[2] != 1]
        if invalid:
            raise RuntimeError(f"{platform_code}/{table_name}存在未映射批次：{invalid}")
        result.extend((platform_code, table_name, *row) for row in found)
    return result


def validate_comments(cursor, scope: str = "legacy") -> None:
    platforms_for_scope(scope)
    selected_tables = (
        (*COMMENTED_TABLES, *SHARED_COMMENTED_TABLES)
        if scope == "legacy"
        else (*PLATFORM_COMMENTED_TABLES[scope], *SHARED_COMMENTED_TABLES)
    )
    missing: list[str] = []
    for schema_name, table_name in selected_tables:
        cursor.execute(
            """
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
            """,
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if row is None or not row[0]:
            missing.append(f"{schema_name}.{table_name}:table")
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
              AND a.attnum>0 AND NOT a.attisdropped
              AND col_description(c.oid,a.attnum) IS NULL
            """,
            (schema_name, table_name),
        )
        missing.extend(
            f"{schema_name}.{table_name}.{column[0]}" for column in cursor.fetchall()
        )
    if missing:
        raise RuntimeError(f"新增表或字段缺少注释：{missing}")


def value(cursor, query: str, params: tuple = ()) -> Decimal:
    cursor.execute(query, params)
    return Decimal(cursor.fetchone()[0] or 0).quantize(Decimal("0.01"))


def validate_platform_results(
    cursor, scope: str = "legacy"
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    income_dws_tables = {
        "pdd": "dws_pdd_main_business_income_shop_daily_category",
        "wechat_channels": "dws_wechat_channels_main_business_income_shop_daily_category",
        "xhs": "dws_xhs_main_business_income_shop_daily_category",
    }
    dwd_specs = {
        "pdd": (
            "dwd_pdd_main_business_income_source_detail",
            "dwd_pdd_platform_expense_source_detail",
        ),
        "wechat_channels": (
            "dwd_wechat_channels_main_business_income_source_detail",
            "dwd_wechat_channels_platform_expense_source_detail",
        ),
        "xhs": (
            "dwd_xhs_main_business_income_source_detail",
            "dwd_xhs_platform_expense_source_detail",
        ),
    }
    for platform_code in platforms_for_scope(scope):
        income_table, expense_table = dwd_specs[platform_code]
        income_dws_table = income_dws_tables[platform_code]
        cursor.execute(f"SELECT COUNT(*), MIN(stat_date), MAX(stat_date) FROM dwd.{income_table}")
        income_dwd = cursor.fetchone()
        cursor.execute(f"SELECT COUNT(*), MIN(stat_date), MAX(stat_date) FROM dwd.{expense_table}")
        expense_dwd = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT COALESCE(SUM(income_amount),0), COUNT(*), 0
            FROM dws.{income_dws_table}
            """
        )
        income_total, income_ads_rows, income_unmapped = cursor.fetchone()
        cursor.execute(
            """
            SELECT
              COALESCE(SUM(expense_amount),0),
              COUNT(*),
              COUNT(*) FILTER (WHERE company_code='unmapped')
            FROM ads.ads_platform_expense_company_shop_daily_category
            WHERE platform_code=%s
            """,
            (platform_code,),
        )
        expense_total, expense_ads_rows, expense_unmapped = cursor.fetchone()
        if income_unmapped or expense_unmapped:
            raise RuntimeError(
                f"{platform_code} ADS存在未匹配公司："
                f"income={income_unmapped}, expense={expense_unmapped}"
            )
        platform_result = {
            "income_dwd": income_dwd,
            "expense_dwd": expense_dwd,
            "income_total": Decimal(income_total),
            "expense_total": Decimal(expense_total),
            "income_ads_rows": income_ads_rows,
            "expense_ads_rows": expense_ads_rows,
        }
        if platform_code == "xhs":
            cursor.execute(
                """
                SELECT COUNT(*),
                       ROUND(COALESCE(SUM(REPLACE(BTRIM("动账金额"), ',', '')::numeric), 0), 2)
                FROM common.v_current_xhs_settlement_expense_raw
                WHERE BTRIM("业务款项")='申诉调账'
                """
            )
            appeal_source = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*),
                       ROUND(COALESCE(SUM(restored_income_amount), 0), 2)
                FROM dwd.dwd_xhs_main_business_income_source_detail
                WHERE source_business_type='申诉调账'
                """
            )
            appeal_income = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM dwd.dwd_xhs_platform_expense_source_detail
                WHERE source_business_type='申诉调账'
                """
            )
            appeal_expense_rows = cursor.fetchone()[0]
            if appeal_income != appeal_source or appeal_expense_rows != 0:
                raise RuntimeError(
                    "小红书申诉调账应进入收入且不得进入平台费用："
                    f"ODS={appeal_source}，收入DWD={appeal_income}，费用DWD行数={appeal_expense_rows}"
                )
            platform_result.update({
                "appeal_adjustment_source": appeal_source,
                "appeal_adjustment_income": appeal_income,
                "appeal_adjustment_expense_rows": appeal_expense_rows,
            })
        result[platform_code] = platform_result
    return result


def validate_dws_ads(cursor, scope: str = "legacy") -> dict[str, tuple[int, int]]:
    from etl.platform_finance.operating_treatment import validate_projection
    return {platform: validate_projection(cursor,platform) for platform in platforms_for_scope(scope)}


def validate_reconciliation(cursor, scope: str = "legacy") -> dict[str, Decimal]:
    differences = {}
    for platform in platforms_for_scope(scope):
        if platform == "pdd":
            source = value(cursor, "SELECT SUM((\"收入金额（+元）\")::numeric+(\"支出金额（-元）\")::numeric) FROM common.v_current_pdd_settlement_raw")
        elif platform == "wechat_channels":
            source = value(cursor, "SELECT SUM(signed_amount) FROM dwd.dwd_wechat_channels_main_business_income_source_detail")
        else:
            source = value(cursor,"SELECT SUM(restored_income_amount) FROM dwd.dwd_xhs_main_business_income_source_detail") - value(cursor,"SELECT SUM(directional_expense_amount) FROM dwd.dwd_xhs_platform_expense_source_detail")
        final = value(cursor,f"SELECT SUM(income_amount-expense_amount+excluded_amount) FROM dws.dws_{platform}_operating_flow_shop_daily_scene")
        differences[platform] = (final-source).quantize(Decimal("0.01"))
    if any(differences.values()):
        raise RuntimeError(f"结算资金勾稽失败：{differences}")
    return differences


def validate_baseline(
    cursor, scope: str = "legacy"
) -> dict[str, tuple[Decimal, Decimal]]:
    actual: dict[str, tuple[Decimal, Decimal]] = {}
    for platform_code in platforms_for_scope(scope):
        income = value(
            cursor,
            f"""
            SELECT SUM(income_amount)
            FROM dws.dws_{platform_code}_main_business_income_shop_daily_category
            WHERE platform_code=%s
              AND stat_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-31'
            """,
            (platform_code,),
        )
        expense = value(
            cursor,
            """
            SELECT SUM(expense_amount)
            FROM ads.ads_platform_expense_company_shop_daily_category
            WHERE platform_code=%s
              AND stat_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-31'
            """,
            (platform_code,),
        )
        actual[platform_code] = (income, expense)
        if actual[platform_code] != MAY_BASELINE[platform_code]:
            raise RuntimeError(
                f"{platform_code} 2026年5月基准不一致："
                f"{actual[platform_code]} != {MAY_BASELINE[platform_code]}"
            )
    return actual


def samples(cursor) -> list[tuple]:
    cursor.execute(
        """
        SELECT * FROM (
          SELECT '拼多多收入' sample_type, source_business_type,
                 secondary_category_name, signed_amount
          FROM dwd.dwd_pdd_main_business_income_source_detail
          WHERE source_description='0010002|交易收入-订单收入'
          ORDER BY source_id LIMIT 1
        ) a
        UNION ALL
        SELECT * FROM (
          SELECT '拼多多费用补回', source_business_type,
                 secondary_category_name, directional_expense_amount
          FROM dwd.dwd_pdd_platform_expense_source_detail
          WHERE directional_expense_amount<0
          ORDER BY source_id LIMIT 1
        ) b
        UNION ALL
        SELECT * FROM (
          SELECT '视频号退款', source_business_type,
                 secondary_category_name, signed_amount
          FROM dwd.dwd_wechat_channels_main_business_income_source_detail
          WHERE source_business_type='订单退款'
          ORDER BY source_id LIMIT 1
        ) c
        UNION ALL
        SELECT * FROM (
          SELECT '视频号费用', source_business_type,
                 secondary_category_name, directional_expense_amount
          FROM dwd.dwd_wechat_channels_platform_expense_source_detail
          WHERE source_business_type='达人佣金'
          ORDER BY source_id LIMIT 1
        ) d
        UNION ALL
        SELECT * FROM (
          SELECT '小红书还原收入', source_business_type,
                 secondary_category_name, restored_income_amount
          FROM dwd.dwd_xhs_main_business_income_source_detail
          WHERE source_business_type='结算入账'
          ORDER BY source_id LIMIT 1
        ) e
        UNION ALL
        SELECT * FROM (
          SELECT '小红书申诉调账收入', source_business_type,
                 secondary_category_name, restored_income_amount
          FROM dwd.dwd_xhs_main_business_income_source_detail
          WHERE source_business_type='申诉调账'
          ORDER BY source_id LIMIT 1
        ) f
        UNION ALL
        SELECT * FROM (
          SELECT '小红书费用返还', source_business_type,
                 secondary_category_name, directional_expense_amount
          FROM dwd.dwd_xhs_platform_expense_source_detail
          WHERE directional_expense_amount<0
          ORDER BY source_id, source_component_code LIMIT 1
        ) g
        """
    )
    return cursor.fetchall()


def run_pipeline(args: argparse.Namespace, scope: str = "legacy") -> None:
    create_sql_files, refresh_sql_files = files_for_scope(scope)
    scope_labels = {
        "pdd": "拼多多",
        "wechat_channels": "视频号",
        "xhs": "小红书",
        "legacy": "拼多多、视频号和小红书",
    }
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with connection.cursor() as cursor:
            execute_files(cursor, PREPARE_SQL_FILES)
            ods_rows = validate_ods(cursor, scope)
            batch_mappings = validate_batch_mapping(cursor, scope)
            execute_files(cursor, create_sql_files)
            execute_files(cursor, refresh_sql_files)
            validate_comments(cursor, scope)
            platform_results = validate_platform_results(cursor, scope)
            dws_ads_diff = validate_dws_ads(cursor, scope)
            reconciliation = validate_reconciliation(cursor, scope)
            baseline = validate_baseline(cursor, scope) if args.enforce_current_baseline else {}
            sample_rows = samples(cursor) if scope == "legacy" else []
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"{scope_labels[scope]}主营业务收入与平台费用刷新成功")
    print(f"ODS行数：{ods_rows}")
    print("批次店铺映射：")
    for row in batch_mappings:
        print(row)
    for platform_code, result in platform_results.items():
        print(
            f"{platform_code}：收入DWD={result['income_dwd']}，"
            f"费用DWD={result['expense_dwd']}，"
            f"全量收入={result['income_total']:.2f}，"
            f"全量费用={result['expense_total']:.2f}，"
            f"ADS行={result['income_ads_rows']}/{result['expense_ads_rows']}"
        )
    print(f"DWS/ADS双向差异：{dws_ads_diff}")
    print(f"资金勾稽差额：{reconciliation}")
    print("DWD抽样：")
    for row in sample_rows:
        print(row)
    if args.enforce_current_baseline:
        print(f"2026年5月专项基准校验通过：{baseline}")


def main() -> None:
    # 历史命令仍保留三平台兼容行为；生产调度使用三个独立包装入口。
    run_pipeline(parser().parse_args(), "legacy")


if __name__ == "__main__":
    main()
