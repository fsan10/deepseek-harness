#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新银行流水统一指标及银行兼容指标链路。"""

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
CREATE_SQL_FILES = [
    "bank/main_business_revenue/184_dws_bank_main_business_revenue_account_daily_postgres.sql",
    "ads/main_business_revenue/185_ads_main_business_revenue_company_daily_postgres.sql",
    "bank/total_revenue/188_dws_bank_total_revenue_account_daily_type_postgres.sql",
    "ads/total_revenue/189_ads_total_revenue_company_daily_type_postgres.sql",
    "bank/total_expense/192_dws_bank_total_expense_account_daily_type_postgres.sql",
    "ads/total_expense/193_ads_total_expense_company_daily_type_postgres.sql",
    "bank/main_business_cost/196_dws_bank_main_business_cost_account_daily_postgres.sql",
    "ads/main_business_cost/197_ads_main_business_cost_company_daily_postgres.sql",
    "bank/statement_metrics/361_dws_bank_statement_account_daily_metric_postgres.sql",
    "ads/bank_statement/362_ads_bank_statement_company_daily_metric_postgres.sql",
]
REFRESH_SQL_FILES = [
    "bank/main_business_revenue/186_refresh_dws_bank_main_business_revenue_account_daily_postgres.sql",
    "ads/main_business_revenue/187_refresh_ads_main_business_revenue_company_daily_postgres.sql",
    "bank/total_revenue/190_refresh_dws_bank_total_revenue_account_daily_type_postgres.sql",
    "ads/total_revenue/191_refresh_ads_total_revenue_company_daily_type_postgres.sql",
    "bank/total_expense/194_refresh_dws_bank_total_expense_account_daily_type_postgres.sql",
    "ads/total_expense/195_refresh_ads_total_expense_company_daily_type_postgres.sql",
    "bank/main_business_cost/198_refresh_dws_bank_main_business_cost_account_daily_postgres.sql",
    "ads/main_business_cost/199_refresh_ads_main_business_cost_company_daily_postgres.sql",
    "bank/statement_metrics/363_refresh_dws_bank_statement_account_daily_metric_postgres.sql",
    "ads/bank_statement/364_refresh_ads_bank_statement_company_daily_metric_postgres.sql",
]
REQUIRED_COLUMNS = {
    ("ods", "ods_bank_statement"): {
        "id", "batch_id", "account_no", "account_name", "transaction_date",
        "debit_amount", "credit_amount", "transaction_no", "created_at",
    },
    ("dwd", "dwd_statement_split"): {
        "id", "ods_id", "batch_id", "split_index", "split_amount", "expense_type_id",
        "account_entry_id", "original_amount", "adjusted_diff", "updated_at",
    },
    ("fund", "import_record"): {
        "batch_id", "status", "is_submitted", "submitted_at",
    },
    ("dim", "dim_expense_type"): {"id", "code", "name"},
    ("dim", "dim_account_entry"): {"id", "code", "name"},
    ("dim", "dim_account_entry_expense_type"): {"expense_type_id", "account_entry_id"},
    ("dim", "dim_platform_shop_company"): {"company_code", "company_name"},
    ("ads", "ads_settlement_net_company_shop_daily"): {
        "stat_date", "company_code", "company_name", "settlement_net_amount",
        "included_event_count", "source_updated_at",
    },
}
NEW_TABLES = [
    ("dws", "dws_bank_main_business_revenue_account_daily"),
    ("ads", "ads_main_business_revenue_company_daily"),
    ("dws", "dws_bank_total_revenue_account_daily_type"),
    ("ads", "ads_total_revenue_company_daily_type"),
    ("dws", "dws_bank_total_expense_account_daily_type"),
    ("ads", "ads_total_expense_company_daily_type"),
    ("dws", "dws_bank_main_business_cost_account_daily"),
    ("ads", "ads_main_business_cost_company_daily"),
    ("dws", "dws_bank_statement_account_daily_metric"),
    ("ads", "ads_bank_statement_company_daily_metric"),
]
EXPECTED_BATCH = "IMP20260721002"
EXPECTED = {
    "ods_rows": 58,
    "dwd_rows": 65,
    "platform_withdrawal": Decimal("833748.88"),
    "main_business_revenue": Decimal("0.00"),
    "non_operating_revenue": Decimal("0.43"),
    "platform_revenue": Decimal("4796746.68"),
    "total_revenue": Decimal("4796747.11"),
    "selling_expense": Decimal("513439.01"),
    "administrative_expense": Decimal("59185.78"),
    "tax_and_surcharge": Decimal("108759.18"),
    "personnel_cost": Decimal("126676.75"),
    "financial_expense": Decimal("79.45"),
    "non_operating_expense": Decimal("0.00"),
    "total_expense": Decimal("808140.17"),
    "main_business_cost": Decimal("1650.00"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新银行经营管理指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="执行历史专项验收基准；日常和自动化刷新不得启用。",
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
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema=%s AND table_name=%s""",
            (schema_name, table_name),
        )
        missing = sorted(required - {row[0] for row in cursor.fetchall()})
        if missing:
            raise RuntimeError(f"{schema_name}.{table_name}缺少必需字段：{', '.join(missing)}")


def validate_source(cursor, *, enforce_current_baseline: bool = False) -> dict[str, object]:
    validate_required_objects(cursor)
    cursor.execute(
        """SELECT batch_id FROM fund.import_record
           WHERE status='success' AND is_submitted ORDER BY batch_id"""
    )
    submitted_batches = [row[0] for row in cursor.fetchall()]
    if not submitted_batches:
        raise RuntimeError("没有已由财务提交锁定的银行批次")
    if enforce_current_baseline and submitted_batches != [EXPECTED_BATCH]:
        raise RuntimeError(f"已提交银行批次不是确认基准：{submitted_batches}，预期[{EXPECTED_BATCH}]")

    cursor.execute(
        """SELECT COUNT(*),COUNT(DISTINCT ods.id),COUNT(DISTINCT ods.transaction_no),
                  MIN(ods.transaction_date),MAX(ods.transaction_date)
           FROM ods.ods_bank_statement ods
           JOIN fund.import_record record ON record.batch_id=ods.batch_id
           WHERE record.status='success' AND record.is_submitted"""
    )
    ods_rows, ods_ids, transaction_nos, date_from, date_to = cursor.fetchone()
    if ods_rows != ods_ids or ods_rows != transaction_nos:
        raise RuntimeError(f"已提交ODS粒度变化：{ods_rows}/{ods_ids}/{transaction_nos}")
    if enforce_current_baseline and ods_rows != EXPECTED["ods_rows"]:
        raise RuntimeError(f"已提交ODS行数变化：{ods_rows}，预期{EXPECTED['ods_rows']}")

    cursor.execute(
        """SELECT COUNT(*),COUNT(DISTINCT split.id),
                  COUNT(*)-COUNT(DISTINCT (split.batch_id,split.ods_id,split.split_index)),
                  COUNT(DISTINCT split.ods_id),
                  COUNT(*) FILTER (WHERE split.expense_type_id IS NULL OR split.account_entry_id IS NULL),
                  COUNT(*) FILTER (WHERE split.original_amount+split.adjusted_diff<=0),
                  COALESCE(SUM(split.adjusted_diff),0)
           FROM dwd.dwd_statement_split split
           JOIN fund.import_record record ON record.batch_id=split.batch_id
           WHERE record.status='success' AND record.is_submitted"""
    )
    dwd_rows, dwd_ids, duplicate_keys, source_rows, unassigned, nonpositive, adjustment_balance = cursor.fetchone()
    if (
        dwd_rows != dwd_ids
        or duplicate_keys
        or source_rows != ods_rows
        or unassigned
        or nonpositive
        or adjustment_balance != Decimal("0.00")
    ):
        raise RuntimeError(
            "已提交DWD粒度或质量变化："
            f"{dwd_rows}/{dwd_ids}/{duplicate_keys}/{source_rows}/{unassigned}/{nonpositive}/{adjustment_balance}"
        )
    if enforce_current_baseline and dwd_rows != EXPECTED["dwd_rows"]:
        raise RuntimeError(f"已提交DWD行数变化：{dwd_rows}，预期{EXPECTED['dwd_rows']}")

    cursor.execute(
        """SELECT COUNT(*) FROM (
             SELECT ods.id
             FROM ods.ods_bank_statement ods
             JOIN fund.import_record record ON record.batch_id=ods.batch_id
             LEFT JOIN dwd.dwd_statement_split split
               ON split.ods_id=ods.id AND split.batch_id=ods.batch_id
             WHERE record.status='success' AND record.is_submitted
             GROUP BY ods.id,ods.debit_amount,ods.credit_amount
             HAVING COUNT(split.id)=0
                OR (ods.debit_amount IS NULL)=(ods.credit_amount IS NULL)
                OR ABS(SUM(split.split_amount)-COALESCE(ABS(ods.debit_amount),ABS(ods.credit_amount)))>0.01
           ) bad"""
    )
    if cursor.fetchone()[0]:
        raise RuntimeError("已提交ODS/DWD存在来源覆盖、金额方向、拆分或调账不平")

    cursor.execute(
        """SELECT COUNT(*)
           FROM dwd.dwd_statement_split split
           JOIN fund.import_record record ON record.batch_id=split.batch_id
           WHERE record.status='success' AND record.is_submitted
             AND NOT EXISTS (
               SELECT 1 FROM dim.dim_account_entry_expense_type relation
               WHERE relation.expense_type_id=split.expense_type_id
                 AND relation.account_entry_id=split.account_entry_id
             )"""
    )
    if cursor.fetchone()[0]:
        raise RuntimeError("已提交DWD存在无效的费用类型与入账科目关系")

    cursor.execute(
        """WITH detail AS (
             SELECT expense.name expense_name,account_entry.code account_code,account_entry.name account_name,
                    CASE
                      WHEN ods.debit_amount IS NOT NULL AND ods.credit_amount IS NULL
                        THEN -SIGN(ods.debit_amount)*(split.original_amount+split.adjusted_diff)
                      WHEN ods.credit_amount IS NOT NULL AND ods.debit_amount IS NULL
                        THEN SIGN(ods.credit_amount)*(split.original_amount+split.adjusted_diff)
                      ELSE 0
                    END signed_amount
             FROM dwd.dwd_statement_split split
             JOIN fund.import_record record ON record.batch_id=split.batch_id
              AND record.status='success' AND record.is_submitted
             JOIN ods.ods_bank_statement ods ON ods.id=split.ods_id
             JOIN dim.dim_expense_type expense ON expense.id=split.expense_type_id
             JOIN dim.dim_account_entry account_entry ON account_entry.id=split.account_entry_id
           )
           SELECT
             COALESCE(SUM(signed_amount) FILTER (WHERE expense_name='主营业务收入'
               AND (account_code='ACC002' OR account_name IN ('平台提现','入账-提现'))),0),
             COALESCE(SUM(signed_amount) FILTER (WHERE expense_name='主营业务收入'
               AND account_code<>'ACC002' AND account_name NOT IN ('平台提现','入账-提现')),0),
             COALESCE(SUM(signed_amount) FILTER (WHERE expense_name='营业外收入'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='销售费用'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='管理费用'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='税金及附加'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='人员成本'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='财务费用'),0),
             COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='营业外支出'),0),
              COALESCE(-SUM(signed_amount) FILTER (WHERE expense_name='主营业务成本'),0),
              COUNT(*) FILTER (WHERE expense_name='主营业务收入'
                AND account_code<>'ACC002' AND account_name NOT IN ('平台提现','入账-提现')),
              COUNT(*) FILTER (WHERE expense_name IN (
                '销售费用','管理费用','税金及附加','人员成本','财务费用','营业外支出'
              )),
              COUNT(*) FILTER (WHERE expense_name='主营业务成本')
            FROM detail"""
    )
    values = cursor.fetchone()
    keys = (
        "platform_withdrawal", "main_business_revenue", "non_operating_revenue",
        "selling_expense", "administrative_expense", "tax_and_surcharge",
        "personnel_cost", "financial_expense", "non_operating_expense", "main_business_cost",
        "main_business_revenue_details", "total_expense_details", "main_business_cost_details",
    )
    source_amounts = dict(zip(keys, values))
    if enforce_current_baseline:
        for key, value in source_amounts.items():
            if key not in EXPECTED:
                continue
            if value != EXPECTED[key]:
                raise RuntimeError(f"银行来源验收基准变化：{key}={value}，预期{EXPECTED[key]}")
    source_amounts["total_expense"] = sum(source_amounts[key] for key in (
        "selling_expense", "administrative_expense", "tax_and_surcharge",
        "personnel_cost", "financial_expense", "non_operating_expense",
    ))
    if enforce_current_baseline and source_amounts["total_expense"] != EXPECTED["total_expense"]:
        raise RuntimeError(f"银行总费用基准变化：{source_amounts['total_expense']}")

    cursor.execute("SELECT COALESCE(SUM(settlement_net_amount),0) FROM ads.ads_settlement_net_company_shop_daily")
    platform_revenue = cursor.fetchone()[0]
    if enforce_current_baseline and platform_revenue != EXPECTED["platform_revenue"]:
        raise RuntimeError(f"平台收入基准变化：{platform_revenue}，预期{EXPECTED['platform_revenue']}")
    source_amounts["platform_revenue"] = platform_revenue
    source_amounts["total_revenue"] = (
        source_amounts["main_business_revenue"]
        + source_amounts["non_operating_revenue"]
        + platform_revenue
    )
    if enforce_current_baseline and source_amounts["total_revenue"] != EXPECTED["total_revenue"]:
        raise RuntimeError(f"总营收基准变化：{source_amounts['total_revenue']}")
    source_amounts.update({
        "submitted_batches": submitted_batches,
        "ods_rows": ods_rows,
        "dwd_rows": dwd_rows,
        "date_range": (date_from, date_to),
    })
    return source_amounts


def bidirectional_difference(cursor, metric: str) -> int:
    if metric == "main_revenue":
        sql = """
        WITH company_map AS (
          SELECT company_name,MIN(company_code) company_code FROM dim.dim_platform_shop_company
          GROUP BY company_name HAVING COUNT(DISTINCT company_code)=1
        ), expected AS (
          SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                 ROUND(SUM(d.main_business_revenue_amount),2) amount,SUM(d.included_detail_count) detail_count
          FROM dws.dws_bank_main_business_revenue_account_daily d
          LEFT JOIN company_map m ON m.company_name=d.source_account_name
          GROUP BY 1,2,3
        ), actual AS (
          SELECT stat_date,platform_code,company_code,main_business_revenue_amount,included_detail_count
          FROM ads.ads_main_business_revenue_company_daily
        )
        SELECT COUNT(*) FROM ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) x
        """
    elif metric == "expense":
        sql = """
        WITH company_map AS (
          SELECT company_name,MIN(company_code) company_code FROM dim.dim_platform_shop_company
          GROUP BY company_name HAVING COUNT(DISTINCT company_code)=1
        ), expected AS (
          SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,d.expense_type_code,
                 ROUND(SUM(d.expense_amount),2) amount,SUM(d.included_detail_count) detail_count
          FROM dws.dws_bank_total_expense_account_daily_type d
          LEFT JOIN company_map m ON m.company_name=d.source_account_name
          GROUP BY 1,2,3,4
        ), actual AS (
          SELECT stat_date,platform_code,company_code,expense_type_code,expense_amount,included_detail_count
          FROM ads.ads_total_expense_company_daily_type
        )
        SELECT COUNT(*) FROM ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) x
        """
    elif metric == "main_cost":
        sql = """
        WITH company_map AS (
          SELECT company_name,MIN(company_code) company_code FROM dim.dim_platform_shop_company
          GROUP BY company_name HAVING COUNT(DISTINCT company_code)=1
        ), expected AS (
          SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                 ROUND(SUM(d.main_business_cost_amount),2) amount,SUM(d.included_detail_count) detail_count
          FROM dws.dws_bank_main_business_cost_account_daily d
          LEFT JOIN company_map m ON m.company_name=d.source_account_name
          GROUP BY 1,2,3
        ), actual AS (
          SELECT stat_date,platform_code,company_code,main_business_cost_amount,included_detail_count
          FROM ads.ads_main_business_cost_company_daily
        )
        SELECT COUNT(*) FROM ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) x
        """
    elif metric == "bank_statement":
        sql = """
        WITH company_map AS (
          SELECT company_name,MIN(company_code) company_code FROM dim.dim_platform_shop_company
          GROUP BY company_name HAVING COUNT(DISTINCT company_code)=1
        ), expected AS (
          SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                 d.metric_group_code,d.metric_code,
                 ROUND(SUM(d.metric_amount),2) amount,SUM(d.included_detail_count) detail_count
          FROM dws.dws_bank_statement_account_daily_metric d
          LEFT JOIN company_map m ON m.company_name=d.source_account_name
          GROUP BY 1,2,3,4,5
        ), actual AS (
          SELECT stat_date,platform_code,company_code,metric_group_code,metric_code,
                 metric_amount,included_detail_count
          FROM ads.ads_bank_statement_company_daily_metric
        )
        SELECT COUNT(*) FROM ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) x
        """
    else:
        sql = """
        WITH company_map AS (
          SELECT company_name,MIN(company_code) company_code FROM dim.dim_platform_shop_company
          GROUP BY company_name HAVING COUNT(DISTINCT company_code)=1
        ), expected AS (
          SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,d.revenue_type_code,
                 ROUND(SUM(d.revenue_amount),2) amount,SUM(d.included_detail_count) detail_count
          FROM dws.dws_bank_total_revenue_account_daily_type d
          LEFT JOIN company_map m ON m.company_name=d.source_account_name
          GROUP BY 1,2,3,4
          UNION ALL
          SELECT stat_date,'all_platforms',company_code,'platform_revenue',
                 ROUND(SUM(settlement_net_amount),2),SUM(included_event_count)
          FROM ads.ads_settlement_net_company_shop_daily GROUP BY stat_date,company_code
        ), actual AS (
          SELECT stat_date,platform_code,company_code,revenue_type_code,revenue_amount,included_detail_count
          FROM ads.ads_total_revenue_company_daily_type
        )
        SELECT COUNT(*) FROM ((SELECT * FROM expected EXCEPT SELECT * FROM actual)
          UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected)) x
        """
    cursor.execute(sql)
    return cursor.fetchone()[0]


def validate_pipeline(
    cursor,
    source: dict[str, object],
    *,
    enforce_current_baseline: bool = False,
) -> dict[str, object]:
    table_profiles = {}
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            f"SELECT COUNT(*),MIN(stat_date),MAX(stat_date) FROM {schema_name}.{table_name}"
        )
        table_profiles[f"{schema_name}.{table_name}"] = cursor.fetchone()

    cursor.execute(
        """SELECT COALESCE(SUM(main_business_revenue_amount),0),
                  COALESCE(SUM(included_detail_count),0),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_main_business_revenue_company_daily"""
    )
    main_revenue, main_revenue_details, unmapped_main_revenue = cursor.fetchone()
    cursor.execute(
        """SELECT revenue_type_code,COALESCE(SUM(revenue_amount),0)
           FROM ads.ads_total_revenue_company_daily_type
           GROUP BY revenue_type_code ORDER BY revenue_type_code"""
    )
    revenue_components = dict(cursor.fetchall())
    cursor.execute(
        """SELECT metric_code,COALESCE(SUM(metric_amount),0)
           FROM ads.ads_bank_statement_company_daily_metric
           GROUP BY metric_code ORDER BY metric_code"""
    )
    bank_metric_components = dict(cursor.fetchall())
    cursor.execute(
        """SELECT metric_group_code,COALESCE(SUM(metric_amount),0)
           FROM ads.ads_bank_statement_company_daily_metric
           GROUP BY metric_group_code ORDER BY metric_group_code"""
    )
    bank_group_totals = dict(cursor.fetchall())
    cursor.execute(
        """SELECT expense_type_code,COALESCE(SUM(expense_amount),0)
           FROM ads.ads_total_expense_company_daily_type
           GROUP BY expense_type_code ORDER BY expense_type_code"""
    )
    expense_components = dict(cursor.fetchall())
    cursor.execute(
        """SELECT COALESCE(SUM(expense_amount),0),COALESCE(SUM(included_detail_count),0),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_total_expense_company_daily_type"""
    )
    total_expense, expense_details, unmapped_expense = cursor.fetchone()
    cursor.execute(
        """SELECT COALESCE(SUM(main_business_cost_amount),0),COALESCE(SUM(included_detail_count),0),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_main_business_cost_company_daily"""
    )
    main_cost, main_cost_details, unmapped_main_cost = cursor.fetchone()
    cursor.execute(
        """SELECT COALESCE(SUM(revenue_amount),0),
                  COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_total_revenue_company_daily_type"""
    )
    total_revenue, unmapped_total_revenue = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*) FILTER (WHERE company_code='unmapped')
           FROM ads.ads_bank_statement_company_daily_metric"""
    )
    unmapped_bank_statement = cursor.fetchone()[0]
    expected_revenue_components = {
        "platform_revenue": source["platform_revenue"],
        "main_business_revenue": source["main_business_revenue"],
        "non_operating_revenue": source["non_operating_revenue"],
    }
    expected_expense_components = {
        "selling_expense": source["selling_expense"],
        "administrative_expense": source["administrative_expense"],
        "tax_and_surcharge": source["tax_and_surcharge"],
        "personnel_cost": source["personnel_cost"],
        "financial_expense": source["financial_expense"],
        "non_operating_expense": source["non_operating_expense"],
    }
    expected_bank_metric_components = {
        "main_business_revenue": source["main_business_revenue"],
        "non_operating_revenue": source["non_operating_revenue"],
        **expected_expense_components,
        "main_business_cost": source["main_business_cost"],
    }
    expected_bank_group_totals = {
        "revenue": source["main_business_revenue"] + source["non_operating_revenue"],
        "expense": source["total_expense"],
        "cost": source["main_business_cost"],
    }
    if (
        main_revenue != source["main_business_revenue"]
        or main_revenue_details != source["main_business_revenue_details"]
    ):
        raise RuntimeError(f"主营业务收入ADS与已提交来源不一致：{main_revenue}/{main_revenue_details}")
    if revenue_components != expected_revenue_components or total_revenue != source["total_revenue"]:
        raise RuntimeError(f"总营收ADS与已提交来源不一致：{revenue_components}/{total_revenue}")
    if bank_metric_components != expected_bank_metric_components:
        raise RuntimeError(f"银行流水统一ADS不符合基准：{bank_metric_components}")
    if bank_group_totals != expected_bank_group_totals:
        raise RuntimeError(f"银行流水统一ADS指标组不符合基准：{bank_group_totals}")
    if expense_components != expected_expense_components or total_expense != source["total_expense"]:
        raise RuntimeError(f"总费用ADS与已提交来源不一致：{expense_components}/{total_expense}")
    if (
        main_cost != source["main_business_cost"]
        or main_cost_details != source["main_business_cost_details"]
    ):
        raise RuntimeError(f"主营业务成本ADS与已提交来源不一致：{main_cost}/{main_cost_details}")
    if expense_details != source["total_expense_details"]:
        raise RuntimeError(f"总费用纳入明细数与已提交来源不一致：{expense_details}")

    if enforce_current_baseline and table_profiles["dws.dws_bank_statement_account_daily_metric"][0] != 171:
        raise RuntimeError(
            "银行流水统一DWS行数变化："
            f"{table_profiles['dws.dws_bank_statement_account_daily_metric'][0]}，预期171"
        )
    if enforce_current_baseline and table_profiles["ads.ads_bank_statement_company_daily_metric"][0] != 171:
        raise RuntimeError(
            "银行流水统一ADS行数变化："
            f"{table_profiles['ads.ads_bank_statement_company_daily_metric'][0]}，预期171"
        )
    unmapped = (
        unmapped_main_revenue,
        unmapped_total_revenue,
        unmapped_expense,
        unmapped_main_cost,
        unmapped_bank_statement,
    )
    if any(unmapped):
        raise RuntimeError(f"ADS存在未匹配公司：{unmapped}")
    bidirectional = tuple(bidirectional_difference(cursor, metric) for metric in (
        "main_revenue",
        "total_revenue",
        "expense",
        "main_cost",
        "bank_statement",
    ))
    if any(bidirectional):
        raise RuntimeError(f"DWS/ADS双向逐粒度差异：{bidirectional}")

    cursor.execute(
        """SELECT
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code FROM ads.ads_main_business_revenue_company_daily GROUP BY 1,2,3 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code,revenue_type_code FROM ads.ads_total_revenue_company_daily_type GROUP BY 1,2,3,4 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code,expense_type_code FROM ads.ads_total_expense_company_daily_type GROUP BY 1,2,3,4 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,platform_code,company_code FROM ads.ads_main_business_cost_company_daily GROUP BY 1,2,3 HAVING COUNT(*)>1) x),
          (SELECT COUNT(*) FROM (SELECT stat_date,company_code,metric_code FROM ads.ads_bank_statement_company_daily_metric GROUP BY 1,2,3 HAVING COUNT(*)>1) x)"""
    )
    duplicate_ads_keys = cursor.fetchone()
    if any(duplicate_ads_keys):
        raise RuntimeError(f"ADS主键重复：{duplicate_ads_keys}")

    cursor.execute(
        """WITH detail AS (
             SELECT split.id,ods.transaction_date,ods.debit_amount,ods.credit_amount,
                    split.original_amount,split.adjusted_diff,
                    expense.name expense_name,account_entry.code account_code,account_entry.name account_name,
                    CASE WHEN ods.debit_amount IS NOT NULL THEN
                      -SIGN(ods.debit_amount)*(split.original_amount+split.adjusted_diff)
                    ELSE SIGN(ods.credit_amount)*(split.original_amount+split.adjusted_diff) END signed_amount
             FROM dwd.dwd_statement_split split
             JOIN fund.import_record record ON record.batch_id=split.batch_id
              AND record.status='success' AND record.is_submitted
             JOIN ods.ods_bank_statement ods ON ods.id=split.ods_id
             JOIN dim.dim_expense_type expense ON expense.id=split.expense_type_id
             JOIN dim.dim_account_entry account_entry ON account_entry.id=split.account_entry_id
           )
           (SELECT '平台提现排除',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE account_code='ACC002' ORDER BY id LIMIT 1)
           UNION ALL
           (SELECT '营业外收入流出',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE expense_name='营业外收入' AND signed_amount<0 ORDER BY id LIMIT 1)
           UNION ALL
           (SELECT '营业外收入流入',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE expense_name='营业外收入' AND signed_amount>0 ORDER BY id LIMIT 1)
           UNION ALL
           (SELECT '手工调账拆分',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE adjusted_diff<>0 ORDER BY id LIMIT 1)
           UNION ALL
           (SELECT '费用正常流出',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE expense_name='销售费用' ORDER BY id LIMIT 1)
           UNION ALL
           (SELECT '主营业务成本',id,transaction_date,debit_amount,credit_amount,original_amount,adjusted_diff,expense_name,account_name,signed_amount
              FROM detail WHERE expense_name='主营业务成本' ORDER BY id LIMIT 1)"""
    )
    samples = cursor.fetchall()
    if enforce_current_baseline and len(samples) < 6:
        raise RuntimeError(f"公式抽样场景不足：{samples}")

    return {
        "table_profiles": table_profiles,
        "revenue_components": revenue_components,
        "bank_metric_components": bank_metric_components,
        "bank_group_totals": bank_group_totals,
        "expense_components": expense_components,
        "totals": (
            main_revenue,
            total_revenue,
            total_expense,
            main_cost,
        ),
        "detail_counts": (main_revenue_details, expense_details, main_cost_details),
        "unmapped": unmapped,
        "bidirectional": bidirectional,
        "duplicate_ads_keys": duplicate_ads_keys,
        "samples": samples,
    }


def validate_comments(cursor) -> None:
    missing = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """SELECT obj_description(c.oid,'pg_class') FROM pg_class c
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s""",
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """SELECT a.attname FROM pg_attribute a
               JOIN pg_class c ON c.oid=a.attrelid
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
                 AND col_description(c.oid,a.attnum) IS NULL ORDER BY a.attnum""",
            (schema_name, table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{row[0]}" for row in cursor.fetchall())
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def run_pipeline(args: argparse.Namespace) -> None:
    connection = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )
    try:
        with connection.cursor() as cursor:
            source = validate_source(
                cursor,
                enforce_current_baseline=args.enforce_current_baseline,
            )
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_pipeline(
                cursor,
                source,
                enforce_current_baseline=args.enforce_current_baseline,
            )
            validate_comments(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(f"已提交银行批次：{source['submitted_batches']}")
    print(f"ODS/DWD行数：{source['ods_rows']}/{source['dwd_rows']}")
    print(f"银行交易日期范围：{source['date_range'][0]} 至 {source['date_range'][1]}")
    print(f"排除平台提现：{source['platform_withdrawal']:.2f}")
    print(f"主营业务收入：{result['totals'][0]:.2f}")
    print(f"兼容总营收组成：{result['revenue_components']}")
    print(f"兼容总营收：{result['totals'][1]:.2f}")
    print(f"银行流水统一指标：{result['bank_metric_components']}")
    print(f"银行流水统一指标组：{result['bank_group_totals']}")
    print(f"总费用组成：{result['expense_components']}")
    print(f"总费用：{result['totals'][2]:.2f}")
    print(f"主营业务成本：{result['totals'][3]:.2f}")
    print(f"纳入明细数（主营收入/总费用/主营成本）：{result['detail_counts']}")
    print(
        "ADS未匹配公司行数"
        "（主营收入/兼容总营收/总费用/主营成本/银行统一）："
        f"{result['unmapped']}"
    )
    print(
        "DWS/ADS双向差异"
        "（主营收入/兼容总营收/总费用/主营成本/银行统一）："
        f"{result['bidirectional']}"
    )
    print(f"ADS重复主键组：{result['duplicate_ads_keys']}")
    print("各层行数与日期范围：")
    for table_name, profile in result["table_profiles"].items():
        print(f"  {table_name}: {profile[0]}行，{profile[1]} 至 {profile[2]}")
    print("公式抽样（场景,split_id,日期,借方,贷方,原金额,调账差,分类,入账,带符号金额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
