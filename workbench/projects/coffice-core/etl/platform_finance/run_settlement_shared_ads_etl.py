#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新七个平台共用的结算收入、支出、结算净额日/月 ADS。

各平台结算 ETL 只负责自己的 DWD/DWS；本任务作为统一的收口步骤，
在所有已选平台任务完成后一次性重建三张跨平台日 ADS、结算净额月度底表
和 DataEase 指标展开视图。这样即使同一批 ETL 中包含多个平台，也不会
依赖某个平台脚本最后执行来决定共享表内容。
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

try:
    import psycopg2
except ImportError as exc:  # pragma: no cover - 运行环境缺依赖时的提示
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
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
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
    "ads/settlement_net/416_ads_settlement_net_company_shop_monthly_postgres.sql",
    "ads/settlement_net/418_view_settlement_net_company_shop_monthly_metric_postgres.sql",
]
REFRESH_SQL_FILES = [
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
    "ads/settlement_net/417_refresh_ads_settlement_net_company_shop_monthly_postgres.sql",
]

PLATFORMS = (
    "douyin",
    "jd",
    "ks",
    "pdd",
    "wechat_channels",
    "tmall",
    "xhs",
)
DWS_TABLES = (
    "dws_douyin_settlement_income_shop_daily_type",
    "dws_jd_settlement_income_shop_daily_type",
    "dws_ks_settlement_income_shop_daily_type",
    "dws_pdd_settlement_income_shop_daily_type",
    "dws_wechat_channels_settlement_income_shop_daily_type",
    "dws_tmall_settlement_income_shop_daily_type",
    "dws_xhs_settlement_income_shop_daily_type",
    "dws_douyin_settlement_expense_shop_daily_type",
    "dws_jd_settlement_expense_shop_daily_type",
    "dws_ks_settlement_expense_shop_daily_type",
    "dws_pdd_settlement_expense_shop_daily_type",
    "dws_wechat_channels_settlement_expense_shop_daily_type",
    "dws_tmall_settlement_expense_shop_daily_type",
    "dws_xhs_settlement_expense_shop_daily_type",
    "dws_douyin_settlement_net_shop_daily",
    "dws_jd_settlement_net_shop_daily",
    "dws_ks_settlement_net_shop_daily",
    "dws_pdd_settlement_net_shop_daily",
    "dws_wechat_channels_settlement_net_shop_daily",
    "dws_tmall_settlement_net_shop_daily",
    "dws_xhs_settlement_net_shop_daily",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="刷新七平台共享结算日/月 ADS 及 DataEase 透视视图。"
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_dws_sources(cursor) -> None:
    missing: list[str] = []
    for table_name in DWS_TABLES:
        cursor.execute("SELECT to_regclass(%s)", (f"dws.{table_name}",))
        if cursor.fetchone()[0] is None:
            missing.append(f"dws.{table_name}")
    if missing:
        raise RuntimeError(
            "共享结算 ADS 刷新前缺少平台 DWS：" + ", ".join(missing)
        )


def validate_monthly_result(cursor) -> dict[str, object]:
    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_month), MAX(stat_month),
               COALESCE(ROUND(SUM(income_amount), 2), 0),
               COALESCE(ROUND(SUM(expense_amount), 2), 0),
               COALESCE(ROUND(SUM(settlement_net_amount), 2), 0),
               COALESCE(ROUND(SUM(source_settlement_amount), 2), 0),
               COALESCE(ROUND(SUM(validation_difference_amount), 2), 0),
               COALESCE(SUM(included_event_count), 0),
               COALESCE(ROUND(SUM(COALESCE(display_expense_amount, expense_amount)), 2), 0)
        FROM ads.ads_settlement_net_company_shop_monthly
        """
    )
    (
        monthly_rows,
        min_month,
        max_month,
        monthly_income,
        monthly_expense,
        monthly_net,
        monthly_source_settlement,
        monthly_validation_difference,
        monthly_included_events,
        monthly_display_expense,
    ) = cursor.fetchone()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT stat_month, platform_code, company_code, shop_code
            FROM ads.ads_settlement_net_company_shop_monthly
            GROUP BY 1, 2, 3, 4
            HAVING COUNT(*) > 1
        ) duplicate_keys
        """
    )
    duplicate_monthly = cursor.fetchone()[0]
    if duplicate_monthly:
        raise RuntimeError(f"月度结算净额 ADS 主键重复组：{duplicate_monthly}")

    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE settlement_net_amount
                    <> ROUND(income_amount - expense_amount, 2)
            ),
            COUNT(*) FILTER (
                WHERE validation_difference_amount
                    <> ROUND(
                        income_amount - expense_amount
                        - source_settlement_amount,
                        2
                    )
            )
        FROM ads.ads_settlement_net_company_shop_monthly
        """
    )
    monthly_formula_errors, monthly_validation_errors = cursor.fetchone()
    if monthly_formula_errors or monthly_validation_errors:
        raise RuntimeError(
            "月度结算净额公式或核验字段错误："
            f"净额公式={monthly_formula_errors}，核验差额={monthly_validation_errors}"
        )

    cursor.execute(
        """
        WITH daily AS (
            SELECT
                DATE_TRUNC('month', stat_date)::date AS stat_month,
                platform_code,
                MAX(platform_name) AS platform_name,
                company_code,
                MAX(company_name) AS company_name,
                shop_code,
                MAX(shop_name) AS shop_name,
                ROUND(SUM(income_amount), 2) AS income_amount,
                ROUND(SUM(expense_amount), 2) AS expense_amount,
                ROUND(SUM(display_expense_amount), 2) AS display_expense_amount,
                ROUND(SUM(income_amount) - SUM(expense_amount), 2)
                    AS settlement_net_amount,
                ROUND(SUM(source_settlement_amount), 2)
                    AS source_settlement_amount,
                ROUND(
                    SUM(income_amount) - SUM(expense_amount)
                    - SUM(source_settlement_amount),
                    2
                ) AS validation_difference_amount,
                SUM(included_event_count) AS included_event_count
            FROM ads.ads_settlement_net_company_shop_daily
            GROUP BY DATE_TRUNC('month', stat_date)::date,
                     platform_code, company_code, shop_code
        ), monthly AS (
            SELECT
                stat_month,
                platform_code,
                platform_name,
                company_code,
                company_name,
                shop_code,
                shop_name,
                income_amount,
                expense_amount,
                display_expense_amount,
                settlement_net_amount,
                source_settlement_amount,
                validation_difference_amount,
                included_event_count
            FROM ads.ads_settlement_net_company_shop_monthly
        )
        SELECT
            (
                SELECT COUNT(*)
                FROM (
                    SELECT * FROM daily
                    EXCEPT
                    SELECT * FROM monthly
                ) daily_not_in_monthly
            ),
            (
                SELECT COUNT(*)
                FROM (
                    SELECT * FROM monthly
                    EXCEPT
                    SELECT * FROM daily
                ) monthly_not_in_daily
            )
        """
    )
    daily_not_in_monthly, monthly_not_in_daily = cursor.fetchone()
    if daily_not_in_monthly or monthly_not_in_daily:
        raise RuntimeError(
            "日ADS与月度ADS双向差异不为0："
            f"日表未汇总={daily_not_in_monthly}，月表多出={monthly_not_in_daily}"
        )

    cursor.execute(
        """
        SELECT metric_order, metric_code, metric_name,
               COUNT(*) AS metric_rows,
               COALESCE(ROUND(SUM(amount), 2), 0) AS metric_amount
        FROM ads.v_settlement_net_company_shop_monthly_metric
        GROUP BY metric_order, metric_code, metric_name
        ORDER BY metric_order
        """
    )
    view_metrics = cursor.fetchall()
    expected_metrics = {
        "income": (1, "收入", monthly_income),
        "expense": (2, "支出", monthly_display_expense),
        "settlement_net": (3, "结算净额", monthly_net),
    }
    if len(view_metrics) != len(expected_metrics):
        raise RuntimeError(
            "月度结算净额透视视图指标种类不完整："
            f"实际={view_metrics}"
        )
    for metric_order, metric_code, metric_name, metric_rows, metric_amount in view_metrics:
        expected = expected_metrics.get(metric_code)
        if expected is None or (metric_order, metric_name) != expected[:2]:
            raise RuntimeError(
                "月度结算净额透视视图指标定义错误："
                f"实际={(metric_order, metric_code, metric_name)}"
            )
        if metric_rows != monthly_rows or metric_amount != expected[2]:
            raise RuntimeError(
                "月度结算净额透视视图金额或行数不一致："
                f"指标={metric_code}，行数={metric_rows}/{monthly_rows}，"
                f"金额={metric_amount}/{expected[2]}"
            )

    view_rows = sum(row[3] for row in view_metrics)
    if view_rows != monthly_rows * len(expected_metrics):
        raise RuntimeError(
            f"月度结算净额透视视图行数错误：实际={view_rows}，"
            f"预期={monthly_rows * len(expected_metrics)}"
        )
    if monthly_net != monthly_income - monthly_expense:
        raise RuntimeError(
            f"月度结算净额公式失败：收入={monthly_income}，"
            f"支出={monthly_expense}，净额={monthly_net}"
        )

    return {
        "rows": monthly_rows,
        "min_month": min_month,
        "max_month": max_month,
        "income": monthly_income,
        "expense": monthly_expense,
        "display_expense": monthly_display_expense,
        "net": monthly_net,
        "source_settlement": monthly_source_settlement,
        "validation_difference": monthly_validation_difference,
        "included_events": monthly_included_events,
        "view_rows": view_rows,
        "daily_not_in_monthly": daily_not_in_monthly,
        "monthly_not_in_daily": monthly_not_in_daily,
        "duplicate_monthly": duplicate_monthly,
        "formula_errors": monthly_formula_errors,
        "validation_errors": monthly_validation_errors,
    }


def validate_result(cursor) -> dict[str, object]:
    cursor.execute(
        """
        SELECT platform_code,
               COUNT(*) AS rows,
               MIN(stat_date) AS min_date,
               MAX(stat_date) AS max_date,
               ROUND(SUM(income_amount), 2) AS income,
               ROUND(SUM(expense_amount), 2) AS expense,
               ROUND(SUM(settlement_net_amount), 2) AS net,
               ROUND(SUM(income_amount) - SUM(expense_amount)
                     - SUM(source_settlement_amount), 2) AS validation_difference,
               COUNT(*) FILTER (WHERE company_code = 'unmapped') AS unmapped
        FROM ads.ads_settlement_net_company_shop_daily
        GROUP BY platform_code
        ORDER BY platform_code
        """
    )
    net_rows = cursor.fetchall()
    # 平台源字段的核验差额属于数据质量告警，不得替代“收入-支出”的
    # 计算净额，也不应阻断其他平台的共享 ADS 刷新（当前快手存在已知
    # 的源实际结算金额差异）。
    source_difference_rows = [row for row in net_rows if row[7] != 0]

    cursor.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT stat_date, platform_code, company_code, shop_code
            FROM ads.ads_settlement_net_company_shop_daily
            GROUP BY 1,2,3,4
            HAVING COUNT(*) > 1
        ) duplicate_keys
        """
    )
    duplicate_net = cursor.fetchone()[0]
    if duplicate_net:
        raise RuntimeError(f"共享结算净额 ADS 主键重复组：{duplicate_net}")

    cursor.execute(
        """
        SELECT
          (SELECT ROUND(COALESCE(SUM(income_amount), 0), 2)
             FROM ads.ads_settlement_income_company_shop_daily_type),
          (SELECT ROUND(COALESCE(SUM(expense_amount), 0), 2)
             FROM ads.ads_settlement_expense_company_shop_daily_type),
          (SELECT ROUND(COALESCE(SUM(settlement_net_amount), 0), 2)
             FROM ads.ads_settlement_net_company_shop_daily)
        """
    )
    income, expense, net = cursor.fetchone()
    if net != income - expense:
        raise RuntimeError(
            f"共享结算净额公式失败：收入={income}，支出={expense}，净额={net}"
        )
    monthly = validate_monthly_result(cursor)
    return {
        "net_rows": net_rows,
        "income": income,
        "expense": expense,
        "net": net,
        "monthly": monthly,
        "duplicate_net": duplicate_net,
        "source_difference_rows": source_difference_rows,
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
            execute_files(cursor, CREATE_SQL_FILES)
            validate_dws_sources(cursor)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_result(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(
        f"共享结算 ADS 总额：收入={result['income']:.2f}，"
        f"支出={result['expense']:.2f}，净额={result['net']:.2f}"
    )
    print("平台日明细（平台，行数，日期范围，收入，支出，净额，核验差额，未匹配公司）：")
    for row in result["net_rows"]:
        print(f"  {row}")
    if result["source_difference_rows"]:
        print(f"源结算金额差异告警（不阻断刷新）：{result['source_difference_rows']}")
    monthly = result["monthly"]
    print(
        "月度透视底表："
        f"行数={monthly['rows']}，月份范围={monthly['min_month']}至{monthly['max_month']}，"
        f"收入={monthly['income']:.2f}，支出={monthly['expense']:.2f}，"
        f"净额={monthly['net']:.2f}，源结算金额={monthly['source_settlement']:.2f}，"
        f"核验差额={monthly['validation_difference']:.2f}，"
        f"纳入事件数={monthly['included_events']}，视图行数={monthly['view_rows']}"
    )
    print(
        "月度校验："
        f"日/月双向差异={monthly['daily_not_in_monthly']}/"
        f"{monthly['monthly_not_in_daily']}，"
        f"重复主键={monthly['duplicate_monthly']}，"
        f"公式错误={monthly['formula_errors']}，"
        f"核验字段错误={monthly['validation_errors']}"
    )


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
