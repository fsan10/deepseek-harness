#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新小红书结算收入、支出和结算净额三套独立指标链路。"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
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
    "xhs/settlement_income/144_dwd_xhs_settlement_income_event_detail_postgres.sql",
    "xhs/settlement_income/145_dws_xhs_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ks/settlement_income/97_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "pdd/settlement_income/109_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_income/121_dws_wechat_channels_settlement_income_shop_daily_type_postgres.sql",
    "tmall/settlement_income/133_dws_tmall_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "xhs/settlement_expense/148_dwd_xhs_settlement_expense_event_detail_postgres.sql",
    "xhs/settlement_expense/149_dws_xhs_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ks/settlement_expense/101_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "pdd/settlement_expense/113_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_expense/125_dws_wechat_channels_settlement_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_expense/137_dws_tmall_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "xhs/settlement_net/152_dwd_xhs_settlement_net_event_detail_postgres.sql",
    "xhs/settlement_net/153_dws_xhs_settlement_net_shop_daily_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ks/settlement_net/105_dws_ks_settlement_net_shop_daily_postgres.sql",
    "pdd/settlement_net/117_dws_pdd_settlement_net_shop_daily_postgres.sql",
    "wechat_channels/settlement_net/129_dws_wechat_channels_settlement_net_shop_daily_postgres.sql",
    "tmall/settlement_net/141_dws_tmall_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "xhs/settlement_income/146_refresh_dwd_xhs_settlement_income_event_detail_postgres.sql",
    "xhs/settlement_income/147_refresh_dws_xhs_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "xhs/settlement_expense/150_refresh_dwd_xhs_settlement_expense_event_detail_postgres.sql",
    "xhs/settlement_expense/151_refresh_dws_xhs_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "xhs/settlement_net/154_refresh_dwd_xhs_settlement_net_event_detail_postgres.sql",
    "xhs/settlement_net/155_refresh_dws_xhs_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]
REQUIRED_INCOME_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no",
    "row_hash", "ingest_time", "订单号", "售后单号", "结算时间", "交易类型",
    "动账金额", "结算账户", "计佣基数", "商品实付/实退", "运费实付/实退",
    "商家优惠总额", "平台优惠补贴", "政府券优惠补贴", "平台佣金", "买手佣金",
    "花呗分期手续费",
}
REQUIRED_EXPENSE_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no",
    "row_hash", "ingest_time", "订单号", "业务款项", "业务单号", "结算时间",
    "结算账户", "动账金额", "备注",
}
NEW_TABLES = [
    ("dwd", "dwd_xhs_settlement_income_event_detail"),
    ("dws", "dws_xhs_settlement_income_shop_daily_type"),
    ("dwd", "dwd_xhs_settlement_expense_event_detail"),
    ("dws", "dws_xhs_settlement_expense_shop_daily_type"),
    ("dwd", "dwd_xhs_settlement_net_event_detail"),
    ("dws", "dws_xhs_settlement_net_shop_daily"),
]
EXPECTED = {
    "income_rows": 287,
    "expense_rows": 171,
    "income_batches": 1,
    "expense_batches": 1,
    "income_amount": Decimal("15099.78"),
    "settlement_credit_amount": Decimal("20462.97"),
    "refund_amount": Decimal("-5363.19"),
    "expense_amount": Decimal("120.18"),
    "net_amount": Decimal("14979.60"),
    "income_dws_rows": 47,
    "expense_dws_rows": 24,
    "net_dws_rows": 31,
    "component_difference_count": 1,
    "component_difference_amount": Decimal("0.01"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新小红书结算收入、支出和结算净额指标")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-baseline",
        action="store_true",
        default=os.getenv("XHS_ENFORCE_BASELINE", "0").lower() in {"1", "true", "yes"},
        help="仅用于固定样本回归；生产默认按当前ODS动态验收，不因新增合法批次失败。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
    if file_names == PREPARE_SQL_FILES:
        prepare_settlement_sources(cursor, 'xhs')


def validate_table_columns(cursor, table_name: str, required: set[str]) -> None:
    cursor.execute("SELECT to_regclass(%s)", (f"ods.{table_name}",))
    if cursor.fetchone()[0] is None:
        raise RuntimeError(f"缺少来源表：ods.{table_name}")
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='ods' AND table_name=%s""",
        (table_name,),
    )
    missing = sorted(required - {row[0] for row in cursor.fetchall()})
    if missing:
        raise RuntimeError(f"{table_name}缺少必需字段：{', '.join(missing)}")


def validate_ods(cursor, *, enforce_baseline: bool = False) -> dict[str, object]:
    validate_table_columns(cursor, "ods_xhs_settlement_income_raw", REQUIRED_INCOME_COLUMNS)
    validate_table_columns(cursor, "ods_xhs_settlement_expense_raw", REQUIRED_EXPENSE_COLUMNS)
    cursor.execute(
        """
        WITH source_rows AS (
            SELECT
                'order:' || id::text AS source_key,
                'order:' || row_hash::text AS row_key,
                'order'::text AS source_kind,
                batch_id,
                "结算时间" AS settlement_time_text,
                NULLIF(BTRIM("交易类型"), '') AS income_type,
                NULLIF(BTRIM("动账金额"), '') AS movement_amount_text
            FROM common.v_current_xhs_settlement_income_raw
            UNION ALL
            SELECT
                'appeal:' || id::text,
                'appeal:' || row_hash::text,
                'appeal'::text,
                batch_id,
                "结算时间",
                '申诉调账'::text,
                NULLIF(BTRIM("动账金额"), '')
            FROM common.v_current_xhs_settlement_expense_raw
            WHERE BTRIM("业务款项") = '申诉调账'
        ), parsed AS (
            SELECT
                source_rows.*,
                CASE
                    WHEN movement_amount_text ~ '^-?\\d+(\\.\\d+)?$'
                    THEN movement_amount_text::numeric
                END AS movement_amount
            FROM source_rows
        )
        SELECT
            COUNT(*) FILTER (WHERE source_kind='order'),
            COUNT(*) FILTER (WHERE source_kind='appeal'),
            COUNT(*),
            COUNT(DISTINCT source_key),
            COUNT(DISTINCT row_key),
            COUNT(DISTINCT batch_id),
            COUNT(*) FILTER (WHERE batch_id IS NULL),
            COUNT(*) FILTER (WHERE NULLIF(BTRIM(settlement_time_text),'') IS NULL
                                OR BTRIM(settlement_time_text) !~ '^\\d{4}-\\d{2}-\\d{2}'),
            COUNT(*) FILTER (WHERE income_type IS NULL),
            COUNT(*) FILTER (WHERE movement_amount_text IS NULL
                                OR movement_amount_text !~ '^-?\\d+(\\.\\d+)?$'),
            ROUND(COALESCE(SUM(movement_amount), 0), 2),
            ROUND(COALESCE(SUM(movement_amount) FILTER (WHERE income_type='结算入账'), 0), 2),
            ROUND(COALESCE(SUM(movement_amount) FILTER (WHERE income_type='退款'), 0), 2),
            ROUND(COALESCE(SUM(movement_amount) FILTER (WHERE source_kind='appeal'), 0), 2)
        FROM parsed
        """
    )
    income = cursor.fetchone()
    cursor.execute(
        """
        WITH cleaned AS (
            SELECT
                id,
                row_hash,
                batch_id,
                "结算时间",
                "业务款项",
                NULLIF(BTRIM("动账金额"), '') AS movement_amount_text,
                BTRIM("业务款项") = '申诉调账' AS is_income_adjustment
            FROM common.v_current_xhs_settlement_expense_raw
        ), parsed AS (
            SELECT
                cleaned.*,
                CASE
                    WHEN movement_amount_text ~ '^-?\\d+(\\.\\d+)?$'
                    THEN movement_amount_text::numeric
                END AS movement_amount
            FROM cleaned
        )
        SELECT
            COUNT(*) FILTER (WHERE NOT is_income_adjustment),
            COUNT(DISTINCT id) FILTER (WHERE NOT is_income_adjustment),
            COUNT(DISTINCT row_hash) FILTER (WHERE NOT is_income_adjustment),
            COUNT(DISTINCT batch_id) FILTER (WHERE NOT is_income_adjustment),
            COUNT(*) FILTER (WHERE batch_id IS NULL),
            COUNT(*) FILTER (WHERE NULLIF(BTRIM("结算时间"),'') IS NULL
                                OR BTRIM("结算时间") !~ '^\\d{4}-\\d{2}-\\d{2}'),
            COUNT(*) FILTER (WHERE NULLIF(BTRIM("业务款项"),'') IS NULL),
            COUNT(*) FILTER (WHERE movement_amount_text IS NULL
                                OR movement_amount_text !~ '^-?\\d+(\\.\\d+)?$'),
            ROUND(-COALESCE(SUM(movement_amount) FILTER (WHERE NOT is_income_adjustment), 0), 2),
            COUNT(*),
            COUNT(*) FILTER (WHERE is_income_adjustment)
        FROM parsed
        """
    )
    expense = cursor.fetchone()
    if income[0] == 0 or expense[9] == 0:
        raise RuntimeError("小红书结算收入或支出ODS无数据，停止刷新")
    if income[2] != income[3] or income[2] != income[4]:
        raise RuntimeError(f"收入ODS稳定粒度重复：{income[2:5]}")
    if expense[0] != expense[1] or expense[0] != expense[2]:
        raise RuntimeError(f"支出ODS稳定粒度重复：{expense[:3]}")
    if income[1] != expense[10] or income[1] + expense[0] != expense[9]:
        raise RuntimeError(
            "小红书其他服务款收入/费用分类不完整："
            f"申诉调账收入={income[1]}/{income[13]}，"
            f"费用={expense[0]}，原始其他服务款={expense[9]}"
        )
    if any(income[6:10]):
        raise RuntimeError(f"收入ODS批次、日期、类型或金额校验失败：{income[6:10]}")
    # 费用类其他服务款是带符号资金流水，正数是费用退款或补回，不能按纯支出表禁止非负金额。
    if any(expense[4:8]):
        raise RuntimeError(f"支出ODS批次、日期、类型或金额校验失败：{expense[4:8]}")
    actual = {
        "raw_income_rows": income[0],
        "appeal_adjustment_rows": income[1],
        "appeal_adjustment_income_amount": income[13],
        "income_rows": income[2],
        "expense_rows": expense[0],
        "income_batches": income[5],
        "expense_batches": expense[3],
        "income_amount": income[10],
        "settlement_credit_amount": income[11],
        "refund_amount": income[12],
        "expense_amount": expense[8],
        "net_amount": income[10] - expense[8],
    }
    if enforce_baseline:
        for key in ("income_rows", "expense_rows", "income_batches", "expense_batches",
                    "income_amount", "settlement_credit_amount", "refund_amount",
                    "expense_amount", "net_amount"):
            if actual[key] != EXPECTED[key]:
                raise RuntimeError(f"ODS验收基准变化：{key}={actual[key]}，预期{EXPECTED[key]}")
    return actual


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """WITH source_batches AS (
             SELECT batch_id,'ods_xhs_settlement_income_raw' target_table,COUNT(*) source_rows
             FROM ods.ods_xhs_settlement_income_raw GROUP BY batch_id
             UNION ALL
             SELECT batch_id,'ods_xhs_settlement_expense_raw',COUNT(*)
             FROM ods.ods_xhs_settlement_expense_raw GROUP BY batch_id
           )
           SELECT b.batch_id,b.target_table,b.source_rows,COUNT(c.batch_id),
                  MAX(c.shop_code),MAX(c.shop_name),MAX(c.shop_mapping_status)
           FROM source_batches b
           LEFT JOIN common.v_ingest_batch_shop_context c
             ON c.batch_id=b.batch_id AND c.platform_code='xhs'
            AND c.target_table=b.target_table AND c.shop_mapping_status='mapped'
           GROUP BY b.batch_id,b.target_table,b.source_rows ORDER BY b.batch_id"""
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[3] != 1]
    if invalid:
        raise RuntimeError(f"小红书结算ODS存在未映射或冲突批次：{invalid}")
    return mappings


def validate_comments(cursor) -> None:
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """SELECT obj_description(c.oid),COUNT(a.attname),
                      COUNT(*) FILTER (WHERE col_description(c.oid,a.attnum) IS NULL)
               FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
               WHERE n.nspname=%s AND c.relname=%s GROUP BY c.oid""",
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if row is None or row[0] is None or row[2] != 0:
            raise RuntimeError(f"表或字段注释不完整：{schema_name}.{table_name} -> {row}")


def validate_result(
    cursor,
    ods_result: dict[str, object],
    *,
    enforce_baseline: bool = False,
) -> dict[str, object]:
    cursor.execute(
        """SELECT COUNT(*),COUNT(DISTINCT source_id),MIN(stat_date),MAX(stat_date),
                  ROUND(SUM(income_amount),2),
                  COUNT(*) FILTER (WHERE component_difference_amount<>0),
                  ROUND(SUM(component_difference_amount),2)
           FROM dwd.dwd_xhs_settlement_income_event_detail"""
    )
    income_dwd = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*),COUNT(DISTINCT source_id),MIN(stat_date),MAX(stat_date),
                  ROUND(SUM(expense_amount),2),ROUND(SUM(source_movement_amount),2)
           FROM dwd.dwd_xhs_settlement_expense_event_detail"""
    )
    expense_dwd = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*),COUNT(DISTINCT source_event_key),MIN(stat_date),MAX(stat_date),
                  ROUND(SUM(income_amount),2),ROUND(SUM(expense_amount),2),
                  ROUND(SUM(settlement_net_amount),2),ROUND(SUM(source_settlement_amount),2),
                  ROUND(SUM(validation_difference_amount),2)
           FROM dwd.dwd_xhs_settlement_net_event_detail"""
    )
    net_dwd = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*) FILTER (WHERE transaction_type='申诉调账'),
                  ROUND(COALESCE(SUM(income_amount) FILTER (WHERE transaction_type='申诉调账'), 0), 2)
           FROM dwd.dwd_xhs_settlement_income_event_detail"""
    )
    income_appeal_dwd = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*) FILTER (WHERE business_item='申诉调账')
           FROM dwd.dwd_xhs_settlement_expense_event_detail"""
    )
    expense_appeal_dwd = cursor.fetchone()[0]
    expected_income_rows = int(ods_result["income_rows"])
    expected_expense_rows = int(ods_result["expense_rows"])
    expected_net_events = expected_income_rows + expected_expense_rows
    expected_income_amount = ods_result["income_amount"]
    expected_expense_amount = ods_result["expense_amount"]
    expected_net_amount = ods_result["net_amount"]
    expected_appeal_rows = int(ods_result["appeal_adjustment_rows"])
    expected_appeal_amount = ods_result["appeal_adjustment_income_amount"]
    if income_appeal_dwd != (expected_appeal_rows, expected_appeal_amount) or expense_appeal_dwd != 0:
        raise RuntimeError(
            "申诉调账收入/费用分流失败："
            f"DWD收入={income_appeal_dwd}，DWD费用={expense_appeal_dwd}，"
            f"ODS={(expected_appeal_rows, expected_appeal_amount)}"
        )
    if enforce_baseline:
        if income_dwd[0:2] != (EXPECTED["income_rows"], EXPECTED["income_rows"]):
            raise RuntimeError(f"收入DWD粒度校验失败：{income_dwd}")
        if income_dwd[4] != EXPECTED["income_amount"] or income_dwd[5] != EXPECTED["component_difference_count"] or income_dwd[6] != EXPECTED["component_difference_amount"]:
            raise RuntimeError(f"收入DWD金额或组成核验失败：{income_dwd}")
        if expense_dwd[0:2] != (EXPECTED["expense_rows"], EXPECTED["expense_rows"]):
            raise RuntimeError(f"支出DWD粒度校验失败：{expense_dwd}")
        if expense_dwd[4] != EXPECTED["expense_amount"] or expense_dwd[5] != -EXPECTED["expense_amount"]:
            raise RuntimeError(f"支出DWD金额或源符号校验失败：{expense_dwd}")
        if net_dwd[0:2] != (EXPECTED["income_rows"] + EXPECTED["expense_rows"],) * 2 or net_dwd[4:9] != (
            EXPECTED["income_amount"], EXPECTED["expense_amount"], EXPECTED["net_amount"],
            EXPECTED["net_amount"], Decimal("0.00")):
            raise RuntimeError(f"净额DWD公式或源金额核验失败：{net_dwd}")
    else:
        if income_dwd[0:2] != (expected_income_rows, expected_income_rows) or income_dwd[4] != expected_income_amount:
            raise RuntimeError(f"收入DWD与ODS不一致：{income_dwd}，ODS={ods_result}")
        if expense_dwd[0:2] != (expected_expense_rows, expected_expense_rows) or expense_dwd[4] != expected_expense_amount or expense_dwd[5] != -expected_expense_amount:
            raise RuntimeError(f"支出DWD与ODS不一致：{expense_dwd}，ODS={ods_result}")
        if net_dwd[0:2] != (expected_net_events, expected_net_events) or net_dwd[4:9] != (
            expected_income_amount, expected_expense_amount, expected_net_amount,
            expected_net_amount, Decimal("0.00")):
            raise RuntimeError(f"净额DWD公式或ODS源金额核验失败：{net_dwd}，ODS={ods_result}")

    cursor.execute("SELECT COUNT(*),ROUND(SUM(income_amount),2),SUM(included_event_count) FROM dws.dws_xhs_settlement_income_shop_daily_type")
    income_dws = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*),
                  ROUND(COALESCE(SUM(income_amount), 0), 2),
                  COALESCE(SUM(included_event_count), 0)
           FROM dws.dws_xhs_settlement_income_shop_daily_type
           WHERE income_type_code='appeal_adjustment_income'"""
    )
    income_appeal_dws = cursor.fetchone()
    cursor.execute("SELECT COUNT(*),ROUND(SUM(expense_amount),2),SUM(included_event_count) FROM dws.dws_xhs_settlement_expense_shop_daily_type")
    expense_dws = cursor.fetchone()
    if expected_appeal_rows == 0:
        appeal_dws_valid = income_appeal_dws == (0, Decimal("0.00"), 0)
    else:
        appeal_dws_valid = (
            income_appeal_dws[0] > 0
            and income_appeal_dws[1:] == (expected_appeal_amount, expected_appeal_rows)
        )
    if not appeal_dws_valid:
        raise RuntimeError(f"申诉调账收入DWS验收失败：{income_appeal_dws}，ODS={ods_result}")
    cursor.execute(
        """SELECT COUNT(*),ROUND(SUM(income_amount),2),ROUND(SUM(expense_amount),2),
                  ROUND(SUM(settlement_net_amount),2),ROUND(SUM(source_settlement_amount),2),
                  ROUND(SUM(validation_difference_amount),2),SUM(included_event_count)
           FROM dws.dws_xhs_settlement_net_shop_daily"""
    )
    net_dws = cursor.fetchone()
    if enforce_baseline:
        if income_dws != (EXPECTED["income_dws_rows"], EXPECTED["income_amount"], EXPECTED["income_rows"]):
            raise RuntimeError(f"收入DWS验收失败：{income_dws}")
        if expense_dws != (EXPECTED["expense_dws_rows"], EXPECTED["expense_amount"], EXPECTED["expense_rows"]):
            raise RuntimeError(f"支出DWS验收失败：{expense_dws}")
        if net_dws != (EXPECTED["net_dws_rows"], EXPECTED["income_amount"], EXPECTED["expense_amount"],
                        EXPECTED["net_amount"], EXPECTED["net_amount"], Decimal("0.00"), expected_net_events):
            raise RuntimeError(f"净额DWS验收失败：{net_dws}")
    else:
        if income_dws[0] <= 0 or income_dws[1:] != (expected_income_amount, expected_income_rows):
            raise RuntimeError(f"收入DWS与ODS不一致：{income_dws}，ODS={ods_result}")
        if expense_dws[0] <= 0 or expense_dws[1:] != (expected_expense_amount, expected_expense_rows):
            raise RuntimeError(f"支出DWS与ODS不一致：{expense_dws}，ODS={ods_result}")
        if net_dws[0] <= 0 or net_dws[1:] != (
            expected_income_amount, expected_expense_amount, expected_net_amount,
            expected_net_amount, Decimal("0.00"), expected_net_events):
            raise RuntimeError(f"净额DWS公式或ODS源金额核验失败：{net_dws}，ODS={ods_result}")

    cursor.execute(
        """SELECT ROUND(COALESCE(SUM(income_amount), 0),2)
           FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='xhs'"""
    )
    ads_income = cursor.fetchone()[0]
    cursor.execute(
        """SELECT ROUND(COALESCE(SUM(expense_amount), 0),2)
           FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='xhs'"""
    )
    ads_expense = cursor.fetchone()[0]
    cursor.execute(
        """SELECT ROUND(SUM(income_amount),2),ROUND(SUM(expense_amount),2),
                  ROUND(SUM(settlement_net_amount),2),ROUND(SUM(source_settlement_amount),2),
                  ROUND(SUM(validation_difference_amount),2),MIN(stat_date),MAX(stat_date),
                  COUNT(DISTINCT company_code),COUNT(DISTINCT shop_code),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='xhs'"""
    )
    ads_net = cursor.fetchone()
    if ads_income != ods_result["income_amount"] or ads_expense != ods_result["expense_amount"]:
        raise RuntimeError(f"指标卡与ODS不一致：{ads_income}/{ads_expense}")
    if enforce_baseline:
        if ads_net[:5] != (EXPECTED["income_amount"], EXPECTED["expense_amount"], EXPECTED["net_amount"],
                           EXPECTED["net_amount"], Decimal("0.00")) or ads_net[7:] != (1, 1, 0):
            raise RuntimeError(f"净额ADS金额、维度或映射验收失败：{ads_net}")
    elif ads_net[:5] != (expected_income_amount, expected_expense_amount, expected_net_amount,
                         expected_net_amount, Decimal("0.00")) or ads_net[7] <= 0 or ads_net[8] <= 0 or ads_net[9] != 0:
        raise RuntimeError(f"净额ADS金额、维度或映射验收失败：{ads_net}，ODS={ods_result}")

    cursor.execute(
        """SELECT COUNT(*) FROM (
             SELECT stat_date,platform_code,company_code,shop_code,COUNT(*)
             FROM ads.ads_settlement_net_company_shop_daily
             GROUP BY 1,2,3,4 HAVING COUNT(*)>1
           ) x"""
    )
    if cursor.fetchone()[0] != 0:
        raise RuntimeError("共享净额ADS存在重复业务主键")
    cursor.execute(
        """SELECT ROUND(SUM(income_amount),2),ROUND(SUM(expense_amount),2),
                  ROUND(SUM(settlement_net_amount),2),
                  ROUND(SUM(income_amount)-SUM(expense_amount)-SUM(settlement_net_amount),2),
                  ROUND(SUM(validation_difference_amount),2)
           FROM ads.ads_settlement_net_company_shop_daily"""
    )
    shared_cards = cursor.fetchone()
    if shared_cards[3] != Decimal("0.00"):
        raise RuntimeError(f"共享指标卡公式不成立：{shared_cards}")
    validate_comments(cursor)
    return {
        "income_dwd": income_dwd, "expense_dwd": expense_dwd, "net_dwd": net_dwd,
        "income_dws": income_dws, "expense_dws": expense_dws, "net_dws": net_dws,
        "ads_net": ads_net, "shared_cards": shared_cards,
    }


def print_samples(cursor) -> None:
    cursor.execute(
        """SELECT '收入',source_id,stat_date,transaction_type,income_amount,component_difference_amount
           FROM dwd.dwd_xhs_settlement_income_event_detail
           ORDER BY (transaction_type='退款'),source_id LIMIT 3"""
    )
    samples = cursor.fetchall()
    cursor.execute(
        """SELECT '收入差异',source_id,stat_date,transaction_type,income_amount,component_difference_amount
           FROM dwd.dwd_xhs_settlement_income_event_detail
           WHERE component_difference_amount<>0 LIMIT 1"""
    )
    samples += cursor.fetchall()
    cursor.execute(
        """SELECT '支出',source_id,stat_date,business_item,expense_amount,source_movement_amount
           FROM dwd.dwd_xhs_settlement_expense_event_detail ORDER BY source_id LIMIT 2"""
    )
    samples += cursor.fetchall()
    print("DWD抽样（至少5条）：")
    for sample in samples:
        print("  ", sample)


def main() -> None:
    args = build_parser().parse_args()
    connection = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )
    try:
        with connection:
            with connection.cursor() as cursor:
                execute_files(cursor, PREPARE_SQL_FILES)
                ods_result = validate_ods(cursor, enforce_baseline=args.enforce_baseline)
                mappings = validate_batch_shop_mapping(cursor)
                execute_files(cursor, CREATE_SQL_FILES)
                execute_files(cursor, REFRESH_SQL_FILES)
                result = validate_result(
                    cursor,
                    ods_result,
                    enforce_baseline=args.enforce_baseline,
                )
                print_samples(cursor)
        print("小红书结算收入、支出和结算净额指标刷新成功")
        print("ODS基准：", ods_result)
        print("批次店铺映射：", mappings)
        print("小红书ADS：", result["ads_net"])
        print("全平台指标卡（收入/支出/净额/公式差/源核验差）：", result["shared_cards"])
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
