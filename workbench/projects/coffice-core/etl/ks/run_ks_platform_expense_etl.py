#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新快手平台费用独立指标链路并执行分层验收。"""

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
    "dim/373_dim_platform_finance_source_policy_postgres.sql",
]
CREATE_SQL_FILES = [
    "douyin/platform_expense/307_dwd_douyin_platform_expense_source_detail_postgres.sql",
    "douyin/platform_expense/308_dws_douyin_platform_expense_shop_daily_category_postgres.sql",
    "ks/platform_expense/314_dwd_ks_platform_expense_source_detail_postgres.sql",
    "ks/platform_expense/315_dws_ks_platform_expense_shop_daily_category_postgres.sql",
    "ads/platform_expense/311_ads_platform_expense_company_shop_daily_category_postgres.sql",
]
REFRESH_SQL_FILES = [
    "ks/platform_expense/316_refresh_dwd_ks_platform_expense_source_detail_postgres.sql",
    "ks/platform_expense/317_refresh_dws_ks_platform_expense_shop_daily_category_postgres.sql",
    "ads/platform_expense/312_refresh_ads_platform_expense_company_shop_daily_category_postgres.sql",
]

SETTLEMENT_AMOUNT_COLUMNS = {
    "支付营销回退（元）",
    "技术服务费(元)",
    "预售增收技术服务费（元）",
    "达人佣金(元)",
    "团长佣金(元)",
    "快赚客佣金(元)",
    "服务商佣金(元)",
    "其他收费",
}
SETTLEMENT_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "商家ID",
    "订单号",
    "实际结算时间",
    "账户名称",
    *SETTLEMENT_AMOUNT_COLUMNS,
}
FUND_REQUIRED_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "账务流水号",
    "关联业务单号",
    "入账时间",
    "账务方向",
    "发生额（元）",
    "业务类型",
    "描述",
}
COMMENTED_TABLES = [
    ("dim", "dim_platform_fee_mapping"),
    ("dwd", "dwd_ks_platform_expense_source_detail"),
    ("dws", "dws_ks_platform_expense_shop_daily_category"),
    ("ads", "ads_platform_expense_company_shop_daily_category"),
]
CURRENT_BASELINE = {
    "shop_code": "3527127781",
    "date_from": "2026-06-01",
    "date_to": "2026-06-30",
    "settlement_expense": Decimal("81713.85"),
    "fund_expense": Decimal("1215.70"),
    "total_expense": Decimal("82929.55"),
    "primary_totals": {
        "influencer_commission": Decimal("73861.49"),
        "platform_service_fee": Decimal("6116.85"),
        "other_platform_expense": Decimal("1534.15"),
        "consolidated_shipping_expense": Decimal("178.00"),
        "return_shipping_expense": Decimal("713.40"),
        "small_payment_expense": Decimal("425.66"),
        "penalty_expense": Decimal("100.00"),
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新快手平台费用指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="校验快手陌时专卖店2026年6月已确认费用基准。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    from etl.platform_finance.operating_treatment import execute_finance_files
    execute_finance_files(cursor, file_names)


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
           AND c.platform_code = 'ks'
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
        "ods_ks_settlement_raw",
        SETTLEMENT_REQUIRED_COLUMNS,
    )
    validate_required_columns(cursor, "ods_ks_fund_raw", FUND_REQUIRED_COLUMNS)
    for column_name in SETTLEMENT_AMOUNT_COLUMNS:
        validate_numeric_column(cursor, "ods_ks_settlement_raw", column_name)
    validate_numeric_column(cursor, "ods_ks_fund_raw", "发生额（元）")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (
                WHERE NULLIF(NULLIF(BTRIM("实际结算时间"), ''), '-') IS NULL
                   OR BTRIM("实际结算时间") !~ %s
            )
        FROM ods.ods_ks_settlement_raw
        """,
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    settlement_rows, invalid_settlement_dates = cursor.fetchone()
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) FILTER (
                WHERE NULLIF(NULLIF(BTRIM("入账时间"), ''), '-') IS NULL
                   OR BTRIM("入账时间") !~ %s
            ),
            COUNT(*) FILTER (WHERE BTRIM("账务方向") NOT IN ('收', '支')),
            COUNT(*) FILTER (WHERE NULLIF(BTRIM("业务类型"), '') IS NULL),
            COUNT(*) FILTER (
                WHERE COALESCE(
                    NULLIF(
                        NULLIF(REPLACE(BTRIM("发生额（元）"), ',', ''), ''),
                        '-'
                    )::numeric,
                    0
                ) < 0
            )
        FROM ods.ods_ks_fund_raw
        """,
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    (
        fund_rows,
        invalid_fund_dates,
        invalid_fund_directions,
        missing_fund_business_types,
        negative_fund_amounts,
    ) = cursor.fetchone()
    if settlement_rows == 0 or fund_rows == 0:
        raise RuntimeError(
            f"快手平台费用ODS无数据：settlement={settlement_rows}，fund={fund_rows}"
        )
    if invalid_settlement_dates or invalid_fund_dates:
        raise RuntimeError(
            "来源日期存在非法值："
            f"settlement={invalid_settlement_dates}，fund={invalid_fund_dates}"
        )
    if (
        invalid_fund_directions
        or missing_fund_business_types
        or negative_fund_amounts
    ):
        raise RuntimeError(
            "资金ODS方向、业务类型或金额非法："
            f"direction={invalid_fund_directions}，"
            f"business_type={missing_fund_business_types}，"
            f"negative_amount={negative_fund_amounts}"
        )
    from etl.common.finance_sources import prepare_finance_sources, effective_count
    prepare_finance_sources(cursor, "ks")
    return {
        "raw_settlement_rows": settlement_rows,
        "raw_fund_rows": fund_rows,
        "settlement_rows": effective_count(cursor, "ods_ks_settlement_raw"),
        "fund_rows": effective_count(cursor, "ods_ks_fund_raw"),
        "settlement_mappings": validate_batch_shop_mapping(
            cursor,
            "ods_ks_settlement_raw",
        ),
        "fund_mappings": validate_batch_shop_mapping(
            cursor,
            "ods_ks_fund_raw",
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
            ('dwd', 'dwd_ks_platform_expense_source_detail'),
            ('dws', 'dws_ks_platform_expense_shop_daily_category'),
            ('ads', 'ads_platform_expense_company_shop_daily_category')
        )
        GROUP BY t.table_schema, t.table_name, c.oid
        ORDER BY t.table_schema, t.table_name
        """
    )
    rows = cursor.fetchall()
    if len(rows) != len(COMMENTED_TABLES):
        raise RuntimeError(f"快手平台费用新增表数量不完整：{rows}")
    invalid = [row for row in rows if not row[2] or row[3] != row[4]]
    if invalid:
        raise RuntimeError(f"快手平台费用新增表或字段注释不完整：{invalid}")


def validate_pipeline(cursor, ods: dict[str, object]) -> dict[str, object]:
    expected_dwd_rows = int(ods["settlement_rows"]) * 8 + int(ods["fund_rows"])
    dwd_rows = scalar(
        cursor,
        "SELECT COUNT(*) FROM dwd.dwd_ks_platform_expense_source_detail",
    )
    if dwd_rows != expected_dwd_rows:
        raise RuntimeError(f"快手费用DWD行数{dwd_rows}不等于预期{expected_dwd_rows}")

    duplicate_dwd = scalar(
        cursor,
        """
        SELECT COUNT(*) - COUNT(DISTINCT (
            source_document_type,
            source_id,
            secondary_category_name
        ))
        FROM dwd.dwd_ks_platform_expense_source_detail
        """,
    )
    if duplicate_dwd:
        raise RuntimeError(f"快手费用DWD主键重复：{duplicate_dwd}")

    formula_errors = scalar(
        cursor,
        """
        SELECT COUNT(*)
        FROM dwd.dwd_ks_platform_expense_source_detail d
        WHERE (
            d.source_document_type = 'settlement'
            AND d.directional_expense_amount <> d.source_amount
        ) OR (
            d.source_document_type = 'fund'
            AND d.directional_expense_amount <> CASE d.source_direction
                WHEN '支' THEN d.source_amount
                WHEN '收' THEN -d.source_amount
                ELSE 0
            END
        )
        """,
    )
    if formula_errors:
        raise RuntimeError(f"快手费用方向金额公式异常：{formula_errors}条")

    mapping_duplicates = scalar(
        cursor,
        """
        SELECT COUNT(*)
        FROM (
            SELECT platform_code, source_document_type, secondary_category_name
            FROM dim.dim_platform_fee_mapping
            WHERE platform_code = 'ks' AND is_active
            GROUP BY platform_code, source_document_type, secondary_category_name
            HAVING COUNT(*) > 1
        ) duplicated
        """,
    )
    if mapping_duplicates:
        raise RuntimeError(f"快手平台费用存在重复有效映射：{mapping_duplicates}组")

    cursor.execute(
        """
        SELECT
            d.source_document_type,
            d.secondary_category_name,
            COUNT(*) AS detail_count,
            ROUND(SUM(d.directional_expense_amount), 2) AS expense_amount
        FROM dwd.dwd_ks_platform_expense_source_detail d
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
                        AND m.source_business_type = d.source_business_type
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
                        )
                    )
              )
        )
        GROUP BY d.source_document_type, d.secondary_category_name
        ORDER BY d.source_document_type, d.secondary_category_name
        """,
    )
    unmapped_scenes = cursor.fetchall()

    from etl.platform_finance.operating_treatment import validate_projection
    dws_ads_difference = validate_projection(cursor,"ks")[1]

    if dws_ads_difference:
        raise RuntimeError(f"快手费用DWS与ADS双向差异：{dws_ads_difference}组")

    ads_duplicate_keys = scalar(
        cursor,
        """
        SELECT COUNT(*)
        FROM (
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
        ) duplicated
        """,
    )
    unmapped_company_rows = scalar(
        cursor,
        """
        SELECT COUNT(*)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'ks' AND company_code = 'unmapped'
        """,
    )
    if ads_duplicate_keys or unmapped_company_rows:
        raise RuntimeError(
            "快手费用ADS主键或公司映射异常："
            f"duplicate={ads_duplicate_keys}，unmapped={unmapped_company_rows}"
        )

    cursor.execute(
        """
        SELECT
            source_document_type,
            ROUND(SUM(expense_amount), 2),
            SUM(included_detail_count)
        FROM dws.dws_ks_platform_expense_shop_daily_category
        GROUP BY source_document_type
        ORDER BY source_document_type
        """
    )
    source_totals = cursor.fetchall()
    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(stat_date),
            MAX(stat_date),
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'ks'
        """
    )
    ads_rows, date_from, date_to, total_expense = cursor.fetchone()
    cursor.execute(
        """
        SELECT
            primary_category_code,
            MAX(primary_category_name),
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'ks'
        GROUP BY primary_category_code
        ORDER BY primary_category_code
        """
    )
    primary_totals = cursor.fetchall()
    cursor.execute(
        """
        SELECT DISTINCT ON (source_document_type, secondary_category_name)
            source_document_type,
            secondary_category_name,
            source_direction,
            source_amount,
            directional_expense_amount,
            order_no,
            flow_no
        FROM dwd.dwd_ks_platform_expense_source_detail
        WHERE directional_expense_amount <> 0
        ORDER BY
            source_document_type,
            secondary_category_name,
            ABS(directional_expense_amount) DESC,
            source_id
        """
    )
    all_samples = cursor.fetchall()
    if not all_samples:
        raise RuntimeError("快手平台费用公式没有可校验的非零场景")
    sample_scene_count = len(all_samples)
    samples = all_samples[:5]

    validate_comments(cursor)
    return {
        "dwd_rows": dwd_rows,
        "source_totals": source_totals,
        "ads_rows": ads_rows,
        "date_from": date_from,
        "date_to": date_to,
        "total_expense": total_expense,
        "primary_totals": primary_totals,
        "samples": samples,
        "sample_scene_count": sample_scene_count,
        "unmapped_scenes": unmapped_scenes,
        "unmapped_company_rows": unmapped_company_rows,
        "dws_ads_difference": dws_ads_difference,
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
            ROUND(
                COALESCE(
                    SUM(expense_amount)
                        FILTER (WHERE source_document_type = 'settlement'),
                    0
                ),
                2
            ),
            ROUND(
                COALESCE(
                    SUM(expense_amount)
                        FILTER (WHERE source_document_type = 'fund'),
                    0
                ),
                2
            ),
            ROUND(COALESCE(SUM(expense_amount), 0), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'ks'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        """,
        params,
    )
    settlement, fund, total = cursor.fetchone()
    actual_header = {
        "settlement_expense": settlement,
        "fund_expense": fund,
        "total_expense": total,
    }
    expected_header = {
        key: baseline[key]
        for key in actual_header
    }
    if actual_header != expected_header:
        raise RuntimeError(
            "快手平台费用当前来源基准不一致："
            f"actual={actual_header}，expected={expected_header}"
        )

    cursor.execute(
        """
        SELECT
            primary_category_code,
            ROUND(SUM(expense_amount), 2)
        FROM ads.ads_platform_expense_company_shop_daily_category
        WHERE platform_code = 'ks'
          AND shop_code = %s
          AND stat_date BETWEEN %s::date AND %s::date
        GROUP BY primary_category_code
        """,
        params,
    )
    actual_primary = dict(cursor.fetchall())
    if actual_primary != baseline["primary_totals"]:
        raise RuntimeError(
            "快手平台费用当前一级分类基准不一致："
            f"actual={actual_primary}，expected={baseline['primary_totals']}"
        )
    return {"source": actual_header, "primary": actual_primary}


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
        "ODS："
        f"settlement={ods['settlement_rows']}，fund={ods['fund_rows']}；"
        f"DWD={result['dwd_rows']}，ADS={result['ads_rows']}"
    )
    print(
        "快手ADS日期范围与总费用："
        f"{result['date_from']}至{result['date_to']}，"
        f"{result['total_expense']}"
    )
    print(f"DWS按来源汇总：{result['source_totals']}")
    print(f"ADS一级费用分类汇总：{result['primary_totals']}")
    print(
        f"公式抽样：实际{result['sample_scene_count']}个场景，抽样"
        f"{len(result['samples'])}个：{result['samples']}"
    )
    if result["sample_scene_count"] < 5:
        print(
            "警告：快手平台费用公式抽样场景不足5个，已对全部"
            f"{result['sample_scene_count']}个非零场景完成公式校验。"
        )
    if result["unmapped_scenes"]:
        print(
            "警告：发现未映射快手平台费用场景（未自动归类，当前不进入ADS费用）："
            f"{result['unmapped_scenes']}"
        )
    print(
        "公司未匹配与DWS/ADS差异："
        f"{result['unmapped_company_rows']} / {result['dws_ads_difference']}"
    )
    if baseline is not None:
        print(f"快手陌时专卖店2026年6月基准：{baseline}")


if __name__ == "__main__":
    main()
