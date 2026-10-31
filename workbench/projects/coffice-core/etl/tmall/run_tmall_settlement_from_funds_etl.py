#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从天猫支付宝账户和聚合账户资金中提取结算指标。

资金表完整保留在专属 DWD；DWS 只纳入已确认的交易收款/交易付款收入和
备注可识别的平台费用。旧结算 ODS 仍用于历史月份：同一自然月同时存在
资金与旧结算数据时，以资金来源覆盖该月，避免重复计入。
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
except ImportError as exc:  # pragma: no cover - 运行环境缺依赖时的提示
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
LEGACY_CREATE_SQL_FILES = [
    "tmall/settlement_income/132_dwd_tmall_settlement_income_event_detail_postgres.sql",
    "tmall/settlement_income/133_dws_tmall_settlement_income_shop_daily_type_postgres.sql",
    "tmall/settlement_expense/136_dwd_tmall_settlement_expense_event_detail_postgres.sql",
    "tmall/settlement_expense/137_dws_tmall_settlement_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_net/140_dwd_tmall_settlement_net_event_detail_postgres.sql",
    "tmall/settlement_net/141_dws_tmall_settlement_net_shop_daily_postgres.sql",
]
LEGACY_REFRESH_SQL_FILES = [
    "tmall/settlement_income/134_refresh_dwd_tmall_settlement_income_event_detail_postgres.sql",
    "tmall/settlement_income/135_refresh_dws_tmall_settlement_income_shop_daily_type_postgres.sql",
    "tmall/settlement_expense/138_refresh_dwd_tmall_settlement_expense_event_detail_postgres.sql",
    "tmall/settlement_expense/139_refresh_dws_tmall_settlement_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_net/142_refresh_dwd_tmall_settlement_net_event_detail_postgres.sql",
    "tmall/settlement_net/143_refresh_dws_tmall_settlement_net_shop_daily_postgres.sql",
]
FUND_CREATE_SQL_FILES = [
    "tmall/settlement_fund/402_dwd_tmall_settlement_fund_event_detail_postgres.sql",
    "tmall/settlement_fund/403_dws_tmall_settlement_fund_income_shop_daily_type_postgres.sql",
    "tmall/settlement_fund/404_dws_tmall_settlement_fund_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_fund/405_dws_tmall_settlement_fund_net_shop_daily_postgres.sql",
]
FUND_REFRESH_SQL_FILES = [
    "tmall/settlement_fund/406_refresh_dwd_tmall_settlement_fund_event_detail_postgres.sql",
    "tmall/settlement_fund/407_refresh_dws_tmall_settlement_fund_income_shop_daily_type_postgres.sql",
    "tmall/settlement_fund/408_refresh_dws_tmall_settlement_fund_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_fund/409_refresh_dws_tmall_settlement_fund_net_shop_daily_postgres.sql",
]
COMBINE_SQL_FILES = [
    "tmall/settlement_fund/410_refresh_dws_tmall_settlement_income_shop_daily_type_combined_postgres.sql",
    "tmall/settlement_fund/411_refresh_dws_tmall_settlement_expense_shop_daily_type_combined_postgres.sql",
    "tmall/settlement_fund/412_refresh_dws_tmall_settlement_net_shop_daily_combined_postgres.sql",
]
ADS_CREATE_SQL_FILES = [
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
ALL_DWS_CREATE_SQL_FILES = [
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ks/settlement_income/97_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "pdd/settlement_income/109_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_income/121_dws_wechat_channels_settlement_income_shop_daily_type_postgres.sql",
    "tmall/settlement_income/133_dws_tmall_settlement_income_shop_daily_type_postgres.sql",
    "xhs/settlement_income/145_dws_xhs_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ks/settlement_expense/101_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "pdd/settlement_expense/113_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_expense/125_dws_wechat_channels_settlement_expense_shop_daily_type_postgres.sql",
    "tmall/settlement_expense/137_dws_tmall_settlement_expense_shop_daily_type_postgres.sql",
    "xhs/settlement_expense/149_dws_xhs_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ks/settlement_net/105_dws_ks_settlement_net_shop_daily_postgres.sql",
    "pdd/settlement_net/117_dws_pdd_settlement_net_shop_daily_postgres.sql",
    "wechat_channels/settlement_net/129_dws_wechat_channels_settlement_net_shop_daily_postgres.sql",
    "tmall/settlement_net/141_dws_tmall_settlement_net_shop_daily_postgres.sql",
    "xhs/settlement_net/153_dws_xhs_settlement_net_shop_daily_postgres.sql",
]
ADS_REFRESH_SQL_FILES = [
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]

FUND_TABLES = (
    "dwd.dwd_tmall_settlement_fund_event_detail",
    "dws.dws_tmall_settlement_fund_income_shop_daily_type",
    "dws.dws_tmall_settlement_fund_expense_shop_daily_type",
    "dws.dws_tmall_settlement_fund_net_shop_daily",
)
COMMENTED_TABLES = (
    ("dwd", "dwd_tmall_settlement_fund_event_detail"),
    ("dws", "dws_tmall_settlement_fund_income_shop_daily_type"),
    ("dws", "dws_tmall_settlement_fund_expense_shop_daily_type"),
    ("dws", "dws_tmall_settlement_fund_net_shop_daily"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从天猫两张资金单刷新结算指标。")
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
        prepare_settlement_sources(cursor, 'tmall')


def table_exists(cursor, qualified_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (qualified_name,))
    return cursor.fetchone()[0] is not None


def validate_table_columns(cursor, table_name: str, required: set[str]) -> None:
    qualified = f"ods.{table_name}"
    if not table_exists(cursor, qualified):
        raise RuntimeError(f"缺少来源表：{qualified}")
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='ods' AND table_name=%s""",
        (table_name,),
    )
    missing = sorted(required - {row[0] for row in cursor.fetchall()})
    if missing:
        raise RuntimeError(f"{table_name}缺少必需字段：{', '.join(missing)}")


def validate_sources(cursor) -> dict[str, object]:
    validate_table_columns(
        cursor,
        "ods_tmall_aggregate_fund_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "入帐日期", "入帐时间", "支付流水号", "主订单id",
            "子订单id", "入帐类型", "收入金额(元)", "支出金额(元)", "业务描述", "备注",
        },
    )
    validate_table_columns(
        cursor,
        "ods_tmall_alipay_fund_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "row_hash",
            "ingest_time", "账务流水号", "业务流水号", "商户订单号", "发生时间",
            "收入金额（+元）", "支出金额（-元）", "业务类型", "备注",
        },
    )

    cursor.execute(
        """SELECT COUNT(*), COUNT(DISTINCT id), COUNT(DISTINCT row_hash),
                          COUNT(DISTINCT batch_id),
                          COUNT(*) FILTER (WHERE BTRIM("入帐日期") !~ '^\\d{8}$'),
                          COUNT(*) FILTER (WHERE NULLIF(BTRIM("入帐类型"),'') IS NULL),
                          COUNT(*) FILTER (WHERE NULLIF(NULLIF(BTRIM("收入金额(元)"),''),'-') IS NOT NULL
                                               AND REPLACE(BTRIM("收入金额(元)"),',','') !~ '^-?\\d+(\\.\\d+)?$'),
                          COUNT(*) FILTER (WHERE NULLIF(NULLIF(BTRIM("支出金额(元)"),''),'-') IS NOT NULL
                                               AND REPLACE(BTRIM("支出金额(元)"),',','') !~ '^-?\\d+(\\.\\d+)?$'),
                          MIN(TO_DATE(BTRIM("入帐日期"),'YYYYMMDD')),
                          MAX(TO_DATE(BTRIM("入帐日期"),'YYYYMMDD'))
                   FROM common.v_current_tmall_aggregate_fund_raw"""
    )
    aggregate = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*), COUNT(DISTINCT id), COUNT(DISTINCT row_hash),
                          COUNT(DISTINCT batch_id),
                          COUNT(*) FILTER (WHERE NULLIF(BTRIM("发生时间"),'') IS NULL
                                               OR BTRIM("发生时间") !~ '^\\d{4}-\\d{2}-\\d{2}'),
                          COUNT(*) FILTER (WHERE NULLIF(BTRIM(REPLACE("业务类型",E'\\t','')),'') IS NULL),
                          COUNT(*) FILTER (WHERE NULLIF(NULLIF(BTRIM("收入金额（+元）"),''),'-') IS NOT NULL
                                               AND REPLACE(BTRIM("收入金额（+元）"),',','') !~ '^-?\\d+(\\.\\d+)?$'),
                          COUNT(*) FILTER (WHERE NULLIF(NULLIF(BTRIM("支出金额（-元）"),''),'-') IS NOT NULL
                                               AND REPLACE(BTRIM("支出金额（-元）"),',','') !~ '^-?\\d+(\\.\\d+)?$'),
                          MIN(NULLIF(BTRIM("发生时间"),'')::timestamp::date),
                          MAX(NULLIF(BTRIM("发生时间"),'')::timestamp::date)
                   FROM common.v_current_tmall_alipay_fund_raw"""
    )
    alipay = cursor.fetchone()
    if aggregate[0] == 0 or alipay[0] == 0:
        raise RuntimeError(f"天猫资金ODS为空：聚合={aggregate[0]}，支付宝={alipay[0]}")
    if aggregate[0] != aggregate[1] or aggregate[0] != aggregate[2]:
        raise RuntimeError(f"聚合账户资金稳定粒度重复：{aggregate[:3]}")
    if alipay[0] != alipay[1] or alipay[0] != alipay[2]:
        raise RuntimeError(f"支付宝资金稳定粒度重复：{alipay[:3]}")
    if any(aggregate[4:8]) or any(alipay[4:8]):
        raise RuntimeError(
            "天猫资金日期、业务类型或金额校验失败："
            f"aggregate={aggregate[4:8]}，alipay={alipay[4:8]}"
        )
    return {
        "aggregate_rows": aggregate[0],
        "aggregate_batches": aggregate[3],
        "aggregate_min_date": aggregate[8],
        "aggregate_max_date": aggregate[9],
        "alipay_rows": alipay[0],
        "alipay_batches": alipay[3],
        "alipay_min_date": alipay[8],
        "alipay_max_date": alipay[9],
    }


def fund_sources_available(cursor) -> bool:
    """资金ODS尚未导入时允许保留旧结算历史，不阻断整批ETL。"""
    if not table_exists(cursor, "ods.ods_tmall_aggregate_fund_raw"):
        return False
    if not table_exists(cursor, "ods.ods_tmall_alipay_fund_raw"):
        return False
    cursor.execute(
        """SELECT
             (SELECT COUNT(*) FROM ods.ods_tmall_aggregate_fund_raw),
             (SELECT COUNT(*) FROM ods.ods_tmall_alipay_fund_raw)"""
    )
    aggregate_rows, alipay_rows = cursor.fetchone()
    return bool(aggregate_rows and alipay_rows)


def validate_batch_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """WITH source_batches AS (
                 SELECT batch_id, 'ods_tmall_aggregate_fund_raw' target_table, COUNT(*) source_rows
                 FROM ods.ods_tmall_aggregate_fund_raw GROUP BY batch_id
                 UNION ALL
                 SELECT batch_id, 'ods_tmall_alipay_fund_raw', COUNT(*)
                 FROM ods.ods_tmall_alipay_fund_raw GROUP BY batch_id
             )
             SELECT b.batch_id, b.target_table, b.source_rows, COUNT(c.batch_id),
                    MAX(c.shop_code), MAX(c.shop_name), MAX(c.shop_mapping_status)
             FROM source_batches b
             LEFT JOIN common.v_ingest_batch_shop_context c
               ON c.batch_id=b.batch_id AND c.platform_code='tmall'
              AND c.target_table=b.target_table AND c.shop_mapping_status='mapped'
             GROUP BY b.batch_id,b.target_table,b.source_rows
             ORDER BY b.target_table,b.batch_id"""
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[3] != 1]
    if invalid:
        raise RuntimeError(f"天猫资金ODS存在未映射或冲突批次：{invalid}")
    return mappings


def legacy_available(cursor) -> bool:
    if not table_exists(cursor, "ods.ods_tmall_settlement_income_raw"):
        return False
    if not table_exists(cursor, "ods.ods_tmall_settlement_expense_raw"):
        return False
    cursor.execute(
        """SELECT
             (SELECT COUNT(*) FROM ods.ods_tmall_settlement_income_raw),
             (SELECT COUNT(*) FROM ods.ods_tmall_settlement_expense_raw)"""
    )
    income_rows, expense_rows = cursor.fetchone()
    return bool(income_rows and expense_rows)


def scalar(cursor, query: str, params: tuple = ()) -> Decimal:
    cursor.execute(query, params)
    return Decimal(cursor.fetchone()[0] or 0).quantize(Decimal("0.01"))


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in COMMENTED_TABLES:
        cursor.execute(
            """SELECT obj_description(c.oid,'pg_class')
               FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s""",
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """SELECT a.attname
               FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0
                 AND NOT a.attisdropped AND col_description(c.oid,a.attnum) IS NULL
               ORDER BY a.attnum""",
            (schema_name, table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{item[0]}" for item in cursor.fetchall())
    if missing:
        raise RuntimeError(f"资金结算新增对象注释不完整：{', '.join(missing)}")


def validate_pipeline(cursor, source: dict[str, object], had_legacy: bool) -> dict[str, object]:
    expected_fund_rows = int(source["aggregate_rows"]) + int(source["alipay_rows"])
    cursor.execute(
        """SELECT COUNT(*), COUNT(DISTINCT source_event_key),
                          COUNT(*) FILTER (WHERE income_eligible),
                          COUNT(*) FILTER (WHERE expense_eligible),
                          COUNT(*) FILTER (WHERE source_business_type IN ('交易退款','交易退款(售后)')),
                          ROUND(SUM(income_amount),2), ROUND(SUM(expense_amount),2),
                          ROUND(SUM(refund_amount),2)
                   FROM dwd.dwd_tmall_settlement_fund_event_detail"""
    )
    fund_dwd = cursor.fetchone()
    if fund_dwd[0] != expected_fund_rows or fund_dwd[0] != fund_dwd[1]:
        raise RuntimeError(f"资金DWD行数或唯一性异常：{fund_dwd}，预期={expected_fund_rows}")

    cursor.execute(
        """SELECT COUNT(*), ROUND(COALESCE(SUM(income_amount),0),2),
                          COALESCE(SUM(included_event_count),0)
                   FROM dws.dws_tmall_settlement_fund_income_shop_daily_type"""
    )
    fund_income_dws = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*), ROUND(COALESCE(SUM(expense_amount),0),2),
                          COALESCE(SUM(included_event_count),0)
                   FROM dws.dws_tmall_settlement_fund_expense_shop_daily_type"""
    )
    fund_expense_dws = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*), ROUND(COALESCE(SUM(income_amount),0),2),
                          ROUND(COALESCE(SUM(expense_amount),0),2),
                          ROUND(COALESCE(SUM(settlement_net_amount),0),2),
                          ROUND(COALESCE(SUM(source_settlement_amount),0),2),
                          ROUND(COALESCE(SUM(validation_difference_amount),0),2),
                          COALESCE(SUM(included_event_count),0)
                   FROM dws.dws_tmall_settlement_fund_net_shop_daily"""
    )
    fund_net_dws = cursor.fetchone()

    expected_income = scalar(
        cursor,
        """SELECT COALESCE(SUM(amount),0) FROM (
                 SELECT COALESCE(NULLIF(NULLIF(BTRIM("收入金额(元)"),''),'-')::numeric,0) amount
                 FROM common.v_current_tmall_aggregate_fund_raw WHERE BTRIM("入帐类型")='交易收款'
                 UNION ALL
                 SELECT COALESCE(NULLIF(NULLIF(BTRIM("收入金额（+元）"),''),'-')::numeric,0)
                 FROM common.v_current_tmall_alipay_fund_raw
                 WHERE BTRIM(REPLACE("业务类型",E'\\t',''))='交易付款'
             ) x""",
    )
    expected_expense = scalar(
        cursor,
        """SELECT COALESCE(SUM(expense_amount),0)
           FROM dwd.dwd_tmall_settlement_fund_event_detail
           WHERE expense_eligible""",
    )
    if Decimal(fund_income_dws[1]).quantize(Decimal("0.01")) != expected_income:
        raise RuntimeError(f"资金结算收入不一致：DWS={fund_income_dws[1]}，源收款={expected_income}")
    if Decimal(fund_expense_dws[1]).quantize(Decimal("0.01")) != expected_expense:
        raise RuntimeError(f"资金结算支出不一致：DWS={fund_expense_dws[1]}，DWD={expected_expense}")
    if Decimal(fund_net_dws[3]).quantize(Decimal("0.01")) != (
        Decimal(fund_net_dws[1]) - Decimal(fund_net_dws[2])
    ).quantize(Decimal("0.01")):
        raise RuntimeError(f"资金结算净额公式失败：{fund_net_dws}")
    if fund_net_dws[3] != fund_net_dws[4] or fund_net_dws[5] != 0:
        raise RuntimeError(f"资金结算净额源组成核验失败：{fund_net_dws}")

    # 计算旧结算表与资金表的按月覆盖结果，确认合并 DWS 没有丢历史月。
    cursor.execute(
        """WITH fund_months AS (
                 SELECT DISTINCT DATE_TRUNC('month', stat_date)::date month_start
                 FROM dwd.dwd_tmall_settlement_fund_event_detail
             ), legacy_income AS (
                 SELECT ROUND(COALESCE(SUM(order_actual_amount),0),2) amount
                 FROM dwd.dwd_tmall_settlement_income_event_detail l
                 WHERE NOT EXISTS (SELECT 1 FROM fund_months f
                                   WHERE f.month_start=DATE_TRUNC('month',l.stat_date)::date)
             ), legacy_expense AS (
                 SELECT ROUND(COALESCE(SUM(expense_amount),0),2) amount
                 FROM dwd.dwd_tmall_settlement_expense_event_detail l
                 WHERE NOT EXISTS (SELECT 1 FROM fund_months f
                                   WHERE f.month_start=DATE_TRUNC('month',l.stat_date)::date)
             ), legacy_net AS (
                 SELECT ROUND(COALESCE(SUM(settlement_net_amount),0),2) amount
                 FROM dwd.dwd_tmall_settlement_net_event_detail l
                 WHERE NOT EXISTS (SELECT 1 FROM fund_months f
                                   WHERE f.month_start=DATE_TRUNC('month',l.stat_date)::date)
             )
             SELECT
               (SELECT amount FROM legacy_income),
               (SELECT amount FROM legacy_expense),
               (SELECT amount FROM legacy_net)"""
    )
    legacy_income, legacy_expense, legacy_net = cursor.fetchone()
    expected_combined_income = (Decimal(legacy_income or 0) + Decimal(fund_income_dws[1])).quantize(Decimal("0.01"))
    expected_combined_expense = (Decimal(legacy_expense or 0) + Decimal(fund_expense_dws[1])).quantize(Decimal("0.01"))
    expected_combined_net = (expected_combined_income - expected_combined_expense).quantize(Decimal("0.01"))

    cursor.execute(
        """SELECT
             (SELECT ROUND(COALESCE(SUM(income_amount),0),2)
                FROM dws.dws_tmall_settlement_income_shop_daily_type),
             (SELECT ROUND(COALESCE(SUM(expense_amount),0),2)
                FROM dws.dws_tmall_settlement_expense_shop_daily_type),
             (SELECT ROUND(COALESCE(SUM(settlement_net_amount),0),2)
                FROM dws.dws_tmall_settlement_net_shop_daily),
             (SELECT MIN(stat_date) FROM dws.dws_tmall_settlement_net_shop_daily),
             (SELECT MAX(stat_date) FROM dws.dws_tmall_settlement_net_shop_daily)"""
    )
    combined = cursor.fetchone()
    if tuple(combined[:3]) != (expected_combined_income, expected_combined_expense, expected_combined_net):
        raise RuntimeError(
            "天猫旧结算/资金合并金额不一致："
            f"actual={combined[:3]}，expected={(expected_combined_income, expected_combined_expense, expected_combined_net)}"
        )

    cursor.execute(
        """SELECT
          (SELECT ROUND(COALESCE(SUM(income_amount),0),2)
             FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='tmall'),
          (SELECT ROUND(COALESCE(SUM(expense_amount),0),2)
             FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='tmall'),
          (SELECT ROUND(COALESCE(SUM(settlement_net_amount),0),2)
             FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='tmall'),
          (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type
             WHERE platform_code='tmall' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type
             WHERE platform_code='tmall' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily
             WHERE platform_code='tmall' AND company_code='unmapped')"""
    )
    ads = cursor.fetchone()
    if tuple(ads[:3]) != tuple(combined[:3]):
        raise RuntimeError(f"天猫资金合并DWS/ADS金额不一致：DWS={combined[:3]}，ADS={ads[:3]}")
    if any(ads[3:]):
        raise RuntimeError(f"天猫资金合并ADS未匹配公司：{ads[3:]}")

    cursor.execute(
        """SELECT COUNT(*) FROM (
                 SELECT stat_date,platform_code,company_code,shop_code
                 FROM ads.ads_settlement_net_company_shop_daily
                 WHERE platform_code='tmall'
                 GROUP BY 1,2,3,4 HAVING COUNT(*)>1
             ) duplicate_keys"""
    )
    duplicates = cursor.fetchone()[0]
    if duplicates:
        raise RuntimeError(f"天猫资金合并净额ADS主键重复：{duplicates}")

    sample_queries = (
        (
            "正常收入",
            """SELECT source_event_key,source_account_type,source_business_type,
                              stat_date,signed_amount,income_amount,expense_amount,
                              income_eligible,expense_eligible,expense_type_name
                       FROM dwd.dwd_tmall_settlement_fund_event_detail
                      WHERE income_eligible AND income_amount>0
                      ORDER BY source_id LIMIT 1""",
        ),
        (
            "退款审计（不扣收入）",
            """SELECT source_event_key,source_account_type,source_business_type,
                              stat_date,signed_amount,income_amount,expense_amount,
                              income_eligible,expense_eligible,expense_type_name
                       FROM dwd.dwd_tmall_settlement_fund_event_detail
                      WHERE refund_amount>0
                      ORDER BY source_id LIMIT 1""",
        ),
        (
            "正常平台费用",
            """SELECT source_event_key,source_account_type,source_business_type,
                              stat_date,signed_amount,income_amount,expense_amount,
                              income_eligible,expense_eligible,expense_type_name
                       FROM dwd.dwd_tmall_settlement_fund_event_detail
                      WHERE expense_eligible AND expense_amount>0
                      ORDER BY source_id LIMIT 1""",
        ),
        (
            "费用退回",
            """SELECT source_event_key,source_account_type,source_business_type,
                              stat_date,signed_amount,income_amount,expense_amount,
                              income_eligible,expense_eligible,expense_type_name
                       FROM dwd.dwd_tmall_settlement_fund_event_detail
                      WHERE expense_eligible AND expense_amount<0
                      ORDER BY source_id LIMIT 1""",
        ),
        (
            "未计入结算的资金行",
            """SELECT source_event_key,source_account_type,source_business_type,
                              stat_date,signed_amount,income_amount,expense_amount,
                              income_eligible,expense_eligible,expense_type_name
                       FROM dwd.dwd_tmall_settlement_fund_event_detail
                      WHERE NOT income_eligible AND NOT expense_eligible
                        AND signed_amount<>0
                      ORDER BY source_id LIMIT 1""",
        ),
    )
    samples = []
    missing_samples = []
    for label, query in sample_queries:
        cursor.execute(query)
        row = cursor.fetchone()
        if row is None:
            missing_samples.append(label)
        else:
            samples.append((label, row))
    if missing_samples:
        raise RuntimeError(f"天猫资金结算公式抽样场景不足：{missing_samples}")

    return {
        "fund_dwd": fund_dwd,
        "fund_income_dws": fund_income_dws,
        "fund_expense_dws": fund_expense_dws,
        "fund_net_dws": fund_net_dws,
        "legacy_amounts": (legacy_income, legacy_expense, legacy_net),
        "combined": combined,
        "ads": ads,
        "samples": samples,
        "had_legacy": had_legacy,
    }


def run_pipeline(args: argparse.Namespace) -> None:
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
            had_legacy = legacy_available(cursor)
            execute_files(cursor, LEGACY_CREATE_SQL_FILES)
            if had_legacy:
                execute_files(cursor, LEGACY_REFRESH_SQL_FILES)
            execute_files(cursor, FUND_CREATE_SQL_FILES)
            execute_files(cursor, ALL_DWS_CREATE_SQL_FILES)
            if not fund_sources_available(cursor):
                execute_files(cursor, ADS_CREATE_SQL_FILES)
                execute_files(cursor, ADS_REFRESH_SQL_FILES)
                connection.commit()
                print("天猫资金ODS尚未同时具备聚合账户和支付宝明细，已保留旧结算历史并刷新共享ADS")
                return
            source = validate_sources(cursor)
            mappings = validate_batch_mapping(cursor)
            execute_files(cursor, FUND_REFRESH_SQL_FILES)
            execute_files(cursor, COMBINE_SQL_FILES)
            execute_files(cursor, ADS_CREATE_SQL_FILES)
            execute_files(cursor, ADS_REFRESH_SQL_FILES)
            result = validate_pipeline(cursor, source, had_legacy)
            validate_comments(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(
        "天猫资金来源："
        f"聚合账户{source['aggregate_rows']}行/{source['aggregate_batches']}批 "
        f"({source['aggregate_min_date']}至{source['aggregate_max_date']})，"
        f"支付宝{source['alipay_rows']}行/{source['alipay_batches']}批 "
        f"({source['alipay_min_date']}至{source['alipay_max_date']})"
    )
    print(f"旧结算历史是否可用：{'是' if result['had_legacy'] else '否'}")
    print("批次店铺映射：")
    for row in mappings:
        print(f"  {row}")
    print(
        "资金DWD（总行数/收入候选/费用候选/退款审计行数/收入金额/费用金额/退款审计金额）："
        f"{result['fund_dwd']}"
    )
    print(f"资金DWS收入：{result['fund_income_dws']}")
    print(f"资金DWS支出：{result['fund_expense_dws']}")
    print(f"资金DWS净额：{result['fund_net_dws']}")
    print(f"旧结算历史（合并前按月保留金额）：{result['legacy_amounts']}")
    print(f"天猫合并DWS（收入/支出/净额/日期范围）：{result['combined']}")
    print(f"天猫合并ADS（收入/支出/净额/未匹配公司）：{result['ads']}")
    print("资金结算抽样：")
    for row in result["samples"]:
        print(f"  {row}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
