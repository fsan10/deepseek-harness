#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""独立刷新并验收平台与银行收入支出汇总ADS。"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIR = PROJECT_ROOT / "apps" / "fund_split_adjust" / ".vendor"
if VENDOR_DIR.is_dir():
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import psycopg2
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先安装apps/fund_split_adjust/requirements.txt") from exc


SQL_DIR = PROJECT_ROOT / "sql"
MIGRATION_SQL_FILES = [
    "ads/platform_bank_total_revenue/367_migrate_ads_platform_bank_total_revenue_company_daily_type_postgres.sql",
    "ads/platform_bank_total_revenue/365_ads_platform_bank_total_revenue_company_daily_type_postgres.sql",
]
REFRESH_SQL_FILES = [
    "ads/platform_bank_total_revenue/366_refresh_ads_platform_bank_total_revenue_company_daily_type_postgres.sql",
]
TARGET_TABLE = "ads.ads_platform_bank_total_revenue_company_daily_type"
REQUIRED_COLUMNS = {
    ("ads", "ads_platform_main_business_income_company_shop_daily_category"): {
        "stat_date", "platform_code", "platform_name", "company_code", "company_name",
        "shop_code", "primary_category_code", "primary_category_name",
        "secondary_category_code", "secondary_category_name", "source_document_type",
        "income_amount", "included_detail_count", "source_updated_at",
    },
    ("ads", "ads_platform_expense_company_shop_daily_category"): {
        "stat_date", "platform_code", "platform_name", "company_code", "company_name",
        "shop_code", "primary_category_code", "primary_category_name",
        "secondary_category_code", "secondary_category_name", "source_document_type",
        "expense_amount", "included_detail_count", "source_updated_at",
    },
    ("ads", "ads_promotion_expense_company_shop_daily"): {
        "stat_date", "platform_code", "platform_name", "company_code", "company_name",
        "shop_code", "promotion_expense_amount", "included_detail_count", "source_updated_at",
    },
    ("ads", "ads_bank_statement_company_daily_metric"): {
        "stat_date", "platform_code", "platform_name", "company_code", "company_name",
        "metric_group_code", "metric_code", "metric_name", "metric_amount",
        "included_detail_count", "source_updated_at",
    },
}
EXPECTED = {
    "rows": 3972,
    "date_from": "2026-01-02",
    "date_to": "2026-07-23",
    "income": Decimal("6302004.28"),
    "expense": Decimal("2556938.27"),
    "surplus": Decimal("3745066.01"),
    "expense_ratio": Decimal("0.405734"),
    "roi": Decimal("2.464668"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新平台与银行收入支出汇总ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="强制校验2026-08-03确认的当前行数、日期范围和五项指标基准。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_required_objects(cursor) -> None:
    for (schema_name, table_name), required in REQUIRED_COLUMNS.items():
        cursor.execute("SELECT to_regclass(%s)", (f"{schema_name}.{table_name}",))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少来源对象：{schema_name}.{table_name}")
        cursor.execute(
            """SELECT column_name
               FROM information_schema.columns
               WHERE table_schema=%s AND table_name=%s""",
            (schema_name, table_name),
        )
        missing = sorted(required - {row[0] for row in cursor.fetchall()})
        if missing:
            raise RuntimeError(f"{schema_name}.{table_name}缺少必需字段：{', '.join(missing)}")


def source_profiles(cursor) -> dict[str, tuple[object, ...]]:
    profiles = {}
    specs = {
        "ads_platform_main_business_income_company_shop_daily_category": "income_amount",
        "ads_platform_expense_company_shop_daily_category": "expense_amount",
        "ads_promotion_expense_company_shop_daily": "promotion_expense_amount",
        "ads_bank_statement_company_daily_metric": "metric_amount",
    }
    for table_name, amount_column in specs.items():
        cursor.execute(
            f"""SELECT COUNT(*),MIN(stat_date),MAX(stat_date),
                       COALESCE(ROUND(SUM({amount_column}),2),0),
                       COUNT(*) FILTER (WHERE company_code='unmapped')
                FROM ads.{table_name}"""
        )
        profile = cursor.fetchone()
        if profile[0] == 0:
            print(f"[WARN] 来源表ads.{table_name}为空，按0值纳入平台/银行汇总")
        if profile[4]:
            raise RuntimeError(f"来源表ads.{table_name}存在{profile[4]}行未匹配公司")
        profiles[table_name] = profile
    return profiles


def validate_comments(cursor) -> None:
    cursor.execute(
        """SELECT obj_description(c.oid,'pg_class')
           FROM pg_class c
           JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='ads'
             AND c.relname='ads_platform_bank_total_revenue_company_daily_type'"""
    )
    if not cursor.fetchone()[0]:
        raise RuntimeError("汇总ADS缺少表注释")
    cursor.execute(
        """SELECT a.attname
           FROM pg_attribute a
           JOIN pg_class c ON c.oid=a.attrelid
           JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='ads'
             AND c.relname='ads_platform_bank_total_revenue_company_daily_type'
             AND a.attnum>0 AND NOT a.attisdropped
             AND col_description(c.oid,a.attnum) IS NULL
           ORDER BY a.attnum"""
    )
    missing = [row[0] for row in cursor.fetchall()]
    if missing:
        raise RuntimeError(f"汇总ADS字段注释不完整：{', '.join(missing)}")


def validate_lineage(cursor) -> int:
    cursor.execute(
        """WITH source_union AS (
             SELECT stat_date,'platform'::text source_type_code,platform_code,company_code,
                    'income'::text financial_direction_code,
                    'platform_main_business_income'::text metric_group_code,
                    primary_category_code,secondary_category_code,source_document_type,
                    'ads_platform_main_business_income_company_shop_daily_category'::text source_table_code,
                    income_amount metric_amount,included_detail_count
             FROM ads.ads_platform_main_business_income_company_shop_daily_category
             UNION ALL
             SELECT stat_date,'platform',platform_code,company_code,'expense','platform_expense',
                    primary_category_code,secondary_category_code,source_document_type,
                    'ads_platform_expense_company_shop_daily_category',expense_amount,included_detail_count
             FROM ads.ads_platform_expense_company_shop_daily_category
             UNION ALL
             SELECT stat_date,'platform',platform_code,company_code,'expense','independent_promotion_expense',
                    'independent_promotion_expense','all','promotion_account',
                    'ads_promotion_expense_company_shop_daily',promotion_expense_amount,included_detail_count
             FROM ads.ads_promotion_expense_company_shop_daily
             UNION ALL
             SELECT stat_date,'bank','bank',company_code,
                    CASE WHEN metric_group_code='revenue' THEN 'income' ELSE 'expense' END,
                    CASE metric_group_code WHEN 'revenue' THEN 'bank_income'
                         WHEN 'expense' THEN 'bank_expense' WHEN 'cost' THEN 'bank_cost' END,
                    metric_code,'all','bank_statement','ads_bank_statement_company_daily_metric',
                    metric_amount,included_detail_count
             FROM ads.ads_bank_statement_company_daily_metric
           ), expected AS (
             SELECT stat_date,source_type_code,platform_code,company_code,financial_direction_code,
                    metric_group_code,primary_category_code,secondary_category_code,source_document_type,
                    MAX(source_table_code) source_table_code,ROUND(SUM(metric_amount),2) metric_amount,
                    SUM(included_detail_count) included_detail_count
             FROM source_union
             GROUP BY 1,2,3,4,5,6,7,8,9
           ), actual AS (
             SELECT stat_date,source_type_code,platform_code,company_code,financial_direction_code,
                    metric_group_code,primary_category_code,secondary_category_code,source_document_type,
                    source_table_code,metric_amount,included_detail_count
             FROM ads.ads_platform_bank_total_revenue_company_daily_type
           )
           SELECT COUNT(*)
           FROM (
             (SELECT * FROM expected EXCEPT SELECT * FROM actual)
             UNION ALL
             (SELECT * FROM actual EXCEPT SELECT * FROM expected)
           ) difference"""
    )
    return cursor.fetchone()[0]


def validate_card_sql(cursor, date_from, date_to) -> dict[str, object]:
    cursor.execute(
        """SELECT ARRAY_AGG(DISTINCT company_code ORDER BY company_code)
           FROM ads.ads_platform_bank_total_revenue_company_daily_type"""
    )
    company_codes = cursor.fetchone()[0]
    params = (date_from, date_to, company_codes)
    filter_sql = "stat_date >= %s AND stat_date <= %s AND company_code = ANY(%s)"
    queries = {
        "income": f"""SELECT ROUND(COALESCE(SUM(metric_amount),0),2)
                        FROM {TARGET_TABLE}
                        WHERE financial_direction_code='income' AND {filter_sql}""",
        "expense": f"""SELECT ROUND(COALESCE(SUM(metric_amount),0),2)
                         FROM {TARGET_TABLE}
                         WHERE financial_direction_code='expense' AND {filter_sql}""",
        "surplus": f"""SELECT ROUND(
                            COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code='income'),0)
                            - COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code='expense'),0),2)
                          FROM {TARGET_TABLE} WHERE {filter_sql}""",
        "expense_ratio": f"""SELECT ROUND(
                                 COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code='expense'),0)
                                 / NULLIF(COALESCE(SUM(metric_amount) FILTER (
                                     WHERE financial_direction_code='income'),0),0),6)
                               FROM {TARGET_TABLE} WHERE {filter_sql}""",
        "roi": f"""SELECT ROUND(
                       COALESCE(SUM(metric_amount) FILTER (WHERE financial_direction_code='income'),0)
                       / NULLIF(COALESCE(SUM(metric_amount) FILTER (
                           WHERE financial_direction_code='expense'),0),0),6)
                     FROM {TARGET_TABLE} WHERE {filter_sql}""",
    }
    cards = {}
    for name, query in queries.items():
        cursor.execute(query, params)
        cards[name] = cursor.fetchone()[0]

    if cards["income"] - cards["expense"] != cards["surplus"]:
        raise RuntimeError(f"指标卡公式不平：{cards}")

    cursor.execute(
        f"""SELECT financial_direction_code,ROUND(SUM(category_amount),2)
            FROM (
              SELECT financial_direction_code,primary_category_name,SUM(metric_amount) category_amount
              FROM {TARGET_TABLE}
              WHERE {filter_sql}
              GROUP BY financial_direction_code,primary_category_name
            ) category_totals
            GROUP BY financial_direction_code""",
        params,
    )
    composition_totals = dict(cursor.fetchall())
    if composition_totals.get("income", Decimal("0.00")) != cards["income"]:
        raise RuntimeError(f"收入构成图与总收入卡不平：{composition_totals}/{cards}")
    if composition_totals.get("expense", Decimal("0.00")) != cards["expense"]:
        raise RuntimeError(f"支出构成图与总支出卡不平：{composition_totals}/{cards}")
    return {
        "date_range": (date_from, date_to),
        "company_codes": company_codes,
        "cards": cards,
        "composition_totals": composition_totals,
    }


def validate_result(cursor, enforce_baseline: bool) -> dict[str, object]:
    cursor.execute(
        """SELECT COUNT(*),MIN(stat_date),MAX(stat_date),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_platform_bank_total_revenue_company_daily_type"""
    )
    row_count, date_from, date_to, unmapped = cursor.fetchone()
    if unmapped:
        raise RuntimeError(f"汇总ADS存在{unmapped}行未匹配公司")

    cursor.execute(
        """SELECT COUNT(*) FROM (
             SELECT stat_date,source_type_code,platform_code,company_code,
                    financial_direction_code,metric_group_code,primary_category_code,
                    secondary_category_code,source_document_type
             FROM ads.ads_platform_bank_total_revenue_company_daily_type
             GROUP BY 1,2,3,4,5,6,7,8,9 HAVING COUNT(*)>1
           ) duplicate_keys"""
    )
    duplicate_keys = cursor.fetchone()[0]
    if duplicate_keys:
        raise RuntimeError(f"汇总ADS存在{duplicate_keys}组重复最终粒度")

    cursor.execute(
        """SELECT financial_direction_code,COALESCE(ROUND(SUM(metric_amount),2),0)
           FROM ads.ads_platform_bank_total_revenue_company_daily_type
           GROUP BY financial_direction_code ORDER BY financial_direction_code"""
    )
    direction_totals = dict(cursor.fetchall())
    income = direction_totals.get("income", Decimal("0.00"))
    expense = direction_totals.get("expense", Decimal("0.00"))
    surplus = income - expense
    expense_ratio = None if income == 0 else (expense / income).quantize(Decimal("0.000001"))
    roi = None if expense == 0 else (income / expense).quantize(Decimal("0.000001"))

    cursor.execute(
        """SELECT source_table_code,financial_direction_code,
                  COALESCE(ROUND(SUM(metric_amount),2),0),COUNT(*)
           FROM ads.ads_platform_bank_total_revenue_company_daily_type
           GROUP BY source_table_code,financial_direction_code
           ORDER BY source_table_code,financial_direction_code"""
    )
    source_totals = cursor.fetchall()

    lineage_difference = validate_lineage(cursor)
    if lineage_difference:
        raise RuntimeError(f"四来源与汇总ADS双向逐粒度差异为{lineage_difference}")
    card_validation = validate_card_sql(cursor, date_from, date_to)

    if enforce_baseline:
        actual = {
            "rows": row_count,
            "date_from": str(date_from),
            "date_to": str(date_to),
            "income": income,
            "expense": expense,
            "surplus": surplus,
            "expense_ratio": expense_ratio,
            "roi": roi,
        }
        differences = {
            key: (actual[key], expected)
            for key, expected in EXPECTED.items()
            if actual[key] != expected
        }
        if differences:
            raise RuntimeError(f"当前确认基准发生变化：{differences}")

    return {
        "rows": row_count,
        "date_range": (date_from, date_to),
        "direction_totals": direction_totals,
        "surplus": surplus,
        "expense_ratio": expense_ratio,
        "roi": roi,
        "source_totals": source_totals,
        "unmapped": unmapped,
        "duplicate_keys": duplicate_keys,
        "lineage_difference": lineage_difference,
        "card_validation": card_validation,
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
            validate_required_objects(cursor)
            profiles = source_profiles(cursor)
            execute_files(cursor, MIGRATION_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_result(cursor, args.enforce_current_baseline)
            validate_comments(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print("四张来源ADS（行数/日期范围/金额/未匹配公司）：")
    for table_name, profile in profiles.items():
        print(f"  ads.{table_name}: {profile[0]}行，{profile[1]} 至 {profile[2]}，{profile[3]:.2f}元，{profile[4]}行")
    print(f"汇总ADS：{result['rows']}行，{result['date_range'][0]} 至 {result['date_range'][1]}")
    print(f"总收入：{result['direction_totals'].get('income', Decimal('0.00')):.2f}")
    print(f"总支出：{result['direction_totals'].get('expense', Decimal('0.00')):.2f}")
    print(f"经营结余：{result['surplus']:.2f}")
    print(f"支出率：{result['expense_ratio']:.6%}" if result["expense_ratio"] is not None else "支出率：NULL")
    print(f"ROI：{result['roi']:.6f}倍" if result["roi"] is not None else "ROI：NULL")
    print("来源方向汇总（来源表/方向/金额/汇总行数）：")
    for source_total in result["source_totals"]:
        print(f"  {source_total}")
    print(f"未匹配公司/重复主键/四来源双向差异：{result['unmapped']}/{result['duplicate_keys']}/{result['lineage_difference']}")
    print(
        "同日期和公司参数的五张指标卡："
        f"{result['card_validation']['cards']}"
    )
    print(f"收入/支出构成图汇总：{result['card_validation']['composition_totals']}")
    print(f"当前基准强制校验：{'已启用' if args.enforce_current_baseline else '未启用'}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
