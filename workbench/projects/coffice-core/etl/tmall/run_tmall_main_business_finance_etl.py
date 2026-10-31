#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新天猫两个资金账户的主营业务收入、平台支出及分类明细。"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先安装 psycopg2-binary。") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "tmall/ods/329_ods_tmall_aggregate_fund_raw_postgres.sql",
    "tmall/ods/330_ods_tmall_alipay_fund_raw_postgres.sql",
    "dim/305_dim_platform_fee_mapping_postgres.sql",
    "dim/331_seed_tmall_platform_fee_mapping_postgres.sql",
    "dim/373_dim_platform_finance_source_policy_postgres.sql",
]
CREATE_SQL_FILES = [
    "douyin/platform_expense/308_dws_douyin_platform_expense_shop_daily_category_postgres.sql",
    "ks/platform_expense/315_dws_ks_platform_expense_shop_daily_category_postgres.sql",
    "jd/platform_expense/320_dws_jd_platform_expense_shop_daily_category_postgres.sql",
    "tmall/platform_expense/332_dwd_tmall_platform_expense_source_detail_postgres.sql",
    "tmall/platform_expense/333_dws_tmall_platform_expense_shop_daily_category_postgres.sql",
    "jd/main_business_income/324_dws_jd_main_business_income_shop_daily_category_postgres.sql",
    "tmall/main_business_income/336_dwd_tmall_main_business_income_source_detail_postgres.sql",
    "tmall/main_business_income/337_dws_tmall_main_business_income_shop_daily_category_postgres.sql",
    "ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql",
]
REFRESH_SQL_FILES = [
    "tmall/platform_expense/334_refresh_dwd_tmall_platform_expense_source_detail_postgres.sql",
    "tmall/platform_expense/335_refresh_dws_tmall_platform_expense_shop_daily_category_postgres.sql",
    "tmall/main_business_income/338_refresh_dwd_tmall_main_business_income_source_detail_postgres.sql",
    "tmall/main_business_income/339_refresh_dws_tmall_main_business_income_shop_daily_category_postgres.sql",
    "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
]

AGGREGATE_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "入帐日期",
    "入帐时间",
    "支付流水号",
    "主订单id",
    "子订单id",
    "入帐类型",
    "收入金额(元)",
    "支出金额(元)",
    "备注",
}
ALIPAY_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "账务流水号",
    "业务流水号",
    "商户订单号",
    "发生时间",
    "收入金额（+元）",
    "支出金额（-元）",
    "业务类型",
    "备注",
}
COMMENTED_TABLES = [
    ("ods", "ods_tmall_aggregate_fund_raw"),
    ("ods", "ods_tmall_alipay_fund_raw"),
    ("dim", "dim_platform_fee_mapping"),
    ("dwd", "dwd_tmall_platform_expense_source_detail"),
    ("dws", "dws_tmall_platform_expense_shop_daily_category"),
    ("dwd", "dwd_tmall_main_business_income_source_detail"),
    ("dws", "dws_tmall_main_business_income_shop_daily_category"),
    ("ads", "ads_platform_expense_company_shop_daily_category"),
]
CURRENT_BASELINE = {
    "shop_code": "549820088",
    "date_from": "2026-06-01",
    "date_to": "2026-06-30",
    "aggregate_rows": 775,
    "alipay_rows": 15208,
    "income_total": Decimal("263482.38"),
    "income_primary": {
        "sales_income": Decimal("264960.54"),
        "sales_refund": Decimal("-1478.16"),
    },
    "expense_total": Decimal("31341.61"),
    "expense_primary": {
        "promotion_expense": Decimal("14582.13"),
        "marketing_discount_fee": Decimal("6581.85"),
        "platform_commission": Decimal("5263.36"),
        "platform_service_fee": Decimal("3803.93"),
        "guarantee_insurance": Decimal("632.47"),
        "small_payment": Decimal("366.87"),
        "logistics_fee": Decimal("111.00"),
    },
    "withdrawal": Decimal("265000.00"),
    "raw_net": Decimal("-32859.23"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新天猫主营业务收入和支出指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="校验天猫MOCK旗舰店2026年6月当前确认基准。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    from etl.platform_finance.operating_treatment import execute_finance_files
    execute_finance_files(cursor, file_names)


def table_columns(cursor, schema_name: str, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema_name, table_name),
    )
    return {row[0] for row in cursor.fetchall()}


def validate_required_columns(
    cursor,
    table_name: str,
    required_columns: set[str],
) -> None:
    cursor.execute("SELECT to_regclass(%s)", (f"ods.{table_name}",))
    if cursor.fetchone()[0] is None:
        raise RuntimeError(f"缺少来源表：ods.{table_name}")
    missing = sorted(required_columns - table_columns(cursor, "ods", table_name))
    if missing:
        raise RuntimeError(f"ods.{table_name}缺少必需字段：{', '.join(missing)}")


def validate_numeric_column(cursor, table_name: str, column_name: str) -> None:
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*)
            FROM ods.{}
            WHERE NULLIF(REPLACE(BTRIM({}), ',', ''), '') IS NOT NULL
              AND REPLACE(BTRIM({}), ',', '') !~ %s
            """
        ).format(
            sql.Identifier(table_name),
            sql.Identifier(column_name),
            sql.Identifier(column_name),
        ),
        (r"^-?\d+(\.\d+)?$",),
    )
    invalid = cursor.fetchone()[0]
    if invalid:
        raise RuntimeError(
            f"ods.{table_name}.{column_name}存在{invalid}条无法解析的金额"
        )


def validate_batch_shop_mapping(cursor, table_name: str) -> list[tuple]:
    cursor.execute(
        sql.SQL(
            """
            WITH source_batches AS (
                SELECT batch_id, COUNT(*) AS source_rows
                FROM ods.{}
                GROUP BY batch_id
            )
            SELECT
                b.batch_id,
                b.source_rows,
                COUNT(c.batch_id) AS mapped_context_count,
                MAX(c.shop_code) AS shop_code,
                MAX(c.shop_name) AS shop_name
            FROM source_batches b
            LEFT JOIN common.v_ingest_batch_shop_context c
                ON c.batch_id = b.batch_id
               AND c.platform_code = 'tmall'
               AND c.target_table = %s
               AND c.shop_mapping_status = 'mapped'
            GROUP BY b.batch_id, b.source_rows
            ORDER BY b.batch_id NULLS FIRST
            """
        ).format(sql.Identifier(table_name)),
        (table_name,),
    )
    rows = cursor.fetchall()
    invalid = [row for row in rows if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"ods.{table_name}存在未映射或冲突批次：{invalid}")
    return rows


def validate_ods(cursor) -> dict[str, object]:
    validate_required_columns(
        cursor,
        "ods_tmall_aggregate_fund_raw",
        AGGREGATE_REQUIRED_COLUMNS,
    )
    validate_required_columns(
        cursor,
        "ods_tmall_alipay_fund_raw",
        ALIPAY_REQUIRED_COLUMNS,
    )
    for column_name in ("收入金额(元)", "支出金额(元)"):
        validate_numeric_column(
            cursor,
            "ods_tmall_aggregate_fund_raw",
            column_name,
        )
    for column_name in ("收入金额（+元）", "支出金额（-元）"):
        validate_numeric_column(
            cursor,
            "ods_tmall_alipay_fund_raw",
            column_name,
        )

    aggregate_batches = validate_batch_shop_mapping(
        cursor,
        "ods_tmall_aggregate_fund_raw",
    )
    alipay_batches = validate_batch_shop_mapping(
        cursor,
        "ods_tmall_alipay_fund_raw",
    )
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM ods.ods_tmall_aggregate_fund_raw),
            (
                SELECT COUNT(DISTINCT NULLIF(BTRIM("支付流水号"), ''))
                FROM ods.ods_tmall_aggregate_fund_raw
            ),
            (SELECT COUNT(*) FROM ods.ods_tmall_alipay_fund_raw),
            (
                SELECT COUNT(DISTINCT NULLIF(BTRIM(REPLACE("账务流水号", E'\t', '')), ''))
                FROM ods.ods_tmall_alipay_fund_raw
            )
        """
    )
    aggregate_rows, aggregate_unique, alipay_rows, alipay_unique = cursor.fetchone()
    from etl.common.finance_sources import prepare_finance_sources, effective_count
    prepare_finance_sources(cursor, "tmall")
    return {
        "raw_aggregate_rows": aggregate_rows,
        "raw_alipay_rows": alipay_rows,
        "aggregate_rows": effective_count(cursor, "ods_tmall_aggregate_fund_raw"),
        "aggregate_unique": aggregate_unique,
        "alipay_rows": effective_count(cursor, "ods_tmall_alipay_fund_raw"),
        "alipay_unique": alipay_unique,
        "aggregate_batches": aggregate_batches,
        "alipay_batches": alipay_batches,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in COMMENTED_TABLES:
        cursor.execute(
            """
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
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
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s
              AND c.relname = %s
              AND a.attnum > 0
              AND NOT a.attisdropped
              AND col_description(c.oid, a.attnum) IS NULL
            """,
            (schema_name, table_name),
        )
        missing.extend(
            f"{schema_name}.{table_name}.{row[0]}" for row in cursor.fetchall()
        )
    if missing:
        raise RuntimeError(f"新增或共享表存在缺失注释：{missing}")


def scalar(cursor, query: str, params: tuple = ()) -> Decimal:
    cursor.execute(query, params)
    return Decimal(cursor.fetchone()[0] or 0).quantize(Decimal("0.01"))


def validate_results(cursor) -> dict[str, object]:
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT (shop_identity_key, source_account_type, source_event_key)),
            MIN(stat_date),
            MAX(stat_date),
            COUNT(*) FILTER (
                WHERE standardized_note IS NULL
                   OR BTRIM(standardized_note) = ''
            )
        FROM dwd.dwd_tmall_platform_expense_source_detail
        """
    )
    expense_dwd = cursor.fetchone()
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT (shop_identity_key, source_account_type, source_event_key)),
            MIN(stat_date),
            MAX(stat_date)
        FROM dwd.dwd_tmall_main_business_income_source_detail
        """
    )
    income_dwd = cursor.fetchone()
    if expense_dwd[0] != expense_dwd[1] or income_dwd[0] != income_dwd[1]:
        raise RuntimeError("天猫指标DWD业务唯一键重复")

    cursor.execute(
        """
        SELECT DISTINCT d.source_business_type, d.secondary_category_name
        FROM dwd.dwd_tmall_platform_expense_source_detail d
        WHERE NOT EXISTS (
            SELECT 1
            FROM dim.dim_platform_fee_mapping m
            WHERE m.platform_code = d.platform_code
              AND m.source_document_type = 'fund'

              AND (
                    (
                        m.source_description_match_type = 'none'
                        AND (m.secondary_category_name = d.secondary_category_name OR (m.source_component_code IS NULL AND m.normalized_scene_name = d.secondary_category_name))
                    )
                    OR (
                        m.source_description_match_type <> 'none'
                        AND (
                            m.source_business_type IS NULL
                            OR m.source_business_type = d.source_business_type
                        )
                        AND (
                            m.source_description_match_type = 'any'
                            OR (
                                m.source_description_match_type = 'exact'
                                AND COALESCE(d.source_description, '')
                                    = COALESCE(m.source_description_match_value, '')
                            )
                            OR (
                                m.source_description_match_type = 'prefix'
                                AND COALESCE(d.source_description, '')
                                    LIKE COALESCE(m.source_description_match_value, '') || '%'
                            )
                            OR (
                                m.source_description_match_type = 'contains'
                                AND POSITION(
                                    COALESCE(m.source_description_match_value, '')
                                    IN COALESCE(d.source_description, '')
                                ) > 0
                            )
                        )
                    )
              )
        )
        ORDER BY d.source_business_type, d.secondary_category_name
        """
    )
    unmapped_fee_scene_rows = cursor.fetchall()
    unmapped_fee_scenes = len(unmapped_fee_scene_rows)
    cursor.execute(
        """
        SELECT COALESCE(SUM(d.directional_expense_amount), 0)
        FROM dwd.dwd_tmall_platform_expense_source_detail d
        WHERE NOT EXISTS (
            SELECT 1
            FROM dim.dim_platform_fee_mapping m
            WHERE m.platform_code = d.platform_code
              AND m.source_document_type = 'fund'

              AND (
                    (
                        m.source_description_match_type = 'none'
                        AND (m.secondary_category_name = d.secondary_category_name OR (m.source_component_code IS NULL AND m.normalized_scene_name = d.secondary_category_name))
                    )
                    OR (
                        m.source_description_match_type <> 'none'
                        AND (
                            m.source_business_type IS NULL
                            OR m.source_business_type = d.source_business_type
                        )
                        AND (
                            m.source_description_match_type = 'any'
                            OR (
                                m.source_description_match_type = 'exact'
                                AND COALESCE(d.source_description, '')
                                    = COALESCE(m.source_description_match_value, '')
                            )
                            OR (
                                m.source_description_match_type = 'prefix'
                                AND COALESCE(d.source_description, '')
                                    LIKE COALESCE(m.source_description_match_value, '') || '%'
                            )
                            OR (
                                m.source_description_match_type = 'contains'
                                AND POSITION(
                                    COALESCE(m.source_description_match_value, '')
                                    IN COALESCE(d.source_description, '')
                                ) > 0
                            )
                        )
                    )
              )
        )
        """
    )
    unmapped_expense_amount = Decimal(cursor.fetchone()[0] or 0).quantize(Decimal("0.01"))

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                main_order_no,
                standardized_note,
                signed_amount
            FROM dwd.dwd_tmall_platform_expense_source_detail
            WHERE source_account_type = 'aggregate'
              AND main_order_no IS NOT NULL
        ) a
        JOIN (
            SELECT
                SUBSTRING(source_description FROM '((33|51)[0-9]{17})') AS order_no,
                standardized_note,
                signed_amount
            FROM dwd.dwd_tmall_platform_expense_source_detail
            WHERE source_account_type = 'alipay'
        ) p
          ON p.order_no = a.main_order_no
         AND p.standardized_note = a.standardized_note
         AND p.signed_amount = a.signed_amount
        """
    )
    cross_account_duplicates = cursor.fetchone()[0]
    if cross_account_duplicates:
        raise RuntimeError(
            f"发现{cross_account_duplicates}条疑似跨账户重复资金事件"
        )

    from etl.platform_finance.operating_treatment import validate_projection
    income_dws_ads_diff, expense_dws_ads_diff = validate_projection(cursor,"tmall")

    if expense_dws_ads_diff or income_dws_ads_diff:
        raise RuntimeError(
            "天猫DWS与ADS存在差异："
            f"expense={expense_dws_ads_diff}, income={income_dws_ads_diff}"
        )

    cursor.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM ads.ads_platform_expense_company_shop_daily_category
                WHERE platform_code = 'tmall' AND company_code = 'unmapped'
            ),
            0,
            (
                SELECT COUNT(DISTINCT stat_date)
                FROM dws.dws_tmall_main_business_income_shop_daily_category
            )
        """
    )
    expense_unmapped, income_unmapped, income_days = cursor.fetchone()
    if expense_unmapped or income_unmapped:
        raise RuntimeError(
            "天猫ADS存在未匹配公司："
            f"expense={expense_unmapped}, income={income_unmapped}"
        )

    raw_net = scalar(
        cursor,
        """
        SELECT SUM(signed_amount)
        FROM dwd.dwd_tmall_platform_expense_source_detail
        """,
    )
    withdrawal = -scalar(
        cursor,
        """
        SELECT SUM(signed_amount)
        FROM dwd.dwd_tmall_platform_expense_source_detail
        WHERE standardized_note = '账户提现'
        """,
    )
    income_total = scalar(
        cursor,
        """
        SELECT SUM(income_amount)
        FROM dws.dws_tmall_main_business_income_shop_daily_category
        """,
    )
    expense_total = scalar(
        cursor,
        """
        SELECT SUM(expense_amount)
        FROM dws.dws_tmall_platform_expense_shop_daily_category
        """,
    )
    reconciliation_difference = (
        income_total
        - expense_total
        - unmapped_expense_amount
        - withdrawal
        - raw_net
    ).quantize(Decimal("0.01"))
    if reconciliation_difference != Decimal("0.00"):
        raise RuntimeError(
            "天猫两账户资金勾稽不平："
            f"difference={reconciliation_difference}"
        )

    cursor.execute(
        """
        WITH candidates AS (
            SELECT
                CASE
                    WHEN source_account_type = 'aggregate'
                     AND standardized_note = '订单收款'
                        THEN '聚合账户订单收款'
                    WHEN source_account_type = 'alipay'
                     AND standardized_note = '订单收款'
                        THEN '支付宝账户订单收款'
                    WHEN standardized_note = '销售退款'
                        THEN '销售退款'
                    WHEN source_business_type = '扣款退回'
                        THEN '费用退回'
                    WHEN standardized_note = '天猫佣金（类目系统）'
                        THEN '平台佣金'
                    WHEN standardized_note = '账户提现'
                        THEN '账户提现'
                END AS sample_type,
                source_account_type,
                source_business_type,
                standardized_note,
                signed_amount,
                directional_expense_amount,
                flow_no,
                source_event_key
            FROM dwd.dwd_tmall_platform_expense_source_detail
        )
        SELECT DISTINCT ON (sample_type)
            sample_type,
            source_account_type,
            source_business_type,
            standardized_note,
            signed_amount,
            directional_expense_amount,
            flow_no
        FROM candidates
        WHERE sample_type IS NOT NULL
        ORDER BY sample_type, source_event_key
        """
    )
    samples = cursor.fetchall()
    return {
        "expense_dwd": expense_dwd,
        "income_dwd": income_dwd,
        "empty_standardized_notes": expense_dwd[4],
        "cross_account_duplicates": cross_account_duplicates,
        "expense_dws_ads_diff": expense_dws_ads_diff,
        "income_dws_ads_diff": income_dws_ads_diff,
        "expense_unmapped": expense_unmapped,
        "income_unmapped": income_unmapped,
        "income_days": income_days,
        "raw_net": raw_net,
        "withdrawal": withdrawal,
        "income_total": income_total,
        "expense_total": expense_total,
        "unmapped_fee_scenes": unmapped_fee_scenes,
        "unmapped_fee_scene_names": [
            row[1] for row in unmapped_fee_scene_rows
        ],
        "unmapped_expense_amount": unmapped_expense_amount,
        "reconciliation_difference": reconciliation_difference,
        "samples": samples,
    }


def validate_current_baseline(cursor, ods: dict[str, object]) -> None:
    baseline = CURRENT_BASELINE
    if ods["aggregate_rows"] != baseline["aggregate_rows"]:
        raise RuntimeError(
            "聚合账户ODS基准不一致："
            f"actual={ods['aggregate_rows']}, expected={baseline['aggregate_rows']}"
        )
    if ods["alipay_rows"] != baseline["alipay_rows"]:
        raise RuntimeError(
            "支付宝账户ODS基准不一致："
            f"actual={ods['alipay_rows']}, expected={baseline['alipay_rows']}"
        )
    params = (
        baseline["shop_code"],
        baseline["date_from"],
        baseline["date_to"],
    )
    income_total = scalar(
        cursor,
        """
        SELECT SUM(income_amount)
        FROM dws.dws_tmall_main_business_income_shop_daily_category
        WHERE platform_code = 'tmall'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        """,
        params,
    )
    expense_total = scalar(
        cursor,
        """
        SELECT SUM(expense_amount)
        FROM dws.dws_tmall_platform_expense_shop_daily_category
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        """,
        params,
    )
    if income_total != baseline["income_total"]:
        raise RuntimeError(
            f"天猫主营业务收入基准不一致：{income_total} != {baseline['income_total']}"
        )
    if expense_total != baseline["expense_total"]:
        raise RuntimeError(
            f"天猫主营业务支出基准不一致：{expense_total} != {baseline['expense_total']}"
        )

    cursor.execute(
        """
        SELECT primary_category_code, ROUND(SUM(income_amount), 2)
        FROM dws.dws_tmall_main_business_income_shop_daily_category
        WHERE platform_code = 'tmall'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY primary_category_code
        """,
        params,
    )
    actual_income = {row[0]: Decimal(row[1]) for row in cursor.fetchall()}
    if actual_income != baseline["income_primary"]:
        raise RuntimeError(
            f"天猫收入一级分类基准不一致：{actual_income}"
        )

    cursor.execute(
        """
        SELECT primary_category_code, ROUND(SUM(expense_amount), 2)
        FROM dws.dws_tmall_platform_expense_shop_daily_category
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY primary_category_code
        """,
        params,
    )
    actual_expense = {row[0]: Decimal(row[1]) for row in cursor.fetchall()}
    if actual_expense != baseline["expense_primary"]:
        raise RuntimeError(
            f"天猫支出一级分类基准不一致：{actual_expense}"
        )


def main() -> None:
    args = build_parser().parse_args()
    conn = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with conn.cursor() as cursor:
            execute_files(cursor, PREPARE_SQL_FILES)
            ods = validate_ods(cursor)
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            validate_comments(cursor)
            result = validate_results(cursor)
            if args.enforce_current_baseline:
                validate_current_baseline(cursor, ods)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("天猫主营业务收入与支出刷新成功")
    print(
        "ODS："
        f"聚合账户={ods['aggregate_rows']}行/{ods['aggregate_unique']}唯一流水，"
        f"支付宝账户={ods['alipay_rows']}行/{ods['alipay_unique']}唯一流水"
    )
    print(f"聚合账户批次映射：{ods['aggregate_batches']}")
    print(f"支付宝账户批次映射：{ods['alipay_batches']}")
    print(
        "DWD："
        f"收入={result['income_dwd'][0]}行，"
        f"费用={result['expense_dwd'][0]}行，"
        f"日期={result['income_dwd'][2]}至{result['income_dwd'][3]}"
    )
    print(
        "结果："
        f"主营业务收入={result['income_total']:.2f}，"
        f"主营业务支出={result['expense_total']:.2f}，"
        f"提现={result['withdrawal']:.2f}，"
        f"原始资金净变动={result['raw_net']:.2f}，"
        f"勾稽差额={result['reconciliation_difference']:.2f}"
    )
    print(
        "质量："
        f"收入自然日={result['income_days']}，"
        f"跨账户重复={result['cross_account_duplicates']}，"
        f"收入DWS/ADS差异={result['income_dws_ads_diff']}，"
        f"费用DWS/ADS差异={result['expense_dws_ads_diff']}，"
        f"公司未匹配={result['income_unmapped']}/{result['expense_unmapped']}"
    )
    if result["unmapped_fee_scenes"]:
        print(
            "警告："
            f"发现{result['unmapped_fee_scenes']}个未映射天猫费用场景，"
            f"原始费用已保留，暂未计入平台费用（金额={result['unmapped_expense_amount']:.2f}）。"
        )
        for scene in result["unmapped_fee_scene_names"][:50]:
            print(f"  - {scene}")
        if result["unmapped_fee_scenes"] > 50:
            print(
                f"  ……其余{result['unmapped_fee_scenes'] - 50}个场景请在经营配置中心查看"
            )
    if result["empty_standardized_notes"]:
        print(
            "警告："
            f"有{result['empty_standardized_notes']}条天猫资金备注为空，"
            "已保留原始费用场景，等待财务确认映射。"
        )
    print("DWD抽样：")
    for row in result["samples"]:
        print(row)
    if args.enforce_current_baseline:
        print("2026年6月专项基准校验通过")


if __name__ == "__main__":
    main()
