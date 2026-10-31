#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""兼容入口：刷新抖音、快手主营收入并执行共享 ADS 校验。

生产任务已经拆分为三个入口：
``run_douyin_main_business_income_etl.py``、
``run_ks_main_business_income_etl.py`` 和
``run_platform_main_business_income_shared_ads_etl.py``。
本文件保留旧命令行入口，避免历史任务或人工脚本失效。
"""

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
]
CREATE_SQL_FILES = [
    "douyin/main_business_income/353_dwd_douyin_main_business_income_source_detail_postgres.sql",
    "douyin/main_business_income/354_dws_douyin_main_business_income_shop_daily_category_postgres.sql",
    "ks/main_business_income/357_dwd_ks_main_business_income_source_detail_postgres.sql",
    "ks/main_business_income/358_dws_ks_main_business_income_shop_daily_category_postgres.sql",
    "ads/main_business_income/325_ads_platform_main_business_income_company_shop_daily_category_postgres.sql",
]
REFRESH_SQL_FILES = [
    "douyin/main_business_income/355_refresh_dwd_douyin_main_business_income_source_detail_postgres.sql",
    "douyin/main_business_income/356_refresh_dws_douyin_main_business_income_shop_daily_category_postgres.sql",
    "ks/main_business_income/359_refresh_dwd_ks_main_business_income_source_detail_postgres.sql",
    "ks/main_business_income/360_refresh_dws_ks_main_business_income_shop_daily_category_postgres.sql",
    "ads/main_business_income/328_refresh_ads_platform_main_business_income_company_shop_daily_category_postgres.sql",
]

DOUYIN_CREATE_SQL_FILES = CREATE_SQL_FILES[:2]
DOUYIN_REFRESH_SQL_FILES = REFRESH_SQL_FILES[:2]
KS_CREATE_SQL_FILES = CREATE_SQL_FILES[2:4]
KS_REFRESH_SQL_FILES = REFRESH_SQL_FILES[2:4]
SHARED_CREATE_SQL_FILES = [CREATE_SQL_FILES[4]]
SHARED_REFRESH_SQL_FILES = [REFRESH_SQL_FILES[4]]

ODS_TABLES = {
    "ods_douyin_settlement_raw": {
        "id",
        "batch_id",
        "source_file_name",
        "source_row_no",
        "row_hash",
        "ingest_time",
        "结算时间",
        "订单号",
        "子订单号",
        "结算单类型",
        "有结算前退款",
        "用户实付",
        "平台补贴",
        "其他平台补贴",
        "政府补贴平台垫资",
        "达人补贴",
        "抖音支付补贴",
        "抖音月付营销补贴",
        "银行补贴",
        "以旧换新抵扣",
        "平台补贴运费",
        "收入合计",
    },
    "ods_ks_settlement_raw": {
        "id",
        "batch_id",
        "source_file_name",
        "source_row_no",
        "row_hash",
        "ingest_time",
        "订单号",
        "订单实付(元)",
        "政府补贴",
        "支付营销补贴",
        "平台补贴",
        "达人补贴",
        "商家补贴(元)",
        "合计收入(元)",
        "订单退款(元)",
        "实际结算时间",
    },
    "ods_ks_fund_raw": {
        "id",
        "batch_id",
        "source_file_name",
        "source_row_no",
        "row_hash",
        "ingest_time",
        "账务流水号",
        "关联业务单号",
        "入账时间",
        "账务方向",
        "发生额（元）",
        "业务类型",
        "描述",
    },
}

COMMENTED_TABLES = [
    ("dwd", "dwd_douyin_main_business_income_source_detail"),
    ("dws", "dws_douyin_main_business_income_shop_daily_category"),
    ("dwd", "dwd_ks_main_business_income_source_detail"),
    ("dws", "dws_ks_main_business_income_shop_daily_category"),
    ("ads", "ads_platform_main_business_income_company_shop_daily_category"),
]

CURRENT_BASELINE = {
    "douyin": {
        "2026-04-01": {
            "product_sales_income": Decimal("1754186.34"),
            "platform_subsidy": Decimal("481940.78"),
            "sales_refund": Decimal("-41529.37"),
            "total": Decimal("2194597.75"),
        },
        "2026-05-01": {
            "product_sales_income": Decimal("1808102.65"),
            "platform_subsidy": Decimal("511498.84"),
            "sales_refund": Decimal("-52030.58"),
            "total": Decimal("2267570.91"),
        },
        "2026-06-01": {
            "product_sales_income": Decimal("709888.78"),
            "platform_subsidy": Decimal("10071.67"),
            "sales_refund": Decimal("-14230.69"),
            "total": Decimal("705729.76"),
        },
    },
    "ks": {
        "2026-05-01": Decimal("141013.49"),
        "2026-06-01": Decimal("200193.49"),
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="刷新抖音、快手主营业务收入并接入七平台共享ADS。"
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="强制校验当前抖音4至6月、快手5至6月专项基准。",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="兼容旧调用；共享ADS默认允许平台来源为空，并只汇总当前已有数据。",
    )
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    from etl.platform_finance.operating_treatment import execute_finance_files
    execute_finance_files(cursor, file_names)


def validate_ods(cursor, scope: str = "legacy") -> dict[str, int]:
    scope_tables = {
        "douyin": {"ods_douyin_settlement_raw"},
        "ks": {"ods_ks_settlement_raw", "ods_ks_fund_raw"},
        "legacy": set(ODS_TABLES),
    }
    if scope not in scope_tables:
        raise ValueError(f"不支持的主营收入ETL范围：{scope}")
    result: dict[str, int] = {}
    for table_name, required_columns in ODS_TABLES.items():
        if table_name not in scope_tables[scope]:
            continue
        cursor.execute("SELECT to_regclass(%s)", (f"ods.{table_name}",))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少来源表ods.{table_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='ods' AND table_name=%s
            """,
            (table_name,),
        )
        actual_columns = {row[0] for row in cursor.fetchall()}
        missing = sorted(required_columns - actual_columns)
        if missing:
            raise RuntimeError(f"ods.{table_name}缺少必需字段：{missing}")
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*),COUNT(DISTINCT id),COUNT(DISTINCT row_hash) "
                "FROM ods.{}"
            ).format(sql.Identifier(table_name))
        )
        row_count, unique_ids, unique_hashes = cursor.fetchone()
        if row_count == 0 or row_count != unique_ids or row_count != unique_hashes:
            raise RuntimeError(
                f"ods.{table_name}粒度异常："
                f"rows={row_count},ids={unique_ids},hashes={unique_hashes}"
            )
        from etl.common.finance_sources import prepare_finance_sources, effective_count
        platform = "douyin" if table_name.startswith("ods_douyin_") else "ks"
        prepare_finance_sources(cursor, platform, include_fund=platform != "douyin")
        result[table_name] = effective_count(cursor, table_name)
    return result


def validate_batch_mapping(cursor, scope: str = "legacy") -> list[tuple]:
    specs = [
        ("douyin", "ods_douyin_settlement_raw"),
        ("ks", "ods_ks_settlement_raw"),
        ("ks", "ods_ks_fund_raw"),
    ]
    if scope == "douyin":
        specs = specs[:1]
    elif scope == "ks":
        specs = specs[1:]
    elif scope != "legacy":
        raise ValueError(f"不支持的批次映射ETL范围：{scope}")
    result: list[tuple] = []
    for platform_code, table_name in specs:
        cursor.execute(
            sql.SQL(
                """
                WITH source_batch AS (
                  SELECT batch_id,COUNT(*) source_rows
                  FROM ods.{}
                  GROUP BY batch_id
                )
                SELECT b.batch_id,b.source_rows,COUNT(c.batch_id),
                       MAX(c.shop_code),MAX(c.shop_name),
                       MAX(c.shop_mapping_status)
                FROM source_batch b
                LEFT JOIN common.v_ingest_batch_shop_context c
                  ON c.batch_id=b.batch_id
                 AND c.platform_code=%s
                 AND c.target_table=%s
                 AND c.shop_mapping_status='mapped'
                GROUP BY b.batch_id,b.source_rows
                ORDER BY b.batch_id
                """
            ).format(sql.Identifier(table_name)),
            (platform_code, table_name),
        )
        rows = cursor.fetchall()
        invalid = [row for row in rows if row[0] is None or row[2] != 1]
        if invalid:
            raise RuntimeError(
                f"{platform_code}/{table_name}存在未映射或冲突批次：{invalid}"
            )
        result.extend((platform_code, table_name, *row) for row in rows)
    return result


def validate_shared_dependencies(cursor) -> None:
    tables = [
        "dws_jd_main_business_income_shop_daily_category",
        "dws_tmall_main_business_income_shop_daily_category",
        "dws_pdd_main_business_income_shop_daily_category",
        "dws_wechat_channels_main_business_income_shop_daily_category",
        "dws_xhs_main_business_income_shop_daily_category",
    ]
    missing: list[str] = []
    for table_name in tables:
        cursor.execute("SELECT to_regclass(%s)", (f"dws.{table_name}",))
        if cursor.fetchone()[0] is None:
            missing.append(f"dws.{table_name}")
    if missing:
        raise RuntimeError(f"共享ADS依赖缺失：{missing}")


def validate_comments(cursor, scope: str = "legacy") -> None:
    allowed_tables = {
        "douyin": COMMENTED_TABLES[:2],
        "ks": COMMENTED_TABLES[2:4],
        "shared": COMMENTED_TABLES[4:],
        "legacy": COMMENTED_TABLES,
    }
    if scope not in allowed_tables:
        raise ValueError(f"不支持的注释校验ETL范围：{scope}")
    missing: list[str] = []
    for schema_name, table_name in allowed_tables[scope]:
        cursor.execute(
            """
            SELECT obj_description(c.oid,'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
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
            JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s
              AND a.attnum>0 AND NOT a.attisdropped
              AND col_description(c.oid,a.attnum) IS NULL
            """,
            (schema_name, table_name),
        )
        missing.extend(
            f"{schema_name}.{table_name}.{row[0]}" for row in cursor.fetchall()
        )
    if missing:
        raise RuntimeError(f"新增表或字段缺少注释：{missing}")


def as_money(value: object) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def validate_dwd(cursor, ods_rows: dict[str, int], scope: str = "legacy") -> dict[str, tuple]:
    if scope not in {"douyin", "ks", "legacy"}:
        raise ValueError(f"共享 ADS 范围不应执行 DWD 校验：{scope}")
    result: dict[str, tuple] = {}
    if scope in {"douyin", "legacy"}:
        cursor.execute(
        """
        SELECT COUNT(*),COUNT(DISTINCT source_id),
               MIN(stat_date),MAX(stat_date),
               COALESCE(SUM(reconciliation_difference),0),
               COUNT(*) FILTER (WHERE reconciliation_difference<>0)
        FROM dwd.dwd_douyin_main_business_income_source_detail
        """
    )
        douyin = cursor.fetchone()
        if douyin[0] != ods_rows["ods_douyin_settlement_raw"] or douyin[0] != douyin[1]:
            raise RuntimeError(f"抖音DWD粒度异常：{douyin}")
        if as_money(douyin[4]) != Decimal("0.00") or douyin[5] != 0:
            raise RuntimeError(f"抖音收入组成逐行核验失败：{douyin}")
        result["douyin"] = douyin

    if scope in {"ks", "legacy"}:
        cursor.execute(
        """
        SELECT source_document_type,COUNT(*),COUNT(DISTINCT source_id),
               MIN(stat_date),MAX(stat_date)
        FROM dwd.dwd_ks_main_business_income_source_detail
        GROUP BY source_document_type
        ORDER BY source_document_type
        """
    )
        ks_rows = cursor.fetchall()
        ks_by_type = {row[0]: row for row in ks_rows}
        if ks_by_type["settlement"][1] != ods_rows["ods_ks_settlement_raw"]:
            raise RuntimeError(f"快手结算DWD行数异常：{ks_by_type['settlement']}")
        if ks_by_type["fund"][1] != ods_rows["ods_ks_fund_raw"]:
            raise RuntimeError(f"快手资金DWD行数异常：{ks_by_type['fund']}")
        if any(row[1] != row[2] for row in ks_rows):
            raise RuntimeError(f"快手DWD最小粒度不唯一：{ks_rows}")
        result["ks"] = tuple(ks_rows)
    return result


def validate_platform_dws(cursor, platform_code: str) -> tuple:
    table_name = {
        "douyin": "dws_douyin_main_business_income_shop_daily_category",
        "ks": "dws_ks_main_business_income_shop_daily_category",
    }.get(platform_code)
    if not table_name:
        raise ValueError(f"不支持的平台DWS校验：{platform_code}")
    cursor.execute(
        sql.SQL(
            """
            SELECT COUNT(*),
                   COUNT(DISTINCT (stat_date,shop_code,primary_category_code,
                                   secondary_category_code,source_document_type)),
                   COALESCE(SUM(income_amount),0),
                   MIN(stat_date),MAX(stat_date)
            FROM dws.{}
            """
        ).format(sql.Identifier(table_name))
    )
    result = cursor.fetchone()
    if result[0] == 0 or result[0] != result[1]:
        raise RuntimeError(f"{platform_code} DWS粒度异常：{result}")
    return result


def validate_dws_ads(cursor, *, require_all_platforms: bool = False) -> dict[str, tuple]:
    from etl.platform_finance.operating_treatment import PLATFORMS, validate_projection
    result = {platform: validate_projection(cursor,platform) for platform in PLATFORMS}

    cursor.execute(
        """
        SELECT COUNT(*) FILTER (WHERE company_code='unmapped'),
               COUNT(DISTINCT platform_code),
               COUNT(*),
               MIN(stat_date),MAX(stat_date)
        FROM ads.ads_platform_main_business_income_company_shop_daily_category
        """
    )
    shared = cursor.fetchone()
    if shared[0] != 0 or shared[1] != 7:
        cursor.execute(
            """
            SELECT platform_code, COUNT(*)
            FROM ads.ads_platform_main_business_income_company_shop_daily_category
            GROUP BY platform_code
            ORDER BY platform_code
            """
        )
        platform_counts = cursor.fetchall()
        if shared[0] != 0:
            raise RuntimeError(
                "共享主营收入ADS公司或平台覆盖异常："
                f"summary={shared}，platform_counts={platform_counts}"
            )
        if require_all_platforms:
            validate_shared_dependencies(cursor)
        print(
            "共享主营收入ADS未输出空值或全部不计入的平台："
            f"{platform_counts}"
        )
    result["shared"] = shared
    return result


def validate_reconciliation(cursor, scope: str = "legacy") -> dict[str, object]:
    if scope not in {"douyin", "ks", "legacy"}:
        raise ValueError(f"不支持的收入勾稽范围：{scope}")
    result: dict[str, Decimal] = {}
    if scope in {"douyin", "legacy"}:
        cursor.execute(
            """
            SELECT COALESCE(SUM(source_income_amount),0),
                   COALESCE(SUM(component_income_amount),0)
            FROM dwd.dwd_douyin_main_business_income_source_detail
            """
        )
        douyin_source, douyin_components = map(as_money, cursor.fetchone())
        cursor.execute(
            """
            SELECT COALESCE(SUM(income_amount),0)
            FROM dws.dws_douyin_main_business_income_shop_daily_category
            """
        )
        douyin_dws = as_money(cursor.fetchone()[0])
        if not (douyin_source == douyin_components == douyin_dws):
            raise RuntimeError(
                "抖音收入勾稽失败："
                f"source={douyin_source},components={douyin_components},dws={douyin_dws}"
            )
        result["douyin"] = douyin_dws

    if scope in {"ks", "legacy"}:
        cursor.execute(
            """
            SELECT COALESCE(SUM(settlement_formula_income_amount),0)
            FROM dwd.dwd_ks_main_business_income_source_detail
            WHERE source_document_type='settlement'
            """
        )
        ks_settlement = as_money(cursor.fetchone()[0])
        cursor.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(signed_fund_amount),0)
            FROM dwd.dwd_ks_main_business_income_source_detail d
            WHERE d.source_document_type='fund'
              AND d.source_direction='支'
              AND d.source_business_type='资金扣减'
              AND d.source_description='快手小店退款'
              AND d.related_order_no IS NOT NULL
              AND d.signed_fund_amount < 0
              AND NOT EXISTS (
                SELECT 1
                FROM dwd.dwd_ks_main_business_income_source_detail settlement
                WHERE settlement.source_document_type='settlement'
                  AND settlement.order_no=d.related_order_no
                  AND settlement.shop_identity_key=d.shop_identity_key
                  AND settlement.order_refund_amount>0
              )
            """
        )
        expected_fund_count, expected_fund = cursor.fetchone()
        expected_fund = as_money(expected_fund)
        cursor.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(included_detail_count),0),
                   COALESCE(SUM(income_amount),0)
            FROM dws.dws_ks_main_business_income_shop_daily_category
            WHERE source_document_type='fund'
            """
        )
        ks_fund_rows, ks_fund_count, ks_fund = cursor.fetchone()
        ks_fund = as_money(ks_fund)
        cursor.execute(
            """
            SELECT COALESCE(SUM(income_amount),0)
            FROM dws.dws_ks_main_business_income_shop_daily_category
            """
        )
        ks_dws = as_money(cursor.fetchone()[0])
        if ks_fund_count != expected_fund_count or ks_fund != expected_fund:
            raise RuntimeError(
                "快手资金补充退款与DWD规则不一致："
                f"dwd={expected_fund_count}/{expected_fund}，"
                f"dws_details={ks_fund_count}，dws_amount={ks_fund}"
            )
        if ks_settlement + ks_fund != ks_dws:
            raise RuntimeError(
                "快手收入勾稽失败："
                f"settlement={ks_settlement},fund={ks_fund},dws={ks_dws}"
            )

        cursor.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(signed_fund_amount),0)
            FROM dwd.dwd_ks_main_business_income_source_detail
            WHERE source_document_type='fund'
              AND source_business_type='结算后退款'
              AND source_description='退现金金额'
              AND related_order_no IN (
                SELECT order_no
                FROM dwd.dwd_ks_main_business_income_source_detail
                WHERE source_document_type='settlement'
                  AND order_refund_amount>0
              )
            """
        )
        duplicate_count, duplicate_amount = cursor.fetchone()
        duplicate_amount = as_money(duplicate_amount)

        cursor.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(income_amount),0)
            FROM dws.dws_ks_main_business_income_shop_daily_category
            WHERE source_document_type='fund'
              AND secondary_category_name='结算后退款 + 退现金金额'
            """
        )
        duplicate_dws_rows, duplicate_dws_amount = cursor.fetchone()
        duplicate_dws_amount = as_money(duplicate_dws_amount)
        if duplicate_dws_rows or duplicate_dws_amount != Decimal("0.00"):
            raise RuntimeError(
                "快手已结算退款被重复计入主营收入："
                f"rows={duplicate_dws_rows},amount={duplicate_dws_amount}"
            )
        result.update(
            {
                "ks_settlement": ks_settlement,
                "ks_supplemental_refund": ks_fund,
                "ks_supplemental_refund_rows": ks_fund_count,
                "ks_supplemental_refund_dws_rows": ks_fund_rows,
                "ks_total": ks_dws,
                "ks_excluded_duplicate_refund": duplicate_amount,
                "ks_excluded_duplicate_refund_rows": duplicate_count,
            }
        )
    return result


def validate_baseline(cursor) -> dict[str, object]:
    actual: dict[str, object] = {}
    douyin_actual: dict[str, dict[str, Decimal]] = {}
    for month, expected in CURRENT_BASELINE["douyin"].items():
        cursor.execute(
            """
            SELECT primary_category_code,COALESCE(SUM(income_amount),0)
            FROM ads.ads_platform_main_business_income_company_shop_daily_category
            WHERE platform_code='douyin'
              AND stat_date>=DATE %s
              AND stat_date<(DATE %s + INTERVAL '1 month')
            GROUP BY primary_category_code
            """,
            (month, month),
        )
        categories = {row[0]: as_money(row[1]) for row in cursor.fetchall()}
        categories["total"] = sum(
            (amount for code, amount in categories.items() if code != "total"),
            Decimal("0.00"),
        )
        if categories != expected:
            raise RuntimeError(
                f"抖音{month}基准不一致：{categories} != {expected}"
            )
        douyin_actual[month] = categories
    actual["douyin"] = douyin_actual

    ks_actual: dict[str, Decimal] = {}
    for month, expected in CURRENT_BASELINE["ks"].items():
        cursor.execute(
            """
            SELECT COALESCE(SUM(income_amount),0)
            FROM ads.ads_platform_main_business_income_company_shop_daily_category
            WHERE platform_code='ks'
              AND stat_date>=DATE %s
              AND stat_date<(DATE %s + INTERVAL '1 month')
            """,
            (month, month),
        )
        amount = as_money(cursor.fetchone()[0])
        if amount != expected:
            raise RuntimeError(
                f"快手{month}基准不一致：{amount} != {expected}"
            )
        ks_actual[month] = amount
    actual["ks"] = ks_actual
    return actual


def sample_rows(cursor) -> list[tuple]:
    cursor.execute(
        """
        (SELECT '抖音正常收入' sample_type,settlement_type,
                order_no,user_payment_amount,source_income_amount
         FROM dwd.dwd_douyin_main_business_income_source_detail
         WHERE user_payment_amount>0
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '抖音结算后退款',settlement_type,
                order_no,user_payment_amount,source_income_amount
         FROM dwd.dwd_douyin_main_business_income_source_detail
         WHERE settlement_type LIKE '结算后退款%'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '快手结算退款',source_document_type,
                order_no,-order_refund_amount,settlement_formula_income_amount
         FROM dwd.dwd_ks_main_business_income_source_detail
         WHERE source_document_type='settlement' AND order_refund_amount>0
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '快手超售后补充退款',source_business_type,
                related_order_no,signed_fund_amount,signed_fund_amount
         FROM dwd.dwd_ks_main_business_income_source_detail
         WHERE source_document_type='fund'
           AND source_business_type='资金扣减'
           AND source_description='快手小店退款'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '快手重复退款勾稽',source_business_type,
                related_order_no,signed_fund_amount,signed_fund_amount
         FROM dwd.dwd_ks_main_business_income_source_detail
         WHERE source_document_type='fund'
           AND source_business_type='结算后退款'
         ORDER BY source_id LIMIT 1)
        """
    )
    return cursor.fetchall()


def run_pipeline(args, scope: str = "legacy") -> None:
    if scope not in {"douyin", "ks", "shared", "legacy"}:
        raise ValueError(f"不支持的主营收入ETL范围：{scope}")
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
            if scope == "shared":
                validate_shared_dependencies(cursor)
                execute_files(cursor, SHARED_CREATE_SQL_FILES)
                execute_files(cursor, SHARED_REFRESH_SQL_FILES)
                validate_comments(cursor, "shared")
                # 空平台表示该平台当前没有店铺/来源，是合法的 0 值；共享 ADS
                # 只校验已有 DWS 与共享结果一致，不再要求七个平台同时有数据。
                dws_ads_result = validate_dws_ads(cursor, require_all_platforms=False)
                print("七平台共享主营收入 ADS 刷新并校验成功")
                print(f"共享 ADS：{dws_ads_result['shared']}")
            else:
                ods_rows = validate_ods(cursor, scope)
                batch_mappings = validate_batch_mapping(cursor, scope)
                if scope == "douyin":
                    create_files = DOUYIN_CREATE_SQL_FILES
                    refresh_files = DOUYIN_REFRESH_SQL_FILES
                elif scope == "ks":
                    create_files = KS_CREATE_SQL_FILES
                    refresh_files = KS_REFRESH_SQL_FILES
                else:
                    create_files = CREATE_SQL_FILES
                    refresh_files = REFRESH_SQL_FILES
                execute_files(cursor, create_files)
                execute_files(cursor, refresh_files)
                validate_comments(cursor, scope)
                dwd_result = validate_dwd(cursor, ods_rows, scope)
                dws_result = (
                    validate_platform_dws(cursor, scope)
                    if scope != "legacy"
                    else validate_dws_ads(cursor, require_all_platforms=True)
                )
                reconciliation = validate_reconciliation(cursor, scope)
                baseline = (
                    validate_baseline(cursor)
                    if scope == "legacy" and args.enforce_current_baseline
                    else {}
                )
                samples = sample_rows(cursor) if scope == "legacy" else []
                label = {
                    "douyin": "抖音",
                    "ks": "快手",
                    "legacy": "抖音、快手",
                }[scope]
                print(f"{label}主营收入 DWD/DWS 刷新成功")
                print(f"ODS行数：{ods_rows}")
                print("批次店铺映射：")
                for row in batch_mappings:
                    print(row)
                print(f"DWD验收：{dwd_result}")
                print(f"DWS验收：{dws_result}")
                print(f"收入勾稽：{reconciliation}")
                if scope == "legacy":
                    print("DWD抽样：")
                    for row in samples:
                        print(row)
                    if args.enforce_current_baseline:
                        print(f"专项基准校验通过：{baseline}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def main() -> None:
    args = build_parser().parse_args()
    run_pipeline(args, "legacy")


if __name__ == "__main__":
    main()
