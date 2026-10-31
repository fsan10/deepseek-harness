#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新京东主营业务收入、平台支出及分类明细，并执行专项验收。"""

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
    "dim/305_dim_platform_fee_mapping_postgres.sql",
    "dim/306_seed_douyin_platform_fee_mapping_postgres.sql",
    "dim/313_seed_ks_platform_fee_mapping_postgres.sql",
    "dim/318_seed_jd_platform_fee_mapping_postgres.sql",
    "dim/373_dim_platform_finance_source_policy_postgres.sql",
]
CREATE_SQL_FILES = [
    "douyin/platform_expense/308_dws_douyin_platform_expense_shop_daily_category_postgres.sql",
    "ks/platform_expense/315_dws_ks_platform_expense_shop_daily_category_postgres.sql",
    "jd/platform_expense/319_dwd_jd_platform_expense_source_detail_postgres.sql",
    "jd/platform_expense/320_dws_jd_platform_expense_shop_daily_category_postgres.sql",
    "jd/main_business_income/323_dwd_jd_main_business_income_source_detail_postgres.sql",
    "jd/main_business_income/324_dws_jd_main_business_income_shop_daily_category_postgres.sql",
    "ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql",
]
REFRESH_SQL_FILES = [
    "jd/platform_expense/321_refresh_dwd_jd_platform_expense_source_detail_postgres.sql",
    "jd/platform_expense/322_refresh_dws_jd_platform_expense_shop_daily_category_postgres.sql",
    "jd/main_business_income/326_refresh_dwd_jd_main_business_income_source_detail_postgres.sql",
    "jd/main_business_income/327_refresh_dws_jd_main_business_income_shop_daily_category_postgres.sql",
    "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
]

SETTLEMENT_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "订单编号",
    "单据编号",
    "单据类型",
    "商户订单号",
    "费用结算时间",
    "费用项",
    "金额",
    "收支方向",
    "账单日期",
    "店铺号",
}
FUND_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "商户订单号",
    "交易订单号",
    "支出类型",
    "交易金额",
    "交易类型",
    "入账时间",
    "资金动账备注",
}
COMMENTED_TABLES = [
    ("dim", "dim_platform_fee_mapping"),
    ("dwd", "dwd_jd_platform_expense_source_detail"),
    ("dws", "dws_jd_platform_expense_shop_daily_category"),
    ("dwd", "dwd_jd_main_business_income_source_detail"),
    ("dws", "dws_jd_main_business_income_shop_daily_category"),
    ("ads", "ads_platform_expense_company_shop_daily_category"),
]
CURRENT_BASELINE = {
    "shop_code": "123572735",
    "date_from": "2026-06-01",
    "date_to": "2026-06-30",
    "income_total": Decimal("13603.76"),
    "income_primary": {
        "product_sales_income": Decimal("15518.76"),
        "sales_refund": Decimal("-1915.00"),
    },
    "expense_total": Decimal("10143.06"),
    "expense_source": {
        "settlement": Decimal("842.09"),
        "fund": Decimal("9300.97"),
    },
    "expense_primary": {
        "platform_commission": Decimal("473.81"),
        "platform_service_fee": Decimal("82.72"),
        "product_insurance_expense": Decimal("149.15"),
        "freight_insurance_expense": Decimal("105.58"),
        "jd_bean_expense": Decimal("6.08"),
        "promotion_expense": Decimal("9308.72"),
        "after_sales_compensation_expense": Decimal("17.00"),
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新京东主营业务收入和支出指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="校验京东MOCK饮品旗舰店2026年6月已确认基准。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    from etl.platform_finance.operating_treatment import execute_finance_files
    execute_finance_files(cursor, file_names)
    if file_names == PREPARE_SQL_FILES:
        cursor.execute((SQL_DIR / 'common/468_ingest_source_day_selection_postgres.sql').read_text(encoding='utf-8'))


def table_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = %s
        """,
        (table_name,),
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
    missing = sorted(required_columns - table_columns(cursor, table_name))
    if missing:
        raise RuntimeError(f"ods.{table_name}缺少必需字段：{', '.join(missing)}")


def validate_numeric_column(cursor, table_name: str, column_name: str) -> None:
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*)
            FROM ods.{}
            WHERE NULLIF(
                NULLIF(REPLACE(BTRIM({}), ',', ''), ''),
                '-'
            ) IS NOT NULL
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
        f"""
        WITH source_batches AS (
            SELECT batch_id, COUNT(*) AS source_rows
            FROM ods.{table_name}
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
           AND c.platform_code = 'jd'
           AND c.target_table = %s
           AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id, b.source_rows
        ORDER BY b.batch_id NULLS FIRST
        """,
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
        "ods_jd_settlement_raw",
        SETTLEMENT_REQUIRED_COLUMNS,
    )
    validate_required_columns(
        cursor,
        "ods_jd_fund_raw",
        FUND_REQUIRED_COLUMNS,
    )
    validate_numeric_column(cursor, "ods_jd_settlement_raw", "金额")
    validate_numeric_column(cursor, "ods_jd_fund_raw", "交易金额")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(
                REPLACE(REPLACE(BTRIM("单据编号"), '="', ''), '"', ''),
                ''
            )),
            COUNT(*) FILTER (
                WHERE BTRIM("账单日期") !~ %s
                  AND BTRIM("账单日期") !~ %s
            ),
            COUNT(*) FILTER (WHERE BTRIM("收支方向") NOT IN ('收入', '支出')),
            COUNT(*) FILTER (
                WHERE BTRIM("币种") <> 'CNY'
                   OR (
                       BTRIM("收支方向") = '收入'
                       AND (
                           BTRIM("商家应收/应付") <> '应收'
                           OR REPLACE(BTRIM("金额"), ',', '')::numeric < 0
                       )
                   )
                   OR (
                       BTRIM("收支方向") = '支出'
                       AND (
                           BTRIM("商家应收/应付") <> '应付'
                           OR REPLACE(BTRIM("金额"), ',', '')::numeric > 0
                       )
                   )
            )
        FROM common.v_selected_jd_settlement_raw
        """,
        (r"^[0-9]{8}$", r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
    )
    (
        settlement_rows,
        settlement_unique_documents,
        invalid_settlement_dates,
        invalid_settlement_directions,
        settlement_sign_errors,
    ) = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT MD5(
                CONCAT_WS(
                    E'\\x1f',
                    BTRIM(COALESCE("商户订单号", '')),
                    BTRIM(COALESCE("交易订单号", '')),
                    BTRIM(COALESCE("支出类型", '')),
                    BTRIM(COALESCE("交易金额", '')),
                    BTRIM(COALESCE("交易类型", '')),
                    BTRIM(COALESCE("入账时间", '')),
                    BTRIM(COALESCE("资金动账备注", ''))
                )
            )),
            COUNT(*) FILTER (
                WHERE BTRIM("入账时间") !~ %s
            ),
            COUNT(*) FILTER (WHERE BTRIM("支出类型") NOT IN ('收入', '支出')),
            COUNT(*) FILTER (
                WHERE REPLACE(BTRIM("交易金额"), ',', '')::numeric < 0
            )
        FROM common.v_selected_jd_fund_raw
        """,
        (r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$",),
    )
    (
        fund_rows,
        fund_unique_events,
        invalid_fund_dates,
        invalid_fund_directions,
        negative_fund_amounts,
    ) = cursor.fetchone()
    if settlement_rows == 0 or fund_rows == 0:
        raise RuntimeError(
            f"京东主营收支ODS无数据：settlement={settlement_rows}，fund={fund_rows}"
        )
    if (
        invalid_settlement_dates
        or invalid_settlement_directions
        or settlement_sign_errors
        or invalid_fund_dates
        or invalid_fund_directions
        or negative_fund_amounts
    ):
        raise RuntimeError(
            "京东来源日期、方向或符号非法："
            f"settlement_date={invalid_settlement_dates}，"
            f"settlement_direction={invalid_settlement_directions}，"
            f"settlement_sign={settlement_sign_errors}，"
            f"fund_date={invalid_fund_dates}，"
            f"fund_direction={invalid_fund_directions}，"
            f"fund_negative={negative_fund_amounts}"
        )

    # Document and wallet identities are local to the standard shop.
    cursor.execute('''SELECT COUNT(DISTINCT (c.shop_identity_key,
        NULLIF(REPLACE(REPLACE(BTRIM(r."单据编号"),'="',''),'"',''),'')))
        FROM common.v_selected_jd_settlement_raw r
        JOIN common.v_ingest_batch_shop_context c USING(batch_id)''')
    settlement_unique_documents = cursor.fetchone()[0]
    cursor.execute('''SELECT COUNT(DISTINCT (c.shop_identity_key,MD5(CONCAT_WS(E'\\x1f',
        BTRIM(COALESCE(r."商户订单号",'')),BTRIM(COALESCE(r."交易订单号",'')),
        BTRIM(COALESCE(r."支出类型",'')),BTRIM(COALESCE(r."交易金额",'')),
        BTRIM(COALESCE(r."交易类型",'')),BTRIM(COALESCE(r."入账时间",'')),
        BTRIM(COALESCE(r."资金动账备注",'')))))) FROM common.v_selected_jd_fund_raw r
        JOIN common.v_ingest_batch_shop_context c USING(batch_id)''')
    fund_unique_events = cursor.fetchone()[0]
    return {
        "settlement_rows": settlement_rows,
        "settlement_unique_documents": settlement_unique_documents,
        "fund_rows": fund_rows,
        "fund_unique_events": fund_unique_events,
        "fund_duplicate_versions": fund_rows - fund_unique_events,
        "settlement_mappings": validate_batch_shop_mapping(
            cursor,
            "ods_jd_settlement_raw",
        ),
        "fund_mappings": validate_batch_shop_mapping(
            cursor,
            "ods_jd_fund_raw",
        ),
    }


def scalar(cursor, statement: str, params: tuple = ()):
    if params:
        cursor.execute(statement, params)
    else:
        cursor.execute(statement)
    return cursor.fetchone()[0]


def validate_comments(cursor) -> None:
    cursor.execute(
        """
        SELECT
            t.table_schema,
            t.table_name,
            obj_description(c.oid, 'pg_class') AS table_comment,
            COUNT(col.column_name) AS column_count,
            COUNT(col_description(c.oid, col.ordinal_position))
                FILTER (
                    WHERE col_description(c.oid, col.ordinal_position)
                        IS NOT NULL
                ) AS commented_column_count
        FROM information_schema.tables t
        JOIN pg_class c ON c.relname = t.table_name
        JOIN pg_namespace n
          ON n.oid = c.relnamespace
         AND n.nspname = t.table_schema
        JOIN information_schema.columns col
          ON col.table_schema = t.table_schema
         AND col.table_name = t.table_name
        WHERE (t.table_schema, t.table_name) IN (
            ('dim', 'dim_platform_fee_mapping'),
            ('dwd', 'dwd_jd_platform_expense_source_detail'),
            ('dws', 'dws_jd_platform_expense_shop_daily_category'),
            ('dwd', 'dwd_jd_main_business_income_source_detail'),
            ('dws', 'dws_jd_main_business_income_shop_daily_category'),
            ('ads', 'ads_platform_expense_company_shop_daily_category')
        )
        GROUP BY t.table_schema, t.table_name, c.oid
        ORDER BY t.table_schema, t.table_name
        """
    )
    rows = cursor.fetchall()
    if len(rows) != len(COMMENTED_TABLES):
        raise RuntimeError(f"京东主营收支新增表数量不完整：{rows}")
    invalid = [row for row in rows if not row[2] or row[3] != row[4]]
    if invalid:
        raise RuntimeError(f"京东主营收支表或字段注释不完整：{invalid}")


def validate_mapping_coverage(cursor) -> int:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dwd.dwd_jd_platform_expense_source_detail d
        WHERE NOT EXISTS (
            SELECT 1
            FROM dim.dim_platform_fee_mapping m
            WHERE m.platform_code = d.platform_code
              AND m.source_document_type = d.source_document_type

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
                                    LIKE COALESCE(
                                        m.source_description_match_value,
                                        ''
                                    ) || '%'
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
    return cursor.fetchone()[0]


def validate_dws_ads_difference(cursor, metric: str) -> int:
    from etl.platform_finance.operating_treatment import validate_projection
    return validate_projection(cursor,"jd")[0 if metric=="income" else 1]


def validate_settlement_to_wallet_reconciliation(cursor) -> dict[str, object]:
    from etl.jd.wallet_reconciliation import validate
    return validate(cursor)


def validate_pipeline(cursor, ods: dict[str, object]) -> dict[str, object]:
    expected_dwd_rows = (
        int(ods["settlement_unique_documents"])
        + int(ods["fund_unique_events"])
    )
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM dwd.dwd_jd_platform_expense_source_detail),
            (SELECT COUNT(*) FROM dwd.dwd_jd_main_business_income_source_detail)
        """
    )
    expense_dwd_rows, income_dwd_rows = cursor.fetchone()
    if (expense_dwd_rows, income_dwd_rows) != (
        expected_dwd_rows,
        expected_dwd_rows,
    ):
        raise RuntimeError(
            "京东主营收支DWD行数不等于去重来源："
            f"{expense_dwd_rows}/{income_dwd_rows}!={expected_dwd_rows}"
        )

    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) - COUNT(DISTINCT (
                shop_identity_key,
                source_document_type,
                source_event_key
            )) FROM dwd.dwd_jd_platform_expense_source_detail),
            (SELECT COUNT(*) - COUNT(DISTINCT (
                shop_identity_key,
                source_document_type,
                source_event_key
            )) FROM dwd.dwd_jd_main_business_income_source_detail)
        """
    )
    duplicate_dwd = cursor.fetchone()
    if any(duplicate_dwd):
        raise RuntimeError(f"京东主营收支DWD主键重复：{duplicate_dwd}")

    mapping_misses = validate_mapping_coverage(cursor)
    if mapping_misses:
        raise RuntimeError(f"京东平台费用DWD有{mapping_misses}条未命中映射")

    income_difference = validate_dws_ads_difference(cursor, "income")
    expense_difference = validate_dws_ads_difference(cursor, "expense")
    if income_difference or expense_difference:
        raise RuntimeError(
            "京东主营收支DWS与ADS双向差异："
            f"income={income_difference}，expense={expense_difference}"
        )

    cursor.execute(
        """
        SELECT
            0,
            (SELECT COUNT(*) FROM ads.ads_platform_expense_company_shop_daily_category
             WHERE platform_code = 'jd' AND company_code = 'unmapped'),
            0,
            (SELECT COUNT(*) FROM (
                SELECT
                    stat_date,
                    platform_code,
                    company_code,
                    shop_code,
                    source_document_type,
                    secondary_category_code
                FROM ads.ads_platform_expense_company_shop_daily_category
                GROUP BY 1, 2, 3, 4, 5, 6
                HAVING COUNT(*) > 1
            ) duplicated)
        """
    )
    unmapped_income, unmapped_expense, duplicate_income_ads, duplicate_expense_ads = (
        cursor.fetchone()
    )
    if any(
        (
            unmapped_income,
            unmapped_expense,
            duplicate_income_ads,
            duplicate_expense_ads,
        )
    ):
        raise RuntimeError(
            "京东主营收支ADS公司映射或主键异常："
            f"unmapped={unmapped_income}/{unmapped_expense}，"
            f"duplicate={duplicate_income_ads}/{duplicate_expense_ads}"
        )

    reconciliation = validate_settlement_to_wallet_reconciliation(cursor)

    duplicate_refunds = scalar(
        cursor,
        """
        SELECT COUNT(*)
        FROM dwd.dwd_jd_main_business_income_source_detail fund
        WHERE fund.source_document_type = 'fund'
          AND fund.source_business_type = '转账-售后退款质保金扣除'
          AND EXISTS (
              SELECT 1
              FROM dwd.dwd_jd_main_business_income_source_detail settlement
              WHERE settlement.source_document_type = 'settlement'
                AND settlement.fee_item_name = '货款'
                AND settlement.document_type IN ('取消退款单', '售后服务单')
                AND settlement.order_no = fund.related_order_no
                AND settlement.signed_amount < 0
          )
        """,
    )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(stat_date),
            MAX(stat_date),
            ROUND(SUM(income_amount), 2)
        FROM dws.dws_jd_main_business_income_shop_daily_category
        """
    )
    income_ads_rows, income_date_from, income_date_to, all_income = (
        cursor.fetchone()
    )
    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(stat_date),
            MAX(stat_date),
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'jd'
        """
    )
    expense_ads_rows, expense_date_from, expense_date_to, all_expense = (
        cursor.fetchone()
    )

    cursor.execute(
        """
        WITH sample_pool AS (
            SELECT 'income' AS source_kind, primary_category_name,
                   secondary_category_name, income_amount AS amount
            FROM dws.dws_jd_main_business_income_shop_daily_category
            WHERE income_amount <> 0
            UNION ALL
            SELECT 'expense', primary_category_name, secondary_category_name,
                   expense_amount
            FROM dws.dws_jd_platform_expense_shop_daily_category
            WHERE expense_amount <> 0
        ),
        representative AS (
            SELECT DISTINCT ON (
                source_kind,
                primary_category_name,
                secondary_category_name
            )
                source_kind,
                primary_category_name,
                secondary_category_name,
                amount
            FROM sample_pool
            ORDER BY
                source_kind,
                primary_category_name,
                secondary_category_name,
                ABS(amount) DESC
        )
        SELECT *
        FROM representative
        ORDER BY source_kind, primary_category_name, secondary_category_name
        LIMIT 20
        """
    )
    samples = cursor.fetchall()
    if len(samples) < 5:
        raise RuntimeError(f"京东主营收支分类公式抽样不足5条：{samples}")

    validate_comments(cursor)
    return {
        "expected_dwd_rows": expected_dwd_rows,
        "income_ads_rows": income_ads_rows,
        "income_date_from": income_date_from,
        "income_date_to": income_date_to,
        "all_income": all_income,
        "expense_ads_rows": expense_ads_rows,
        "expense_date_from": expense_date_from,
        "expense_date_to": expense_date_to,
        "all_expense": all_expense,
        "reconciliation": reconciliation,
        "duplicate_refunds": duplicate_refunds,
        "samples": samples,
        "income_difference": income_difference,
        "expense_difference": expense_difference,
        "unmapped_income": unmapped_income,
        "unmapped_expense": unmapped_expense,
    }


def validate_current_baseline(cursor) -> dict[str, object]:
    baseline = CURRENT_BASELINE
    params = (
        baseline["shop_code"],
        baseline["date_from"],
        baseline["date_to"],
    )
    cursor.execute(
        """
        SELECT
            primary_category_code,
            ROUND(SUM(income_amount), 2)
        FROM dws.dws_jd_main_business_income_shop_daily_category
        WHERE platform_code = 'jd'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY primary_category_code
        """,
        params,
    )
    income_primary = dict(cursor.fetchall())
    income_total = sum(income_primary.values(), Decimal("0"))
    if (
        income_primary != baseline["income_primary"]
        or income_total != baseline["income_total"]
    ):
        raise RuntimeError(
            "京东2026年6月主营业务收入基准不一致："
            f"actual={income_primary}/{income_total}，"
            f"expected={baseline['income_primary']}/{baseline['income_total']}"
        )

    cursor.execute(
        """
        SELECT
            source_document_type,
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'jd'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY source_document_type
        """,
        params,
    )
    expense_source = dict(cursor.fetchall())
    cursor.execute(
        """
        SELECT
            primary_category_code,
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'jd'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY primary_category_code
        """,
        params,
    )
    expense_primary = dict(cursor.fetchall())
    expense_total = sum(expense_primary.values(), Decimal("0"))
    if (
        expense_source != baseline["expense_source"]
        or expense_primary != baseline["expense_primary"]
        or expense_total != baseline["expense_total"]
    ):
        raise RuntimeError(
            "京东2026年6月主营业务支出基准不一致："
            f"source={expense_source}，primary={expense_primary}，"
            f"total={expense_total}；expected={baseline}"
        )

    return {
        "income_total": income_total,
        "income_primary": income_primary,
        "expense_total": expense_total,
        "expense_source": expense_source,
        "expense_primary": expense_primary,
    }


def main() -> None:
    args = build_parser().parse_args()
    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        connection.autocommit = False
        with connection.cursor() as cursor:
            execute_files(cursor, PREPARE_SQL_FILES)
            ods = validate_ods(cursor)
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_pipeline(cursor, ods)
            baseline = (
                validate_current_baseline(cursor)
                if args.enforce_current_baseline
                else None
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(
        "ODS原始/去重："
        f"settlement={ods['settlement_rows']}/"
        f"{ods['settlement_unique_documents']}，"
        f"fund={ods['fund_rows']}/{ods['fund_unique_events']}，"
        f"资金重复版本={ods['fund_duplicate_versions']}"
    )
    print(f"收入/费用DWD各{result['expected_dwd_rows']}行")
    print(
        "收入ADS："
        f"{result['income_ads_rows']}行，"
        f"{result['income_date_from']}至{result['income_date_to']}，"
        f"全量{result['all_income']}"
    )
    print(
        "费用ADS："
        f"{result['expense_ads_rows']}行，"
        f"{result['expense_date_from']}至{result['expense_date_to']}，"
        f"全量{result['all_expense']}"
    )
    reconciliation = result["reconciliation"]
    print(
        "结算到钱包跨日对账："
        f"结算单据组={reconciliation['settlement_group_count']}，"
        f"来源批次数={reconciliation['source_batch_count']}，"
        f"已匹配={reconciliation['matched_count']}，"
        f"待到账={reconciliation['pending_count']}，"
        f"真实缺失={reconciliation['missing_count']}，"
        f"金额不一致={reconciliation['amount_mismatch_count']}，"
        f"结算合计={reconciliation['settlement_total']}，"
        f"已到账合计={reconciliation['fund_total']}，"
        f"结算日={reconciliation['settlement_date_from']}~"
        f"{reconciliation['settlement_date_to']}，"
        f"资金交易日期={reconciliation['fund_extract_from']}~{reconciliation['fund_extract_to']}，"
        f"未覆盖={reconciliation['uncovered_count']}，完整覆盖未知={reconciliation['coverage_unknown_count']}"
    )
    print(f"结算来源批次清单：{reconciliation['settlement_batches']}")
    print(f"资金已验证完整覆盖范围：{reconciliation['fund_coverage']}")
    print(f"跨表重复退款数：{result['duplicate_refunds']}")
    print(f"公式与分类抽样：{result['samples']}")
    print(
        "DWS/ADS差异与公司未匹配："
        f"{result['income_difference']}/{result['expense_difference']}；"
        f"{result['unmapped_income']}/{result['unmapped_expense']}"
    )
    if baseline is not None:
        print(f"京东2026年6月专项基准：{baseline}")


if __name__ == "__main__":
    main()
