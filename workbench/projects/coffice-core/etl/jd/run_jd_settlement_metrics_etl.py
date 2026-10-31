#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新京东结算收入、支出和结算净额三套独立指标链路。"""

from __future__ import annotations

import argparse
import os
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
    "jd/settlement_income/84_dwd_jd_settlement_income_document_detail_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "jd/settlement_expense/88_dwd_jd_settlement_expense_document_detail_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "jd/settlement_net/92_dwd_jd_settlement_net_document_detail_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "jd/settlement_income/86_refresh_dwd_jd_settlement_income_document_detail_postgres.sql",
    "jd/settlement_income/87_refresh_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "jd/settlement_expense/90_refresh_dwd_jd_settlement_expense_document_detail_postgres.sql",
    "jd/settlement_expense/91_refresh_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "jd/settlement_net/94_refresh_dwd_jd_settlement_net_document_detail_postgres.sql",
    "jd/settlement_net/95_refresh_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]

REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
    "订单编号", "单据编号", "单据类型", "商户订单号", "费用项",
    "金额", "币种", "商家应收/应付", "店铺号", "收支方向", "账单日期",
}

NEW_TABLES = [
    ("dwd", "dwd_jd_settlement_income_document_detail"),
    ("dws", "dws_jd_settlement_income_shop_daily_type"),
    ("dwd", "dwd_jd_settlement_expense_document_detail"),
    ("dws", "dws_jd_settlement_expense_shop_daily_type"),
    ("dwd", "dwd_jd_settlement_net_document_detail"),
    ("dws", "dws_jd_settlement_net_shop_daily"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新京东结算收入、支出和结算净额指标。")
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
        cursor.execute((SQL_DIR / 'common/468_ingest_source_day_selection_postgres.sql').read_text(encoding='utf-8'))


def clean_document_expression() -> sql.Composed:
    return sql.SQL("NULLIF(REPLACE(REPLACE(BTRIM({}), '=\"', ''), '\"', ''), '')").format(
        sql.Identifier("单据编号")
    )


def validate_ods(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_jd_settlement_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_jd_settlement_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_jd_settlement_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"京东结算ODS缺少必需字段：{', '.join(missing_columns)}")

    document_expr = clean_document_expression()
    cursor.execute(
        sql.SQL("SELECT COUNT(*), COUNT(DISTINCT {}) FROM common.v_selected_jd_settlement_raw").format(
            document_expr
        )
    )
    source_rows, unique_documents = cursor.fetchone()
    if source_rows == 0:
        raise RuntimeError("京东结算ODS无数据，停止刷新")
    if unique_documents == 0:
        raise RuntimeError("京东结算ODS无有效单据编号")

    amount = sql.Identifier("金额")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM common.v_selected_jd_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NULL "
            "OR BTRIM({}) !~ %s"
        ).format(amount, amount),
        (r"^-?\d+(\.\d+)?$",),
    )
    invalid_amounts = cursor.fetchone()[0]
    if invalid_amounts:
        raise RuntimeError(f"金额为空或解析失败：{invalid_amounts}条")

    bill_date = sql.Identifier("账单日期")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM common.v_selected_jd_settlement_raw "
            "WHERE NULLIF(BTRIM({}), '') IS NULL "
            "OR (BTRIM({}) !~ %s AND BTRIM({}) !~ %s)"
        ).format(bill_date, bill_date, bill_date),
        (r"^[0-9]{8}$", r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"),
    )
    invalid_dates = cursor.fetchone()[0]
    if invalid_dates:
        raise RuntimeError(f"账单日期为空或格式非法：{invalid_dates}条")

    direction = sql.Identifier("收支方向")
    receivable = sql.Identifier("商家应收/应付")
    currency = sql.Identifier("币种")
    cursor.execute(
        sql.SQL(
            """
            SELECT
                COUNT(*) FILTER (WHERE BTRIM({direction}) NOT IN (%s, %s)),
                COUNT(*) FILTER (WHERE
                    (BTRIM({direction}) = %s AND BTRIM({amount})::numeric <= 0)
                    OR (BTRIM({direction}) = %s AND BTRIM({amount})::numeric >= 0)
                ),
                COUNT(*) FILTER (WHERE
                    (BTRIM({direction}) = %s AND BTRIM({receivable}) <> %s)
                    OR (BTRIM({direction}) = %s AND BTRIM({receivable}) <> %s)
                ),
                COUNT(*) FILTER (WHERE BTRIM({currency}) <> 'CNY')
            FROM common.v_selected_jd_settlement_raw
            """
        ).format(direction=direction, amount=amount, receivable=receivable, currency=currency),
        ("收入", "支出", "收入", "支出", "收入", "应收", "支出", "应付"),
    )
    invalid_directions, sign_conflicts, receivable_conflicts, non_cny_rows = cursor.fetchone()
    if any((invalid_directions, sign_conflicts, receivable_conflicts, non_cny_rows)):
        raise RuntimeError(
            "京东结算方向、符号、应收应付或币种校验失败："
            f"direction={invalid_directions}, sign={sign_conflicts}, "
            f"receivable={receivable_conflicts}, non_cny={non_cny_rows}"
        )
    return source_rows, unique_documents


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id, COUNT(*) AS source_rows
            FROM common.v_selected_jd_settlement_raw
            GROUP BY batch_id
        )
        SELECT b.batch_id, b.source_rows, COUNT(c.batch_id),
               MAX(c.shop_code), MAX(c.shop_name), MAX(c.shop_mapping_status)
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'jd'
         AND c.target_table = 'ods_jd_settlement_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id, b.source_rows
        ORDER BY b.batch_id NULLS FIRST
        """
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"京东结算ODS存在未映射或冲突批次：{invalid}")

    source_shop = sql.Identifier("店铺号")
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*)
            FROM common.v_selected_jd_settlement_raw r
            JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id = r.batch_id
             AND c.platform_code = 'jd'
             AND c.target_table = 'ods_jd_settlement_raw'
             AND c.shop_mapping_status = 'mapped'
            WHERE NULLIF(BTRIM(r.{source_shop}), '') IS NOT NULL
              AND BTRIM(r.{source_shop}) <> c.shop_code
            """
        ).format(source_shop=source_shop)
    )
    shop_conflicts = cursor.fetchone()[0]
    if shop_conflicts:
        raise RuntimeError(f"源店铺号与批次标准店铺冲突：{shop_conflicts}条")
    return mappings


def validate_pipeline(cursor, unique_documents: int) -> dict[str, object]:
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM dwd.dwd_jd_settlement_income_document_detail),
            (SELECT COUNT(*) FROM dwd.dwd_jd_settlement_expense_document_detail),
            (SELECT COUNT(*) FROM dwd.dwd_jd_settlement_net_document_detail),
            (SELECT COUNT(*) - COUNT(DISTINCT document_no) FROM dwd.dwd_jd_settlement_net_document_detail)
        """
    )
    income_dwd_rows, expense_dwd_rows, net_dwd_rows, duplicate_documents = cursor.fetchone()
    if (income_dwd_rows, expense_dwd_rows, net_dwd_rows) != (
        unique_documents, unique_documents, unique_documents
    ) or duplicate_documents:
        raise RuntimeError(
            f"DWD粒度校验失败：唯一单据{unique_documents}，"
            f"收入/支出/净额={income_dwd_rows}/{expense_dwd_rows}/{net_dwd_rows}，"
            f"重复={duplicate_documents}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE validation_difference_amount <> 0),
            COUNT(*) FILTER (WHERE
                (income_expense_direction = '收入' AND income_amount <> source_amount)
                OR (income_expense_direction = '收入' AND expense_amount <> 0)
                OR (income_expense_direction = '支出' AND income_amount <> 0)
                OR (income_expense_direction = '支出' AND expense_amount <> -source_amount)
            )
        FROM dwd.dwd_jd_settlement_net_document_detail
        """
    )
    validation_errors, direction_formula_errors = cursor.fetchone()
    if validation_errors or direction_formula_errors:
        raise RuntimeError(
            f"DWD公式校验失败：净额差异{validation_errors}，"
            f"方向公式差异{direction_formula_errors}"
        )

    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(included_event_count), 0),
               COALESCE(SUM(income_amount), 0)
        FROM dws.dws_jd_settlement_income_shop_daily_type
        """
    )
    income_dws_rows, included_income_events, dws_income = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(included_event_count), 0),
               COALESCE(SUM(expense_amount), 0)
        FROM dws.dws_jd_settlement_expense_shop_daily_type
        """
    )
    expense_dws_rows, included_expense_events, dws_expense = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
               COALESCE(SUM(income_amount), 0), COALESCE(SUM(expense_amount), 0),
               COALESCE(SUM(settlement_net_amount), 0),
               COALESCE(SUM(source_settlement_amount), 0),
               COALESCE(SUM(validation_difference_amount), 0),
               COALESCE(SUM(included_event_count), 0)
        FROM dws.dws_jd_settlement_net_shop_daily
        """
    )
    (net_dws_rows, min_date, max_date, dws_net_income, dws_net_expense,
     dws_net, dws_source_net, dws_difference, included_net_events) = cursor.fetchone()

    if included_income_events + included_expense_events != unique_documents:
        raise RuntimeError(
            f"收入与支出方向单据数不等于唯一单据数："
            f"{included_income_events}+{included_expense_events}!={unique_documents}"
        )
    if included_net_events != unique_documents:
        raise RuntimeError(f"净额DWS单据数{included_net_events}与{unique_documents}不一致")
    if dws_income != dws_net_income or dws_expense != dws_net_expense:
        raise RuntimeError(
            f"三套DWS组成不一致：收入{dws_income}/{dws_net_income}，"
            f"支出{dws_expense}/{dws_net_expense}"
        )
    if dws_net != dws_income - dws_expense or dws_net != dws_source_net or dws_difference != 0:
        raise RuntimeError(
            f"京东结算净额核验失败：net={dws_net}，"
            f"income-expense={dws_income-dws_expense}，source={dws_source_net}，"
            f"difference={dws_difference}"
        )

    cursor.execute(
        """
        SELECT
            (SELECT COALESCE(SUM(income_amount), 0)
             FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code = 'jd'),
            (SELECT COALESCE(SUM(expense_amount), 0)
             FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code = 'jd'),
            (SELECT COALESCE(SUM(settlement_net_amount), 0)
             FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code = 'jd'),
            (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type
             WHERE platform_code = 'jd' AND company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type
             WHERE platform_code = 'jd' AND company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily
             WHERE platform_code = 'jd' AND company_code = 'unmapped')
        """
    )
    ads_income, ads_expense, ads_net, unmapped_income, unmapped_expense, unmapped_net = cursor.fetchone()
    if (ads_income, ads_expense, ads_net) != (dws_income, dws_expense, dws_net):
        raise RuntimeError(
            f"DWS/ADS双向汇总不一致：DWS={dws_income}/{dws_expense}/{dws_net}，"
            f"ADS={ads_income}/{ads_expense}/{ads_net}"
        )

    cursor.execute(
        """
        WITH categorized AS (
            SELECT *,
                CASE
                    WHEN document_type = '订单' AND income_expense_direction = '收入' THEN 1
                    WHEN document_type = '订单' AND income_expense_direction = '支出' THEN 2
                    WHEN document_type = '非销售单' THEN 3
                    WHEN document_type = '取消退款单' AND income_expense_direction = '收入' THEN 4
                    WHEN document_type = '取消退款单' AND income_expense_direction = '支出' THEN 5
                    WHEN document_type = '售后服务单' THEN 6
                END AS sample_group
            FROM dwd.dwd_jd_settlement_net_document_detail
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY sample_group ORDER BY source_id) AS rn
            FROM categorized
            WHERE sample_group IS NOT NULL
        )
        SELECT document_no, document_type, fee_item_name,
               income_expense_direction, source_amount, income_amount,
               expense_amount, settlement_net_amount, validation_difference_amount
        FROM ranked
        WHERE rn = 1
        ORDER BY sample_group
        """
    )
    samples = cursor.fetchall()

    cursor.execute(
        """
        SELECT platform_code, SUM(income_amount)
        FROM ads.ads_settlement_income_company_shop_daily_type
        GROUP BY platform_code ORDER BY platform_code
        """
    )
    platform_income_totals = cursor.fetchall()

    return {
        "income_dwd_rows": income_dwd_rows,
        "expense_dwd_rows": expense_dwd_rows,
        "net_dwd_rows": net_dwd_rows,
        "income_dws_rows": income_dws_rows,
        "expense_dws_rows": expense_dws_rows,
        "net_dws_rows": net_dws_rows,
        "included_income_events": included_income_events,
        "included_expense_events": included_expense_events,
        "min_date": min_date,
        "max_date": max_date,
        "income": dws_income,
        "expense": dws_expense,
        "net": dws_net,
        "source_net": dws_source_net,
        "difference": dws_difference,
        "unmapped": (unmapped_income, unmapped_expense, unmapped_net),
        "samples": samples,
        "platform_income_totals": platform_income_totals,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
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
            source_rows, unique_documents = validate_ods(cursor)
            mappings = validate_batch_shop_mapping(cursor)
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_pipeline(cursor, unique_documents)
            validate_comments(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS来源行数/唯一单据数：{source_rows}/{unique_documents}")
    print("批次店铺映射：")
    for batch_id, rows, _, shop_code, shop_name, status in mappings:
        print(f"  批次{batch_id}：{rows}行 -> {shop_code} / {shop_name} / {status}")
    print(
        "DWD行数（收入/支出/净额）："
        f"{result['income_dwd_rows']}/{result['expense_dwd_rows']}/{result['net_dwd_rows']}"
    )
    print(
        "DWS行数（收入类型/支出类型/净额日）："
        f"{result['income_dws_rows']}/{result['expense_dws_rows']}/{result['net_dws_rows']}"
    )
    print(
        "DWS纳入收入/支出单据数："
        f"{result['included_income_events']}/{result['included_expense_events']}"
    )
    print(f"ADS京东日期范围：{result['min_date']} 至 {result['max_date']}")
    print(f"京东收入金额：{result['income']:.2f}")
    print(f"京东支出金额：{result['expense']:.2f}")
    print(f"京东计算结算净额：{result['net']:.2f}")
    print(f"京东源带符号金额合计：{result['source_net']:.2f}")
    print(f"京东净额核验差额：{result['difference']:.2f}")
    print(
        "ADS京东未匹配公司行数（收入/支出/净额）："
        f"{result['unmapped'][0]}/{result['unmapped'][1]}/{result['unmapped'][2]}"
    )
    print(f"跨平台收入合计：{result['platform_income_totals']}")
    print("DWD公式抽样（单据号,单据类型,费用项,方向,源金额,收入,支出,净额,差额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
