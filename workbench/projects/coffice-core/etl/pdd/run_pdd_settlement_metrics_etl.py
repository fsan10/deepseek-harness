#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新拼多多结算收入、支出和结算净额三套独立指标链路。"""

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

from etl.common.report_sources import prepare_report_sources
from etl.platform_finance.run_settlement_shared_ads_etl import validate_monthly_result


PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
    "pdd/settlement_income/108_dwd_pdd_settlement_income_event_detail_postgres.sql",
    "pdd/settlement_income/109_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ks/settlement_income/97_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "pdd/settlement_expense/112_dwd_pdd_settlement_expense_event_detail_postgres.sql",
    "pdd/settlement_expense/113_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ks/settlement_expense/101_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "pdd/settlement_net/116_dwd_pdd_settlement_net_event_detail_postgres.sql",
    "pdd/settlement_net/117_dws_pdd_settlement_net_shop_daily_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ks/settlement_net/105_dws_ks_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
    "ads/settlement_net/416_ads_settlement_net_company_shop_monthly_postgres.sql",
    "ads/settlement_net/418_view_settlement_net_company_shop_monthly_metric_postgres.sql",
]
REFRESH_SQL_FILES = [
    "pdd/settlement_income/110_refresh_dwd_pdd_settlement_income_event_detail_postgres.sql",
    "pdd/settlement_income/111_refresh_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "pdd/settlement_expense/114_refresh_dwd_pdd_settlement_expense_event_detail_postgres.sql",
    "pdd/settlement_expense/115_refresh_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "pdd/settlement_net/118_refresh_dwd_pdd_settlement_net_event_detail_postgres.sql",
    "pdd/settlement_net/119_refresh_dws_pdd_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
    "ads/settlement_net/417_refresh_ads_settlement_net_company_shop_monthly_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_row_no", "row_hash", "ingest_time",
    "商户订单号", "发生时间", "收入金额（+元）", "支出金额（-元）",
    "账务类型", "备注", "业务描述",
}
NEW_TABLES = [
    ("dwd", "dwd_pdd_settlement_income_event_detail"),
    ("dws", "dws_pdd_settlement_income_shop_daily_type"),
    ("dwd", "dwd_pdd_settlement_expense_event_detail"),
    ("dws", "dws_pdd_settlement_expense_shop_daily_type"),
    ("dwd", "dwd_pdd_settlement_net_event_detail"),
    ("dws", "dws_pdd_settlement_net_shop_daily"),
    ("ads", "ads_settlement_net_company_shop_daily"),
    ("ads", "ads_settlement_net_company_shop_monthly"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新拼多多结算收入、支出和结算净额指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    prepare_report_sources(cursor, (), pdd_settlement=True)
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def amount_expression(column_name: str) -> sql.Composed:
    return sql.SQL("ROUND(COALESCE(NULLIF(NULLIF(BTRIM({}), ''), '-')::numeric, 0), 2)").format(
        sql.Identifier(column_name)
    )


def validate_ods(cursor) -> tuple[int, int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_pdd_settlement_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_pdd_settlement_raw")
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='ods' AND table_name='ods_pdd_settlement_raw'"""
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"拼多多结算ODS缺少必需字段：{', '.join(missing_columns)}")

    order_no = sql.Identifier("商户订单号")
    occurred_at = sql.Identifier("发生时间")
    account_type = sql.Identifier("账务类型")
    income = sql.Identifier("收入金额（+元）")
    expense = sql.Identifier("支出金额（-元）")
    business_description = sql.Identifier("业务描述")
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*), COUNT(DISTINCT id), COUNT(DISTINCT row_hash),
                   COUNT(DISTINCT NULLIF(BTRIM({order_no}),'')),
                   COUNT(DISTINCT CONCAT_WS('|',{order_no},{occurred_at},{account_type},
                       {income},{expense},{business_description}))
            FROM common.v_current_pdd_settlement_raw
            """
        ).format(
            order_no=order_no, occurred_at=occurred_at, account_type=account_type,
            income=income, expense=expense, business_description=business_description,
        )
    )
    source_rows, unique_ids, unique_hashes, unique_orders, unique_business_events = cursor.fetchone()
    if source_rows == 0:
        raise RuntimeError("拼多多结算ODS无数据，停止刷新")
    if source_rows != unique_ids or source_rows != unique_hashes:
        raise RuntimeError(
            "ODS源行粒度重复："
            f"rows={source_rows}, ids={unique_ids}, hashes={unique_hashes}"
        )
    if source_rows != unique_business_events:
        print(
            "警告：ODS业务字段组合键存在重复，但源行均为独立流水，"
            "按source_id/source_row_no保留并累计："
            f"rows={source_rows}, ids={unique_ids}, hashes={unique_hashes}, "
            f"business_keys={unique_business_events}"
        )

    for column_name in ("收入金额（+元）", "支出金额（-元）"):
        identifier = sql.Identifier(column_name)
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) FROM common.v_current_pdd_settlement_raw "
                "WHERE NULLIF(NULLIF(BTRIM({c}),''),'-') IS NULL "
                "OR BTRIM({c}) !~ %s"
            ).format(c=identifier),
            (r"^-?\d+(\.\d+)?$",),
        )
        invalid_amounts = cursor.fetchone()[0]
        if invalid_amounts:
            raise RuntimeError(f"字段{column_name}为空或金额解析失败：{invalid_amounts}条")

    income_amount = amount_expression("收入金额（+元）")
    signed_expense = amount_expression("支出金额（-元）")
    cursor.execute(
        sql.SQL(
            """
            SELECT
                COUNT(*) FILTER (WHERE {income}<0),
                COUNT(*) FILTER (WHERE {expense}>0),
                COUNT(*) FILTER (WHERE {income}=0 AND {expense}=0),
                COUNT(*) FILTER (WHERE {income}<>0 AND {expense}<>0),
                COUNT(*) FILTER (WHERE NULLIF(BTRIM({account_type}),'') IS NULL)
            FROM common.v_current_pdd_settlement_raw
            """
        ).format(income=income_amount, expense=signed_expense, account_type=account_type)
    )
    sign_errors = cursor.fetchone()
    if any(sign_errors):
        raise RuntimeError(f"收入/支出符号、单边非零或账务类型校验失败：{sign_errors}")

    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM common.v_current_pdd_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}),''),'-') IS NULL OR BTRIM({}) !~ %s"
        ).format(occurred_at, occurred_at),
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    invalid_dates = cursor.fetchone()[0]
    if invalid_dates:
        raise RuntimeError(f"发生时间为空或格式非法：{invalid_dates}条")
    return source_rows, unique_orders, unique_business_events


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id, COUNT(*) source_rows
            FROM common.v_current_pdd_settlement_raw GROUP BY batch_id
        )
        SELECT b.batch_id,b.source_rows,COUNT(c.batch_id),MAX(c.shop_code),
               MAX(c.shop_name),MAX(c.shop_mapping_status)
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id=b.batch_id AND c.platform_code='pdd'
         AND c.target_table='ods_pdd_settlement_raw' AND c.shop_mapping_status='mapped'
        GROUP BY b.batch_id,b.source_rows ORDER BY b.batch_id NULLS FIRST
        """
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"拼多多结算ODS存在未映射或冲突批次：{invalid}")
    return mappings


def validate_ads_bidirectional(cursor, metric: str) -> int:
    if metric == "income":
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                       d.shop_code,d.income_type_code,ROUND(SUM(d.income_amount),2) amount
                FROM dws.dws_pdd_settlement_income_shop_daily_type d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4,5
            ), actual AS (
                SELECT stat_date,platform_code,company_code,shop_code,income_type_code,income_amount amount
                FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='pdd'
            )
            SELECT COUNT(*) FROM (((SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))) x
            """
        )
    elif metric == "expense":
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                       d.shop_code,d.expense_type_code,ROUND(SUM(d.expense_amount),2) amount
                FROM dws.dws_pdd_settlement_expense_shop_daily_type d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4,5
            ), actual AS (
                SELECT stat_date,platform_code,company_code,shop_code,expense_type_code,expense_amount amount
                FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='pdd'
            )
            SELECT COUNT(*) FROM (((SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))) x
            """
        )
    else:
        cursor.execute(
            """
            WITH expected AS (
                SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,d.shop_code,
                       ROUND(SUM(d.income_amount),2) income_amount,
                       ROUND(SUM(d.expense_amount),2) expense_amount,
                       ROUND(SUM(d.income_amount)-SUM(d.expense_amount),2) settlement_net_amount,
                       ROUND(SUM(d.source_settlement_amount),2) source_settlement_amount,
                       ROUND(SUM(d.income_amount)-SUM(d.expense_amount)-SUM(d.source_settlement_amount),2) validation_difference_amount
                FROM dws.dws_pdd_settlement_net_shop_daily d
                LEFT JOIN dim.dim_platform_shop_company m
                  ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
                 AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
                GROUP BY 1,2,3,4
            ), actual AS (
                SELECT stat_date,platform_code,company_code,shop_code,income_amount,expense_amount,
                       settlement_net_amount,source_settlement_amount,validation_difference_amount
                FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='pdd'
            )
            SELECT COUNT(*) FROM (((SELECT * FROM expected EXCEPT SELECT * FROM actual)
                UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))) x
            """
        )
    return cursor.fetchone()[0]


def validate_refund_reclassification(cursor) -> dict[str, object]:
    """核对逐日类型的金额和事件数，退款不可重复进入结算支出。"""
    cursor.execute(
        """
        WITH classified AS (
            SELECT d.*, CASE WHEN account_type='退款'
                OR (account_type='优惠券结算'
                    AND SPLIT_PART(business_description,'|',1)='0020005')
                THEN source_signed_expense_amount ELSE 0 END AS refund_amount
            FROM dwd.dwd_pdd_settlement_net_event_detail d
        ), expected AS (
            SELECT stat_date,platform_code,shop_code,account_type,'income' metric,
                   SUM(income_amount+refund_amount) amount,COUNT(*) events
            FROM classified WHERE income_amount+refund_amount<>0 GROUP BY 1,2,3,4
            UNION ALL
            SELECT stat_date,platform_code,shop_code,account_type,'expense',
                   SUM(expense_amount+refund_amount),COUNT(*)
            FROM classified WHERE expense_amount+refund_amount<>0 GROUP BY 1,2,3,4
        ), actual AS (
            SELECT stat_date,platform_code,shop_code,income_type_name,'income' metric,
                   income_amount amount,included_event_count events
            FROM dws.dws_pdd_settlement_income_shop_daily_type
            UNION ALL
            SELECT stat_date,platform_code,shop_code,expense_type_name,'expense',
                   expense_amount,included_event_count
            FROM dws.dws_pdd_settlement_expense_shop_daily_type
        )
        SELECT COUNT(*) FROM (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        ) differences
        """
    )
    type_differences = cursor.fetchone()[0]
    cursor.execute(
        """
        WITH classified AS (
            SELECT d.*, CASE WHEN account_type='退款'
                OR (account_type='优惠券结算'
                    AND SPLIT_PART(business_description,'|',1)='0020005')
                THEN source_signed_expense_amount ELSE 0 END AS refund_amount
            FROM dwd.dwd_pdd_settlement_net_event_detail d
        ), expected AS (
            SELECT stat_date,platform_code,shop_code,
                   SUM(income_amount+refund_amount) income,
                   SUM(expense_amount+refund_amount) expense,
                   -SUM(expense_amount+refund_amount) display_expense
            FROM classified GROUP BY 1,2,3
        ), actual AS (
            SELECT stat_date,platform_code,shop_code,income_amount,expense_amount,
                   display_expense_amount
            FROM dws.dws_pdd_settlement_net_shop_daily
        )
        SELECT COUNT(*) FROM (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        ) differences
        """
    )
    daily_differences = cursor.fetchone()[0]
    if type_differences or daily_differences:
        raise RuntimeError(
            f"结算退款归属校验失败：日类型差异={type_differences}，日净额组成差异={daily_differences}"
        )
    cursor.execute(
        """SELECT COUNT(*),COALESCE(SUM(source_signed_expense_amount),0)
           FROM dwd.dwd_pdd_settlement_net_event_detail
           WHERE source_signed_expense_amount<>0 AND (account_type='退款'
             OR (account_type='优惠券结算'
                 AND SPLIT_PART(business_description,'|',1)='0020005'))"""
    )
    refund_rows, refund_amount = cursor.fetchone()
    return {"refund_rows": refund_rows, "refund_amount": refund_amount,
            "type_differences": type_differences, "daily_differences": daily_differences}


def validate_pipeline(cursor, source_rows: int) -> dict[str, object]:
    cursor.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM dwd.dwd_pdd_settlement_income_event_detail),
          (SELECT COUNT(*) FROM dwd.dwd_pdd_settlement_expense_event_detail),
          (SELECT COUNT(*) FROM dwd.dwd_pdd_settlement_net_event_detail),
          (SELECT COUNT(*)-COUNT(DISTINCT source_id) FROM dwd.dwd_pdd_settlement_net_event_detail)
        """
    )
    income_dwd_rows, expense_dwd_rows, net_dwd_rows, duplicate_source_ids = cursor.fetchone()
    if (income_dwd_rows, expense_dwd_rows, net_dwd_rows) != (source_rows, source_rows, source_rows):
        raise RuntimeError(f"DWD行数不等于ODS：{income_dwd_rows}/{expense_dwd_rows}/{net_dwd_rows}!={source_rows}")
    if duplicate_source_ids:
        raise RuntimeError(f"DWD source_id重复：{duplicate_source_ids}")

    cursor.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE source_signed_expense_amount>0 OR expense_amount<0),
          COUNT(*) FILTER (WHERE expense_amount<>-source_signed_expense_amount)
        FROM dwd.dwd_pdd_settlement_expense_event_detail
        """
    )
    expense_sign_errors, expense_formula_errors = cursor.fetchone()
    cursor.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE settlement_net_amount<>income_amount-expense_amount),
          COUNT(*) FILTER (WHERE source_settlement_amount<>income_amount+source_signed_expense_amount),
          COUNT(*) FILTER (WHERE validation_difference_amount<>
              settlement_net_amount-source_settlement_amount),
          COUNT(*) FILTER (WHERE validation_difference_amount<>0)
        FROM dwd.dwd_pdd_settlement_net_event_detail
        """
    )
    net_formula_errors, source_formula_errors, validation_formula_errors, source_difference_rows = cursor.fetchone()
    if any((expense_sign_errors, expense_formula_errors, net_formula_errors,
            source_formula_errors, validation_formula_errors, source_difference_rows)):
        raise RuntimeError(
            "DWD符号或公式校验失败："
            f"{expense_sign_errors}/{expense_formula_errors}/{net_formula_errors}/"
            f"{source_formula_errors}/{validation_formula_errors}/{source_difference_rows}"
        )

    refund_reclassification = validate_refund_reclassification(cursor)

    cursor.execute(
        """SELECT COUNT(*),COALESCE(SUM(income_amount),0),COALESCE(SUM(included_event_count),0)
           FROM dws.dws_pdd_settlement_income_shop_daily_type"""
    )
    income_dws_rows, dws_income, income_events = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*),COALESCE(SUM(expense_amount),0),COALESCE(SUM(included_event_count),0)
           FROM dws.dws_pdd_settlement_expense_shop_daily_type"""
    )
    expense_dws_rows, dws_expense, expense_events = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*),MIN(stat_date),MAX(stat_date),COALESCE(SUM(income_amount),0),
               COALESCE(SUM(expense_amount),0),COALESCE(SUM(settlement_net_amount),0),
               COALESCE(SUM(source_settlement_amount),0),
               COALESCE(SUM(validation_difference_amount),0),
               COALESCE(SUM(included_event_count),0)
        FROM dws.dws_pdd_settlement_net_shop_daily
        """
    )
    (net_dws_rows,min_date,max_date,net_income,net_expense,dws_net,source_net,
     validation_difference,included_events) = cursor.fetchone()
    if income_events + expense_events != source_rows or included_events != source_rows:
        raise RuntimeError(
            f"全部账务流水未完整纳入：income={income_events},expense={expense_events},"
            f"net={included_events},source={source_rows}"
        )
    if (dws_income,dws_expense,dws_net) != (net_income,net_expense,net_income-net_expense):
        raise RuntimeError(
            f"三套DWS汇总不一致：income={dws_income}/{net_income},"
            f"expense={dws_expense}/{net_expense},net={dws_net}"
        )
    if dws_net != source_net or validation_difference != 0:
        raise RuntimeError(
            f"净额与源带符号流水不一致：net={dws_net},source={source_net},diff={validation_difference}"
        )

    cursor.execute(
        """
        SELECT
          (SELECT COALESCE(SUM(income_amount),0) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='pdd'),
          (SELECT COALESCE(SUM(expense_amount),0) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='pdd'),
          (SELECT COALESCE(SUM(settlement_net_amount),0) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='pdd'),
          (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='pdd' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='pdd' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='pdd' AND company_code='unmapped')
        """
    )
    ads_income,ads_expense,ads_net,unmapped_income,unmapped_expense,unmapped_net = cursor.fetchone()
    if (ads_income,ads_expense,ads_net) != (dws_income,dws_expense,dws_net):
        raise RuntimeError(
            f"DWS/ADS汇总不一致：DWS={dws_income}/{dws_expense}/{dws_net},"
            f"ADS={ads_income}/{ads_expense}/{ads_net}"
        )

    bidirectional_errors = tuple(validate_ads_bidirectional(cursor, m) for m in ("income","expense","net"))
    if any(bidirectional_errors):
        raise RuntimeError(f"DWS/ADS双向逐粒度差异：{bidirectional_errors}")

    cursor.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code,shop_code,income_type_code
             FROM ads.ads_settlement_income_company_shop_daily_type GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code,shop_code,expense_type_code
             FROM ads.ads_settlement_expense_company_shop_daily_type GROUP BY 1,2,3,4,5 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code,shop_code
             FROM ads.ads_settlement_net_company_shop_daily GROUP BY 1,2,3,4 HAVING COUNT(*)>1) x)
        """
    )
    duplicate_ads_keys = cursor.fetchone()
    if any(duplicate_ads_keys):
        raise RuntimeError(f"ADS主键重复：{duplicate_ads_keys}")

    cursor.execute(
        """
        WITH ranked AS (
          SELECT *,ROW_NUMBER() OVER(PARTITION BY account_type,business_description ORDER BY source_id) rn,
                 CASE WHEN account_type='退款'
                   OR (account_type='优惠券结算'
                       AND SPLIT_PART(business_description,'|',1)='0020005')
                 THEN source_signed_expense_amount ELSE 0 END refund_amount
          FROM dwd.dwd_pdd_settlement_net_event_detail
        )
        SELECT account_type,source_id,stat_date,income_amount+refund_amount,expense_amount+refund_amount,
               settlement_net_amount,source_settlement_amount,validation_difference_amount
        FROM ranked WHERE rn=1 ORDER BY account_type
        """
    )
    samples = cursor.fetchall()
    if len(samples) < 5:
        raise RuntimeError(f"公式抽样账务类型不足5类：{samples}")

    cursor.execute(
        """SELECT platform_code,SUM(income_amount)
           FROM ads.ads_settlement_income_company_shop_daily_type
           GROUP BY platform_code ORDER BY platform_code"""
    )
    platform_income_totals = cursor.fetchall()
    return {
        "dwd_rows":(income_dwd_rows,expense_dwd_rows,net_dwd_rows),
        "dws_rows":(income_dws_rows,expense_dws_rows,net_dws_rows),
        "events":(income_events,expense_events,included_events),
        "date_range":(min_date,max_date),
        "income":dws_income,"expense":dws_expense,"net":dws_net,
        "source_net":source_net,"difference":validation_difference,
        "unmapped":(unmapped_income,unmapped_expense,unmapped_net),
        "bidirectional_errors":bidirectional_errors,
        "duplicate_ads_keys":duplicate_ads_keys,
        "samples":samples,"platform_income_totals":platform_income_totals,
        "refund_reclassification":refund_reclassification,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """SELECT obj_description(c.oid,'pg_class') FROM pg_class c
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s""",
            (schema_name,table_name),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
                 AND col_description(c.oid,a.attnum) IS NULL ORDER BY a.attnum""",
            (schema_name,table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{r[0]}" for r in cursor.fetchall())
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def run_pipeline(args: argparse.Namespace) -> None:
    conn = psycopg2.connect(
        host=args.host,port=args.port,dbname=args.dbname,user=args.user,password=args.password
    )
    try:
        with conn.cursor() as cursor:
            execute_files(cursor,PREPARE_SQL_FILES)
            source_rows,unique_orders,unique_events = validate_ods(cursor)
            mappings = validate_batch_shop_mapping(cursor)
            execute_files(cursor,CREATE_SQL_FILES)
            execute_files(cursor,REFRESH_SQL_FILES)
            result = validate_pipeline(cursor,source_rows)
            validate_comments(cursor)
            monthly = validate_monthly_result(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS来源行数/唯一订单数/业务字段组合键数：{source_rows}/{unique_orders}/{unique_events}")
    print("批次店铺映射：")
    for batch_id,rows,_,shop_code,shop_name,status in mappings:
        print(f"  批次{batch_id}：{rows}行 -> {shop_code} / {shop_name} / {status}")
    print(f"DWD行数（收入/支出/净额）：{result['dwd_rows']}")
    print(f"DWS行数（收入类型/支出类型/净额日）：{result['dws_rows']}")
    print(f"DWS收入/支出/净额纳入事件数：{result['events']}")
    print(f"ADS拼多多日期范围：{result['date_range'][0]} 至 {result['date_range'][1]}")
    print(f"拼多多收入金额：{result['income']:.2f}")
    print(f"拼多多支出金额：{result['expense']:.2f}")
    print(f"拼多多计算结算净额：{result['net']:.2f}")
    print(f"拼多多源带符号流水合计：{result['source_net']:.2f}")
    print(f"拼多多净额核验差额：{result['difference']:.2f}")
    print(f"ADS未匹配公司行数（收入/支出/净额）：{result['unmapped']}")
    print(f"DWS/ADS双向差异（收入/支出/净额）：{result['bidirectional_errors']}")
    print(f"ADS重复主键组（收入/支出/净额）：{result['duplicate_ads_keys']}")
    print(f"跨平台收入合计：{result['platform_income_totals']}")
    print(f"退款重分类校验：{result['refund_reclassification']}")
    print(f"月度透视校验：日/月差异={monthly['daily_not_in_monthly']}/{monthly['monthly_not_in_daily']}，公式错误={monthly['formula_errors']}")
    print("公式抽样（账务类型,source_id,日期,结算收入,正向支出,净额,源带符号金额,差额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
