#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新快手结算收入、支出和结算净额三套独立指标链路。"""

from __future__ import annotations

import argparse
import os
import sys
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
    "dim/437_ks_yinka_shop_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
    "ks/settlement_income/96_dwd_ks_settlement_income_event_detail_postgres.sql",
    "ks/settlement_income/97_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ks/settlement_expense/100_dwd_ks_settlement_expense_event_detail_postgres.sql",
    "ks/settlement_expense/101_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ks/settlement_net/104_dwd_ks_settlement_net_event_detail_postgres.sql",
    "ks/settlement_net/105_dws_ks_settlement_net_shop_daily_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "ks/settlement_income/98_refresh_dwd_ks_settlement_income_event_detail_postgres.sql",
    "ks/settlement_income/99_refresh_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ks/settlement_expense/102_refresh_dwd_ks_settlement_expense_event_detail_postgres.sql",
    "ks/settlement_expense/103_refresh_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ks/settlement_net/106_refresh_dwd_ks_settlement_net_event_detail_postgres.sql",
    "ks/settlement_net/107_refresh_dws_ks_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]

INCOME_COMPONENT_COLUMNS = [
    "订单实付(元)", "政府补贴", "支付营销补贴", "平台补贴", "商家补贴(元)", "达人补贴",
]
EXPENSE_COMPONENT_COLUMNS = [
    "订单退款(元)", "技术服务费(元)", "预售增收技术服务费（元）", "达人佣金(元)",
    "团长佣金(元)", "快赚客佣金(元)", "服务商佣金(元)", "其他收费",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_row_no", "row_hash", "ingest_time",
    "商家ID", "订单号", "商品ID", "实际结算时间", "佣金模式", "结算规则", "资金渠道",
    "合计收入(元)", "合计支出(元)", "实际结算金额(元)", "支付营销回退（元）",
    *INCOME_COMPONENT_COLUMNS, *EXPENSE_COMPONENT_COLUMNS,
}
NEW_TABLES = [
    ("dwd", "dwd_ks_settlement_income_event_detail"),
    ("dws", "dws_ks_settlement_income_shop_daily_type"),
    ("dwd", "dwd_ks_settlement_expense_event_detail"),
    ("dws", "dws_ks_settlement_expense_shop_daily_type"),
    ("dwd", "dwd_ks_settlement_net_event_detail"),
    ("dws", "dws_ks_settlement_net_shop_daily"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新快手结算收入、支出和结算净额指标。")
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
        prepare_settlement_sources(cursor, 'ks')


def amount_expression(column_name: str) -> sql.Composed:
    return sql.SQL("ROUND(COALESCE(NULLIF(NULLIF(BTRIM({}), ''), '-')::numeric, 0), 2)").format(
        sql.Identifier(column_name)
    )


def component_sum_expression(column_names: list[str]) -> sql.Composed:
    return sql.SQL(" + ").join(amount_expression(name) for name in column_names)


def validate_ods(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_ks_settlement_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_ks_settlement_raw")

    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_ks_settlement_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"快手结算ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT id), COUNT(DISTINCT row_hash),
               COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_ks_settlement_raw
        """
    )
    source_rows, unique_source_ids, unique_hashes, unique_orders = cursor.fetchone()
    if source_rows == 0:
        raise RuntimeError("快手结算ODS无数据，停止刷新")
    if source_rows != unique_source_ids or source_rows != unique_hashes:
        raise RuntimeError(
            f"ODS稳定粒度或行哈希重复：rows={source_rows}, ids={unique_source_ids}, hashes={unique_hashes}"
        )

    numeric_columns = sorted(
        set(INCOME_COMPONENT_COLUMNS + EXPENSE_COMPONENT_COLUMNS + [
            "合计收入(元)", "合计支出(元)", "实际结算金额(元)", "支付营销回退（元）",
        ])
    )
    for column_name in numeric_columns:
        identifier = sql.Identifier(column_name)
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) FROM ods.ods_ks_settlement_raw "
                "WHERE NULLIF(NULLIF(BTRIM({c}), ''), '-') IS NOT NULL "
                "AND BTRIM({c}) !~ %s"
            ).format(c=identifier),
            (r"^-?\d+(\.\d+)?$",),
        )
        invalid_count = cursor.fetchone()[0]
        if invalid_count:
            raise RuntimeError(f"字段{column_name}存在无法解析金额：{invalid_count}条")

    settlement_time = sql.Identifier("实际结算时间")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM ods.ods_ks_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NULL OR BTRIM({}) !~ %s"
        ).format(settlement_time, settlement_time),
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    invalid_dates = cursor.fetchone()[0]
    if invalid_dates:
        raise RuntimeError(f"实际结算时间为空或格式非法：{invalid_dates}条")

    income_total = amount_expression("合计收入(元)")
    expense_total = amount_expression("合计支出(元)")
    income_components = component_sum_expression(INCOME_COMPONENT_COLUMNS)
    expense_components = component_sum_expression(EXPENSE_COMPONENT_COLUMNS)
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FILTER (WHERE {income_total} <> ({income_components})), "
            "COUNT(*) FILTER (WHERE {expense_total} <> ({expense_components})) "
            "FROM ods.ods_ks_settlement_raw"
        ).format(
            income_total=income_total, income_components=income_components,
            expense_total=expense_total, expense_components=expense_components,
        )
    )
    income_errors, expense_errors = cursor.fetchone()
    if income_errors or expense_errors:
        raise RuntimeError(
            f"ODS收入或支出组成重算失败：income={income_errors}, expense={expense_errors}"
        )
    return source_rows, unique_orders


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id, COUNT(*) AS source_rows
            FROM ods.ods_ks_settlement_raw GROUP BY batch_id
        )
        SELECT b.batch_id, b.source_rows, COUNT(c.batch_id),
               MAX(c.shop_code), MAX(c.shop_name), MAX(c.shop_mapping_status)
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id = b.batch_id
         AND c.platform_code = 'ks'
         AND c.target_table = 'ods_ks_settlement_raw'
         AND c.shop_mapping_status = 'mapped'
        GROUP BY b.batch_id, b.source_rows
        ORDER BY b.batch_id NULLS FIRST
        """
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"快手结算ODS存在未映射或冲突批次：{invalid}")

    merchant_id = sql.Identifier("商家ID")
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*)
            FROM ods.ods_ks_settlement_raw r
            JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id = r.batch_id
             AND c.platform_code = 'ks'
             AND c.target_table = 'ods_ks_settlement_raw'
             AND c.shop_mapping_status = 'mapped'
            LEFT JOIN dim.dim_platform_shop_company d
              ON d.shop_identity_key = c.shop_identity_key AND d.is_active
             AND CURRENT_DATE >= d.valid_from
             AND (d.valid_to IS NULL OR CURRENT_DATE <= d.valid_to)
            WHERE NULLIF(BTRIM(r.{merchant_id}), '') IS NOT NULL
              AND BTRIM(r.{merchant_id}) IS DISTINCT FROM NULLIF(BTRIM(d.account_id), '')
            """
        ).format(merchant_id=merchant_id)
    )
    conflicts = cursor.fetchone()[0]
    if conflicts:
        raise RuntimeError(f"源商家ID与DIM平台账号ID冲突：{conflicts}条")
    return mappings


def validate_ads_bidirectional(cursor, table_name: str, type_kind: str | None = None) -> int:
    if type_kind == "income":
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date, d.platform_code,
                       COALESCE(m.company_code, 'unmapped') company_code,
                       d.shop_code, d.income_type_code,
                       ROUND(SUM(d.income_amount), 2) amount
                FROM dws.dws_ks_settlement_income_shop_daily_type d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4,5
            ), actual AS (
                SELECT stat_date, platform_code, company_code, shop_code, income_type_code,
                       income_amount amount
                FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='ks'
            )
            SELECT COUNT(*) FROM (
                (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL
                (SELECT * FROM actual EXCEPT SELECT * FROM expected)
            ) x
            """
        )
    elif type_kind == "expense":
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date, d.platform_code,
                       COALESCE(m.company_code, 'unmapped') company_code,
                       d.shop_code, d.expense_type_code,
                       ROUND(SUM(d.expense_amount), 2) amount
                FROM dws.dws_ks_settlement_expense_shop_daily_type d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4,5
            ), actual AS (
                SELECT stat_date, platform_code, company_code, shop_code, expense_type_code,
                       expense_amount amount
                FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='ks'
            )
            SELECT COUNT(*) FROM (
                (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL
                (SELECT * FROM actual EXCEPT SELECT * FROM expected)
            ) x
            """
        )
    else:
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date, d.platform_code,
                       COALESCE(m.company_code, 'unmapped') company_code, d.shop_code,
                       ROUND(SUM(d.income_amount),2) income_amount,
                       ROUND(SUM(d.expense_amount),2) expense_amount,
                       ROUND(SUM(d.income_amount)-SUM(d.expense_amount),2) settlement_net_amount,
                       ROUND(SUM(d.source_settlement_amount),2) source_settlement_amount,
                       ROUND(SUM(d.income_amount)-SUM(d.expense_amount)-SUM(d.source_settlement_amount),2) validation_difference_amount
                FROM dws.dws_ks_settlement_net_shop_daily d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4
            ), actual AS (
                SELECT stat_date, platform_code, company_code, shop_code,
                       income_amount, expense_amount, settlement_net_amount,
                       source_settlement_amount, validation_difference_amount
                FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='ks'
            )
            SELECT COUNT(*) FROM (
                (SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL
                (SELECT * FROM actual EXCEPT SELECT * FROM expected)
            ) x
            """
        )
    return cursor.fetchone()[0]


def validate_pipeline(cursor, source_rows: int) -> dict[str, object]:
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM dwd.dwd_ks_settlement_income_event_detail),
            (SELECT COUNT(*) FROM dwd.dwd_ks_settlement_expense_event_detail),
            (SELECT COUNT(*) FROM dwd.dwd_ks_settlement_net_event_detail),
            (SELECT COUNT(*)-COUNT(DISTINCT source_id) FROM dwd.dwd_ks_settlement_net_event_detail)
        """
    )
    income_dwd_rows, expense_dwd_rows, net_dwd_rows, duplicate_source_ids = cursor.fetchone()
    if (income_dwd_rows, expense_dwd_rows, net_dwd_rows) != (source_rows, source_rows, source_rows):
        raise RuntimeError(
            f"DWD行数不等于ODS：{income_dwd_rows}/{expense_dwd_rows}/{net_dwd_rows}!={source_rows}"
        )
    if duplicate_source_ids:
        raise RuntimeError(f"DWD source_id重复：{duplicate_source_ids}")

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE income_amount <>
                order_paid_amount + government_subsidy_amount + payment_marketing_subsidy_amount +
                platform_subsidy_amount + merchant_subsidy_amount + talent_subsidy_amount)
        FROM dwd.dwd_ks_settlement_income_event_detail
        """
    )
    income_formula_errors = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*) FILTER (WHERE expense_amount <>
            order_refund_amount + technical_service_fee_amount + presale_technical_service_fee_amount +
            talent_commission_amount + leader_commission_amount + earner_commission_amount +
            service_provider_commission_amount + other_fee_amount)
        FROM dwd.dwd_ks_settlement_expense_event_detail
        """
    )
    expense_formula_errors = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE settlement_net_amount <> income_amount-expense_amount),
            COUNT(*) FILTER (WHERE validation_difference_amount <>
                settlement_net_amount-source_settlement_amount),
            COUNT(*) FILTER (WHERE validation_difference_amount <> 0)
        FROM dwd.dwd_ks_settlement_net_event_detail
        """
    )
    net_formula_errors, validation_formula_errors, source_difference_rows = cursor.fetchone()
    if any((income_formula_errors, expense_formula_errors, net_formula_errors, validation_formula_errors)):
        raise RuntimeError(
            "DWD公式校验失败："
            f"income={income_formula_errors}, expense={expense_formula_errors}, "
            f"net={net_formula_errors}, validation={validation_formula_errors}"
        )

    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(income_amount),0),
               COALESCE(SUM(included_event_count),0)
        FROM dws.dws_ks_settlement_income_shop_daily_type
        """
    )
    income_dws_rows, dws_income, nonzero_income_components = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(expense_amount),0),
               COALESCE(SUM(included_event_count),0)
        FROM dws.dws_ks_settlement_expense_shop_daily_type
        """
    )
    expense_dws_rows, dws_expense, nonzero_expense_components = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
               COALESCE(SUM(income_amount),0), COALESCE(SUM(expense_amount),0),
               COALESCE(SUM(settlement_net_amount),0),
               COALESCE(SUM(source_settlement_amount),0),
               COALESCE(SUM(validation_difference_amount),0),
               COALESCE(SUM(included_event_count),0)
        FROM dws.dws_ks_settlement_net_shop_daily
        """
    )
    (net_dws_rows, min_date, max_date, net_income, net_expense, dws_net,
     source_net, validation_difference, included_events) = cursor.fetchone()
    if included_events != source_rows:
        raise RuntimeError(f"DWS纳入事件数{included_events}不等于ODS行数{source_rows}")
    if dws_income != net_income or dws_expense != net_expense or dws_net != dws_income-dws_expense:
        raise RuntimeError(
            f"三套DWS汇总不一致：income={dws_income}/{net_income}, "
            f"expense={dws_expense}/{net_expense}, net={dws_net}"
        )

    cursor.execute(
        """
        SELECT
            (SELECT COALESCE(SUM(income_amount),0) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='ks'),
            (SELECT COALESCE(SUM(expense_amount),0) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='ks'),
            (SELECT COALESCE(SUM(settlement_net_amount),0) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='ks'),
            (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='ks' AND company_code='unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='ks' AND company_code='unmapped'),
            (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='ks' AND company_code='unmapped')
        """
    )
    ads_income, ads_expense, ads_net, unmapped_income, unmapped_expense, unmapped_net = cursor.fetchone()
    if (ads_income, ads_expense, ads_net) != (dws_income, dws_expense, dws_net):
        raise RuntimeError(
            f"DWS/ADS汇总不一致：DWS={dws_income}/{dws_expense}/{dws_net}, "
            f"ADS={ads_income}/{ads_expense}/{ads_net}"
        )

    bidirectional_errors = (
        validate_ads_bidirectional(cursor, "income", "income"),
        validate_ads_bidirectional(cursor, "expense", "expense"),
        validate_ads_bidirectional(cursor, "net"),
    )
    if any(bidirectional_errors):
        raise RuntimeError(f"DWS/ADS双向逐粒度差异：{bidirectional_errors}")

    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM (
                SELECT stat_date,platform_code,company_code,shop_code,income_type_code,COUNT(*)
                FROM ads.ads_settlement_income_company_shop_daily_type GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1
            ) x),
            (SELECT COUNT(*) FROM (
                SELECT stat_date,platform_code,company_code,shop_code,expense_type_code,COUNT(*)
                FROM ads.ads_settlement_expense_company_shop_daily_type GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1
            ) x),
            (SELECT COUNT(*) FROM (
                SELECT stat_date,platform_code,company_code,shop_code,COUNT(*)
                FROM ads.ads_settlement_net_company_shop_daily GROUP BY 1,2,3,4 HAVING COUNT(*)>1
            ) x)
        """
    )
    duplicate_ads_keys = cursor.fetchone()
    if any(duplicate_ads_keys):
        raise RuntimeError(f"ADS主键重复：{duplicate_ads_keys}")

    cursor.execute(
        """
        WITH candidates AS (
            SELECT 'source_difference' sample_group, * FROM dwd.dwd_ks_settlement_net_event_detail
             WHERE validation_difference_amount<>0
            UNION ALL
            SELECT 'refund', n.* FROM dwd.dwd_ks_settlement_net_event_detail n
             JOIN dwd.dwd_ks_settlement_expense_event_detail e USING(source_id)
             WHERE e.order_refund_amount>0
            UNION ALL
            SELECT 'marketing_rollback', n.* FROM dwd.dwd_ks_settlement_net_event_detail n
             JOIN dwd.dwd_ks_settlement_expense_event_detail e USING(source_id)
             WHERE e.payment_marketing_rollback_amount>0
            UNION ALL
            SELECT 'other_fee', n.* FROM dwd.dwd_ks_settlement_net_event_detail n
             JOIN dwd.dwd_ks_settlement_expense_event_detail e USING(source_id)
             WHERE e.other_fee_amount>0
            UNION ALL
            SELECT 'presale_fee', n.* FROM dwd.dwd_ks_settlement_net_event_detail n
             JOIN dwd.dwd_ks_settlement_expense_event_detail e USING(source_id)
             WHERE e.presale_technical_service_fee_amount>0
            UNION ALL
            SELECT 'normal', * FROM dwd.dwd_ks_settlement_net_event_detail
             WHERE validation_difference_amount=0 AND expense_amount>0
        ), ranked AS (
            SELECT *, ROW_NUMBER() OVER(PARTITION BY sample_group ORDER BY source_id) rn FROM candidates
        )
        SELECT sample_group, source_id, order_no, stat_date, income_amount, expense_amount,
               settlement_net_amount, source_settlement_amount, validation_difference_amount
        FROM ranked WHERE rn=1 ORDER BY sample_group
        """
    )
    samples = cursor.fetchall()
    if not samples:
        raise RuntimeError("公式抽样没有可校验的场景")

    cursor.execute(
        """
        SELECT platform_code, SUM(income_amount)
        FROM ads.ads_settlement_income_company_shop_daily_type
        GROUP BY platform_code ORDER BY platform_code
        """
    )
    platform_income_totals = cursor.fetchall()

    return {
        "dwd_rows": (income_dwd_rows, expense_dwd_rows, net_dwd_rows),
        "dws_rows": (income_dws_rows, expense_dws_rows, net_dws_rows),
        "date_range": (min_date, max_date),
        "income": dws_income, "expense": dws_expense, "net": dws_net,
        "source_net": source_net, "validation_difference": validation_difference,
        "source_difference_rows": source_difference_rows,
        "included_events": included_events,
        "nonzero_components": (nonzero_income_components, nonzero_expense_components),
        "unmapped": (unmapped_income, unmapped_expense, unmapped_net),
        "bidirectional_errors": bidirectional_errors,
        "duplicate_ads_keys": duplicate_ads_keys,
        "samples": samples,
        "sample_scene_count": len(samples),
        "platform_income_totals": platform_income_totals,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
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
            JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
              AND a.attnum>0 AND NOT a.attisdropped
              AND col_description(c.oid,a.attnum) IS NULL
            ORDER BY a.attnum
            """,
            (schema_name, table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{r[0]}" for r in cursor.fetchall())
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def run_pipeline(args: argparse.Namespace) -> None:
    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )
    try:
        with conn.cursor() as cursor:
            execute_files(cursor, PREPARE_SQL_FILES)
            source_rows, unique_orders = validate_ods(cursor)
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
    print(f"ODS来源行数/唯一订单数：{source_rows}/{unique_orders}")
    print("批次店铺映射：")
    for batch_id, rows, _, shop_code, shop_name, status in mappings:
        print(f"  批次{batch_id}：{rows}行 -> {shop_code} / {shop_name} / {status}")
    print(f"DWD行数（收入/支出/净额）：{result['dwd_rows']}")
    print(f"DWS行数（收入类型/支出类型/净额日）：{result['dws_rows']}")
    print(f"DWS纳入结算事件数：{result['included_events']}")
    print(f"非零收入/支出组成事件数：{result['nonzero_components']}")
    print(f"ADS快手日期范围：{result['date_range'][0]} 至 {result['date_range'][1]}")
    print(f"快手收入金额：{result['income']:.2f}")
    print(f"快手支出金额：{result['expense']:.2f}")
    print(f"快手计算结算净额：{result['net']:.2f}")
    print(f"快手源实际结算金额：{result['source_net']:.2f}")
    print(f"快手净额核验差额：{result['validation_difference']:.2f}")
    print(f"源结算金额差异明细数：{result['source_difference_rows']}")
    print(f"ADS未匹配公司行数（收入/支出/净额）：{result['unmapped']}")
    print(f"DWS/ADS双向差异（收入/支出/净额）：{result['bidirectional_errors']}")
    print(f"ADS重复主键组（收入/支出/净额）：{result['duplicate_ads_keys']}")
    print(f"跨平台收入合计：{result['platform_income_totals']}")
    print(
        f"公式抽样：实际{result['sample_scene_count']}个场景，抽样"
        f"{len(result['samples'])}个（场景,source_id,订单号,日期,收入,支出,"
        "计算净额,源结算金额,差额）："
    )
    for sample in result["samples"]:
        print(f"  {sample}")
    if result["sample_scene_count"] < 5:
        print(
            "警告：公式抽样场景不足5类，已对全部"
            f"{result['sample_scene_count']}个实际场景完成公式校验。"
        )


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
