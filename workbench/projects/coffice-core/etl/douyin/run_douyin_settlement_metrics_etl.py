#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新抖音结算收入、支出和结算净额三套独立指标链路。"""

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
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from etl.common.settlement_sources import prepare_settlement_sources


PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
    "douyin/settlement_income/66_dwd_douyin_settlement_income_event_detail_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/72_dwd_douyin_settlement_expense_event_detail_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "douyin/settlement_net/78_dwd_douyin_settlement_net_event_detail_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "douyin/settlement_income/69_refresh_dwd_douyin_settlement_income_event_detail_postgres.sql",
    "douyin/settlement_income/70_refresh_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/75_refresh_dwd_douyin_settlement_expense_event_detail_postgres.sql",
    "douyin/settlement_expense/76_refresh_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "douyin/settlement_net/81_refresh_dwd_douyin_settlement_net_event_detail_postgres.sql",
    "douyin/settlement_net/82_refresh_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]

REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
    "结算时间", "订单号", "子订单号", "结算金额", "结算单类型",
    "有结算前退款", "业务类型", "订单类型", "商户主体名称",
    "用户实付", "平台补贴", "其他平台补贴", "政府补贴平台垫资",
    "达人补贴", "抖音支付补贴", "抖音月付营销补贴", "银行补贴",
    "以旧换新抵扣", "平台补贴运费", "收入合计", "平台服务费",
    "达人佣金", "服务商佣金", "渠道分成", "招商服务费", "站外推广费",
    "其他分成", "支出合计",
}

AMOUNT_COLUMNS = [
    "结算金额", "用户实付", "平台补贴", "其他平台补贴",
    "政府补贴平台垫资", "达人补贴", "抖音支付补贴",
    "抖音月付营销补贴", "银行补贴", "以旧换新抵扣",
    "平台补贴运费", "收入合计", "平台服务费", "达人佣金",
    "服务商佣金", "渠道分成", "招商服务费", "站外推广费",
    "其他分成", "支出合计",
]

NEW_TABLES = [
    ("dwd", "dwd_douyin_settlement_income_event_detail"),
    ("dws", "dws_douyin_settlement_income_shop_daily_type"),
    ("ads", "ads_settlement_income_company_shop_daily_type"),
    ("dwd", "dwd_douyin_settlement_expense_event_detail"),
    ("dws", "dws_douyin_settlement_expense_shop_daily_type"),
    ("ads", "ads_settlement_expense_company_shop_daily_type"),
    ("dwd", "dwd_douyin_settlement_net_event_detail"),
    ("dws", "dws_douyin_settlement_net_shop_daily"),
    ("ads", "ads_settlement_net_company_shop_daily"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新抖音结算收入、支出和结算净额指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
    if file_names == PREPARE_SQL_FILES:
        prepare_settlement_sources(cursor, 'douyin')


def validate_ods(cursor) -> int:
    cursor.execute("SELECT to_regclass('ods.ods_douyin_settlement_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_douyin_settlement_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_douyin_settlement_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"抖音结算ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute("SELECT COUNT(*) FROM common.v_current_douyin_settlement_raw")
    source_rows = cursor.fetchone()[0]
    if source_rows == 0:
        raise RuntimeError("抖音结算ODS无数据，停止刷新")

    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM ods.ods_douyin_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NULL "
            "OR BTRIM({}) !~ %s"
        ).format(sql.Identifier("结算时间"), sql.Identifier("结算时间")),
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    invalid_dates = cursor.fetchone()[0]
    if invalid_dates:
        raise RuntimeError(f"结算时间为空或格式非法：{invalid_dates}条")

    invalid_amounts: dict[str, int] = {}
    for column_name in AMOUNT_COLUMNS:
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) FROM ods.ods_douyin_settlement_raw "
                "WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NOT NULL "
                "AND BTRIM({}) !~ %s"
            ).format(sql.Identifier(column_name), sql.Identifier(column_name)),
            (r"^-?\d+(\.\d+)?$",),
        )
        invalid_count = cursor.fetchone()[0]
        if invalid_count:
            invalid_amounts[column_name] = invalid_count
    if invalid_amounts:
        details = "，".join(f"{name}={count}" for name, count in invalid_amounts.items())
        raise RuntimeError(f"金额字段存在解析失败：{details}")
    return source_rows


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id, COUNT(*) AS source_rows
            FROM ods.ods_douyin_settlement_raw
            GROUP BY batch_id
        )
        SELECT
            b.batch_id,
            b.source_rows,
            COUNT(c.batch_id) AS mapped_context_count,
            MAX(c.shop_code) AS shop_code,
            MAX(c.shop_name) AS shop_name,
            MAX(c.shop_mapping_status) AS mapping_status
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
            ON c.batch_id = b.batch_id
           AND c.platform_code = 'douyin'
           AND c.target_table = 'ods_douyin_settlement_raw'
           AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id, b.source_rows
        ORDER BY b.batch_id NULLS FIRST
        """
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"抖音结算ODS存在未映射或冲突批次：{invalid}")
    return mappings


def scalar(cursor, statement: str) -> Decimal | int:
    cursor.execute(statement)
    return cursor.fetchone()[0]


def validate_pipeline(cursor, source_rows: int) -> dict[str, object]:
    income_dwd_rows = scalar(cursor, "SELECT COUNT(*) FROM dwd.dwd_douyin_settlement_income_event_detail")
    expense_dwd_rows = scalar(cursor, "SELECT COUNT(*) FROM dwd.dwd_douyin_settlement_expense_event_detail")
    net_dwd_rows = scalar(cursor, "SELECT COUNT(*) FROM dwd.dwd_douyin_settlement_net_event_detail")
    if (income_dwd_rows, expense_dwd_rows, net_dwd_rows) != (source_rows, source_rows, source_rows):
        raise RuntimeError(
            f"ODS/DWD行数不一致：ODS={source_rows}，income={income_dwd_rows}，"
            f"expense={expense_dwd_rows}，net={net_dwd_rows}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE ROUND(
                user_payment_amount + platform_subsidy_amount + other_platform_subsidy_amount
                + government_platform_advance_amount + creator_subsidy_amount
                + douyin_pay_subsidy_amount + douyin_monthly_pay_subsidy_amount
                + bank_subsidy_amount + trade_in_deduction_amount
                + platform_shipping_subsidy_amount - income_amount, 2
            ) <> 0),
            COUNT(*) - COUNT(DISTINCT source_id)
        FROM dwd.dwd_douyin_settlement_income_event_detail
        """
    )
    income_formula_errors, income_duplicates = cursor.fetchone()
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE ROUND(
                platform_service_fee_amount + creator_commission_amount
                + service_provider_commission_amount + channel_share_amount
                + merchant_recruitment_service_fee_amount + offsite_promotion_fee_amount
                + other_share_amount - expense_amount, 2
            ) <> 0),
            COUNT(*) - COUNT(DISTINCT source_id)
        FROM dwd.dwd_douyin_settlement_expense_event_detail
        """
    )
    expense_formula_errors, expense_duplicates = cursor.fetchone()
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE validation_difference_amount <> 0),
            COUNT(*) - COUNT(DISTINCT source_id)
        FROM dwd.dwd_douyin_settlement_net_event_detail
        """
    )
    net_formula_errors, net_duplicates = cursor.fetchone()
    if any((income_formula_errors, expense_formula_errors, net_formula_errors,
            income_duplicates, expense_duplicates, net_duplicates)):
        raise RuntimeError(
            "DWD公式或唯一性校验失败："
            f"income_formula={income_formula_errors}, expense_formula={expense_formula_errors}, "
            f"net_formula={net_formula_errors}, duplicates="
            f"{income_duplicates}/{expense_duplicates}/{net_duplicates}"
        )

    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
               COALESCE(SUM(income_amount), 0)
        FROM ads.ads_settlement_income_company_shop_daily_type
        WHERE platform_code = 'douyin'
        """
    )
    income_ads_rows, min_date, max_date, total_income = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(expense_amount), 0)
        FROM ads.ads_settlement_expense_company_shop_daily_type
        WHERE platform_code = 'douyin'
        """
    )
    expense_ads_rows, total_expense = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(income_amount), 0),
               COALESCE(SUM(expense_amount), 0),
               COALESCE(SUM(settlement_net_amount), 0),
               COALESCE(SUM(source_settlement_amount), 0),
               COALESCE(SUM(validation_difference_amount), 0),
               COALESCE(SUM(included_event_count), 0)
        FROM ads.ads_settlement_net_company_shop_daily
        WHERE platform_code = 'douyin'
        """
    )
    (net_ads_rows, net_income, net_expense, total_net, source_settlement,
     validation_difference, included_events) = cursor.fetchone()

    if total_income != net_income or total_expense != net_expense:
        raise RuntimeError(
            f"三套ADS组成金额不一致：收入{total_income}/{net_income}，"
            f"支出{total_expense}/{net_expense}"
        )
    if total_net != total_income - total_expense or total_net != source_settlement:
        raise RuntimeError(
            f"结算净额校验失败：net={total_net}，income-expense="
            f"{total_income - total_expense}，source={source_settlement}"
        )
    if validation_difference != 0:
        raise RuntimeError(f"结算净额与源结算金额差额不为0：{validation_difference}")
    if included_events != source_rows:
        raise RuntimeError(f"ADS结算事件数{included_events}与ODS行数{source_rows}不一致")

    cursor.execute(
        """
        SELECT
            (SELECT COALESCE(SUM(income_amount), 0) FROM dws.dws_douyin_settlement_income_shop_daily_type)
              - (SELECT COALESCE(SUM(income_amount), 0) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code = 'douyin'),
            (SELECT COALESCE(SUM(expense_amount), 0) FROM dws.dws_douyin_settlement_expense_shop_daily_type)
              - (SELECT COALESCE(SUM(expense_amount), 0) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code = 'douyin'),
            (SELECT COALESCE(SUM(settlement_net_amount), 0) FROM dws.dws_douyin_settlement_net_shop_daily)
              - (SELECT COALESCE(SUM(settlement_net_amount), 0) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code = 'douyin')
        """
    )
    dws_ads_differences = cursor.fetchone()
    if any(value != 0 for value in dws_ads_differences):
        raise RuntimeError(f"DWS与ADS汇总差额不为0：{dws_ads_differences}")

    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code = 'douyin' AND company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code = 'douyin' AND company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code = 'douyin' AND company_code = 'unmapped')
        """
    )
    unmapped_counts = cursor.fetchone()

    cursor.execute(
        """
        SELECT source_id, settlement_type, income_amount, expense_amount,
               settlement_net_amount, source_settlement_amount,
               validation_difference_amount
        FROM dwd.dwd_douyin_settlement_net_event_detail
        ORDER BY
            CASE
                WHEN settlement_type LIKE '%退款%' THEN 0
                WHEN expense_amount < 0 THEN 1
                WHEN income_amount = 0 OR expense_amount = 0 THEN 2
                ELSE 3
            END,
            source_id
        LIMIT 5
        """
    )
    samples = cursor.fetchall()

    return {
        "income_dwd_rows": income_dwd_rows,
        "expense_dwd_rows": expense_dwd_rows,
        "net_dwd_rows": net_dwd_rows,
        "income_ads_rows": income_ads_rows,
        "expense_ads_rows": expense_ads_rows,
        "net_ads_rows": net_ads_rows,
        "min_date": min_date,
        "max_date": max_date,
        "total_income": total_income,
        "total_expense": total_expense,
        "total_net": total_net,
        "source_settlement": source_settlement,
        "validation_difference": validation_difference,
        "unmapped_counts": unmapped_counts,
        "samples": samples,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
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
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
              AND col_description(c.oid, a.attnum) IS NULL
            ORDER BY a.attnum
            """,
            (schema_name, table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{row[0]}" for row in cursor.fetchall())
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def run_pipeline(args: argparse.Namespace) -> None:
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
            source_rows = validate_ods(cursor)
            mappings = validate_batch_shop_mapping(cursor)
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_pipeline(cursor, source_rows)
            validate_comments(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS来源行数：{source_rows}")
    print("批次店铺映射：")
    for batch_id, rows, _, shop_code, shop_name, status in mappings:
        print(f"  批次{batch_id}：{rows}行 -> {shop_code} / {shop_name} / {status}")
    print(
        "DWD行数："
        f"收入{result['income_dwd_rows']}，支出{result['expense_dwd_rows']}，"
        f"净额{result['net_dwd_rows']}"
    )
    print(
        "ADS行数："
        f"收入{result['income_ads_rows']}，支出{result['expense_ads_rows']}，"
        f"净额{result['net_ads_rows']}"
    )
    print(f"ADS日期范围：{result['min_date']} 至 {result['max_date']}")
    print(f"收入金额：{result['total_income']:.2f}")
    print(f"支出金额：{result['total_expense']:.2f}")
    print(f"计算结算净额：{result['total_net']:.2f}")
    print(f"源结算金额：{result['source_settlement']:.2f}")
    print(f"净额核验差额：{result['validation_difference']:.2f}")
    print(
        "ADS未匹配公司行数（收入/支出/净额）："
        f"{result['unmapped_counts'][0]}/{result['unmapped_counts'][1]}/{result['unmapped_counts'][2]}"
    )
    print("DWD公式抽样（source_id, 结算类型, 收入, 支出, 净额, 源结算金额, 差额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
