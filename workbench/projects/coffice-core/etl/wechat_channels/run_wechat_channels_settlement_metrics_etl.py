#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新视频号结算收入、支出和结算净额三套独立指标链路。"""

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
    sys.path.insert(0,str(PROJECT_ROOT))
from etl.common.finance_sources import prepare_finance_sources
PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]
CREATE_SQL_FILES = [
    "wechat_channels/settlement_income/120_dwd_wechat_channels_settlement_income_event_detail_postgres.sql",
    "wechat_channels/settlement_income/121_dws_wechat_channels_settlement_income_shop_daily_type_postgres.sql",
    "douyin/settlement_income/67_dws_douyin_settlement_income_shop_daily_type_postgres.sql",
    "jd/settlement_income/85_dws_jd_settlement_income_shop_daily_type_postgres.sql",
    "ks/settlement_income/97_dws_ks_settlement_income_shop_daily_type_postgres.sql",
    "pdd/settlement_income/109_dws_pdd_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/68_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_expense/124_dwd_wechat_channels_settlement_expense_event_detail_postgres.sql",
    "wechat_channels/settlement_expense/125_dws_wechat_channels_settlement_expense_shop_daily_type_postgres.sql",
    "douyin/settlement_expense/73_dws_douyin_settlement_expense_shop_daily_type_postgres.sql",
    "jd/settlement_expense/89_dws_jd_settlement_expense_shop_daily_type_postgres.sql",
    "ks/settlement_expense/101_dws_ks_settlement_expense_shop_daily_type_postgres.sql",
    "pdd/settlement_expense/113_dws_pdd_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/74_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_net/128_dwd_wechat_channels_settlement_net_event_detail_postgres.sql",
    "wechat_channels/settlement_net/129_dws_wechat_channels_settlement_net_shop_daily_postgres.sql",
    "douyin/settlement_net/79_dws_douyin_settlement_net_shop_daily_postgres.sql",
    "jd/settlement_net/93_dws_jd_settlement_net_shop_daily_postgres.sql",
    "ks/settlement_net/105_dws_ks_settlement_net_shop_daily_postgres.sql",
    "pdd/settlement_net/117_dws_pdd_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/80_ads_settlement_net_company_shop_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "wechat_channels/settlement_income/122_refresh_dwd_wechat_channels_settlement_income_event_detail_postgres.sql",
    "wechat_channels/settlement_income/123_refresh_dws_wechat_channels_settlement_income_shop_daily_type_postgres.sql",
    "ads/settlement_income/71_refresh_ads_settlement_income_company_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_expense/126_refresh_dwd_wechat_channels_settlement_expense_event_detail_postgres.sql",
    "wechat_channels/settlement_expense/127_refresh_dws_wechat_channels_settlement_expense_shop_daily_type_postgres.sql",
    "ads/settlement_expense/77_refresh_ads_settlement_expense_company_shop_daily_type_postgres.sql",
    "wechat_channels/settlement_net/130_refresh_dwd_wechat_channels_settlement_net_event_detail_postgres.sql",
    "wechat_channels/settlement_net/131_refresh_dws_wechat_channels_settlement_net_shop_daily_postgres.sql",
    "ads/settlement_net/83_refresh_ads_settlement_net_company_shop_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_row_no", "row_hash", "ingest_time",
    "流水单号", "记账时间", "动帐类型", "收支类型", "收支金额", "账户余额",
    "关联订单号", "关联售后单号", "关联提现单号", "关联保单号", "关联礼物单号", "详情",
}
NEW_TABLES = [
    ("dwd", "dwd_wechat_channels_settlement_income_event_detail"),
    ("dws", "dws_wechat_channels_settlement_income_shop_daily_type"),
    ("dwd", "dwd_wechat_channels_settlement_expense_event_detail"),
    ("dws", "dws_wechat_channels_settlement_expense_shop_daily_type"),
    ("dwd", "dwd_wechat_channels_settlement_net_event_detail"),
    ("dws", "dws_wechat_channels_settlement_net_shop_daily"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新视频号结算收入、支出和结算净额指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
    if file_names==PREPARE_SQL_FILES:
        prepare_finance_sources(cursor,'wechat_channels')


def validate_ods(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_wechat_channels_settlement_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_wechat_channels_settlement_raw")
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema='ods' AND table_name='ods_wechat_channels_settlement_raw'"""
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"视频号结算ODS缺少必需字段：{', '.join(missing_columns)}")

    flow_no = sql.Identifier("流水单号")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*),COUNT(DISTINCT r.id),COUNT(DISTINCT r.row_hash),"
            "COUNT(DISTINCT (c.shop_identity_key,NULLIF(BTRIM(r.{}),''))),COUNT(DISTINCT r.batch_id) "
            "FROM common.v_current_wechat_channels_settlement_raw r "
            "JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id"
        ).format(flow_no)
    )
    source_rows, unique_ids, unique_hashes, unique_flows, batch_count = cursor.fetchone()
    if source_rows == 0:
        raise RuntimeError("视频号结算ODS无数据，停止刷新")
    if source_rows != unique_ids or source_rows != unique_hashes or source_rows != unique_flows:
        raise RuntimeError(
            f"ODS流水粒度重复：rows={source_rows},ids={unique_ids},hashes={unique_hashes},flows={unique_flows}"
        )

    amount = sql.Identifier("收支金额")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM ods.ods_wechat_channels_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}),''),'-') IS NULL OR BTRIM({}) !~ %s"
        ).format(amount, amount),
        (r"^-?\d+(\.\d+)?$",),
    )
    invalid_amounts = cursor.fetchone()[0]
    if invalid_amounts:
        raise RuntimeError(f"收支金额为空或解析失败：{invalid_amounts}条")

    direction = sql.Identifier("收支类型")
    movement_type = sql.Identifier("动帐类型")
    cursor.execute(
        sql.SQL(
            """
            SELECT
              COUNT(*) FILTER (WHERE BTRIM({direction}) NOT IN (%s,%s)),
              COUNT(*) FILTER (WHERE BTRIM({amount})::numeric<=0),
              COUNT(*) FILTER (WHERE NULLIF(BTRIM({movement_type}),'') IS NULL)
            FROM ods.ods_wechat_channels_settlement_raw
            """
        ).format(direction=direction, amount=amount, movement_type=movement_type),
        ("收入", "支出"),
    )
    direction_errors, nonpositive_amounts, blank_types = cursor.fetchone()
    if any((direction_errors, nonpositive_amounts, blank_types)):
        raise RuntimeError(
            f"方向、金额正数或动帐类型校验失败：{direction_errors}/{nonpositive_amounts}/{blank_types}"
        )

    accounting_time = sql.Identifier("记账时间")
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) FROM ods.ods_wechat_channels_settlement_raw "
            "WHERE NULLIF(NULLIF(BTRIM({}),''),'-') IS NULL OR BTRIM({}) !~ %s"
        ).format(accounting_time, accounting_time),
        (r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",),
    )
    invalid_dates = cursor.fetchone()[0]
    if invalid_dates:
        raise RuntimeError(f"记账时间为空或格式非法：{invalid_dates}条")
    return source_rows, batch_count


def validate_batch_shop_mapping(cursor) -> list[tuple]:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id,COUNT(*) source_rows
            FROM ods.ods_wechat_channels_settlement_raw GROUP BY batch_id
        )
        SELECT b.batch_id,b.source_rows,COUNT(c.batch_id),MAX(c.shop_code),
               MAX(c.shop_name),MAX(c.shop_mapping_status)
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id=b.batch_id AND c.platform_code='wechat_channels'
         AND c.target_table='ods_wechat_channels_settlement_raw'
         AND c.shop_mapping_status='mapped'
        GROUP BY b.batch_id,b.source_rows ORDER BY b.batch_id NULLS FIRST
        """
    )
    mappings = cursor.fetchall()
    invalid = [row for row in mappings if row[0] is None or row[2] != 1]
    if invalid:
        raise RuntimeError(f"视频号结算ODS存在未映射或冲突批次：{invalid}")
    return mappings


def validate_ads_bidirectional(cursor, metric: str) -> int:
    if metric == "income":
        cursor.execute(
            """
            WITH expected AS (
              SELECT d.stat_date,d.platform_code,COALESCE(m.company_code,'unmapped') company_code,
                     d.shop_code,d.income_type_code,ROUND(SUM(d.income_amount),2) amount
              FROM dws.dws_wechat_channels_settlement_income_shop_daily_type d
              LEFT JOIN dim.dim_platform_shop_company m
                ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
               AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
              GROUP BY 1,2,3,4,5
            ), actual AS (
              SELECT stat_date,platform_code,company_code,shop_code,income_type_code,income_amount amount
              FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='wechat_channels'
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
              FROM dws.dws_wechat_channels_settlement_expense_shop_daily_type d
              LEFT JOIN dim.dim_platform_shop_company m
                ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
               AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
              GROUP BY 1,2,3,4,5
            ), actual AS (
              SELECT stat_date,platform_code,company_code,shop_code,expense_type_code,expense_amount amount
              FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='wechat_channels'
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
              FROM dws.dws_wechat_channels_settlement_net_shop_daily d
              LEFT JOIN dim.dim_platform_shop_company m
                ON m.platform_code=d.platform_code AND m.shop_code=d.shop_code AND m.is_active
               AND d.stat_date>=m.valid_from AND (m.valid_to IS NULL OR d.stat_date<=m.valid_to)
              GROUP BY 1,2,3,4
            ), actual AS (
              SELECT stat_date,platform_code,company_code,shop_code,income_amount,expense_amount,
                     settlement_net_amount,source_settlement_amount,validation_difference_amount
              FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='wechat_channels'
            )
            SELECT COUNT(*) FROM (((SELECT * FROM expected EXCEPT SELECT * FROM actual)
              UNION ALL (SELECT * FROM actual EXCEPT SELECT * FROM expected))) x
            """
        )
    return cursor.fetchone()[0]


def validate_pipeline(cursor, source_rows: int) -> dict[str, object]:
    cursor.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM dwd.dwd_wechat_channels_settlement_income_event_detail),
          (SELECT COUNT(*) FROM dwd.dwd_wechat_channels_settlement_expense_event_detail),
          (SELECT COUNT(*) FROM dwd.dwd_wechat_channels_settlement_net_event_detail),
          (SELECT COUNT(*)-COUNT(DISTINCT source_id) FROM dwd.dwd_wechat_channels_settlement_net_event_detail),
          (SELECT COUNT(*)-COUNT(DISTINCT (shop_identity_key,flow_no)) FROM dwd.dwd_wechat_channels_settlement_net_event_detail)
        """
    )
    income_dwd_rows,expense_dwd_rows,net_dwd_rows,duplicate_ids,duplicate_flows = cursor.fetchone()
    if (income_dwd_rows,expense_dwd_rows,net_dwd_rows) != (source_rows,source_rows,source_rows):
        raise RuntimeError(f"DWD行数不等于ODS：{income_dwd_rows}/{expense_dwd_rows}/{net_dwd_rows}!={source_rows}")
    if duplicate_ids or duplicate_flows:
        raise RuntimeError(f"DWD稳定粒度重复：source_id={duplicate_ids},flow_no={duplicate_flows}")

    cursor.execute(
        """
        SELECT
          COUNT(*) FILTER (WHERE settlement_net_amount<>income_amount-expense_amount),
          COUNT(*) FILTER (WHERE source_settlement_amount<>
            CASE WHEN income_expense_direction='收入' THEN source_amount ELSE -source_amount END),
          COUNT(*) FILTER (WHERE validation_difference_amount<>
            settlement_net_amount-source_settlement_amount),
          COUNT(*) FILTER (WHERE validation_difference_amount<>0),
          COUNT(*) FILTER (WHERE
            (income_expense_direction='收入' AND (income_amount<>source_amount OR expense_amount<>0)) OR
            (income_expense_direction='支出' AND (income_amount<>0 OR expense_amount<>source_amount)))
        FROM dwd.dwd_wechat_channels_settlement_net_event_detail
        """
    )
    formula_errors = cursor.fetchone()
    if any(formula_errors):
        raise RuntimeError(f"DWD方向或净额公式校验失败：{formula_errors}")

    cursor.execute(
        """SELECT COUNT(*),COALESCE(SUM(income_amount),0),COALESCE(SUM(included_event_count),0)
           FROM dws.dws_wechat_channels_settlement_income_shop_daily_type"""
    )
    income_dws_rows,dws_income,income_events = cursor.fetchone()
    cursor.execute(
        """SELECT COUNT(*),COALESCE(SUM(expense_amount),0),COALESCE(SUM(included_event_count),0)
           FROM dws.dws_wechat_channels_settlement_expense_shop_daily_type"""
    )
    expense_dws_rows,dws_expense,expense_events = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*),MIN(stat_date),MAX(stat_date),COALESCE(SUM(income_amount),0),
               COALESCE(SUM(expense_amount),0),COALESCE(SUM(settlement_net_amount),0),
               COALESCE(SUM(source_settlement_amount),0),
               COALESCE(SUM(validation_difference_amount),0),COALESCE(SUM(included_event_count),0)
        FROM dws.dws_wechat_channels_settlement_net_shop_daily
        """
    )
    (net_dws_rows,min_date,max_date,net_income,net_expense,dws_net,source_net,
     validation_difference,included_events) = cursor.fetchone()
    if income_events+expense_events != source_rows or included_events != source_rows:
        raise RuntimeError(
            f"全部动账流水未完整纳入：income={income_events},expense={expense_events},"
            f"net={included_events},source={source_rows}"
        )
    if (dws_income,dws_expense,dws_net) != (net_income,net_expense,net_income-net_expense):
        raise RuntimeError(
            f"三套DWS汇总不一致：income={dws_income}/{net_income},"
            f"expense={dws_expense}/{net_expense},net={dws_net}"
        )
    if dws_net != source_net or validation_difference != 0:
        raise RuntimeError(f"净额核验失败：net={dws_net},source={source_net},diff={validation_difference}")

    cursor.execute(
        """
        SELECT
          (SELECT COALESCE(SUM(income_amount),0) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='wechat_channels'),
          (SELECT COALESCE(SUM(expense_amount),0) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='wechat_channels'),
          (SELECT COALESCE(SUM(settlement_net_amount),0) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='wechat_channels'),
          (SELECT COUNT(*) FROM ads.ads_settlement_income_company_shop_daily_type WHERE platform_code='wechat_channels' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_expense_company_shop_daily_type WHERE platform_code='wechat_channels' AND company_code='unmapped'),
          (SELECT COUNT(*) FROM ads.ads_settlement_net_company_shop_daily WHERE platform_code='wechat_channels' AND company_code='unmapped')
        """
    )
    ads_income,ads_expense,ads_net,unmapped_income,unmapped_expense,unmapped_net = cursor.fetchone()
    if (ads_income,ads_expense,ads_net) != (dws_income,dws_expense,dws_net):
        raise RuntimeError(
            f"DWS/ADS汇总不一致：DWS={dws_income}/{dws_expense}/{dws_net},"
            f"ADS={ads_income}/{ads_expense}/{ads_net}"
        )
    bidirectional_errors = tuple(validate_ads_bidirectional(cursor,m) for m in ("income","expense","net"))
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
          SELECT *,ROW_NUMBER() OVER(PARTITION BY movement_type,income_expense_direction ORDER BY source_id) rn
          FROM dwd.dwd_wechat_channels_settlement_net_event_detail
        )
        SELECT movement_type,income_expense_direction,source_id,flow_no,stat_date,
               income_amount,expense_amount,settlement_net_amount,
               source_settlement_amount,validation_difference_amount
        FROM ranked WHERE rn=1 ORDER BY movement_type,income_expense_direction
        """
    )
    samples = cursor.fetchall()
    if len(samples)<5:
        raise RuntimeError(f"公式抽样场景不足5类：{samples}")
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
        "date_range":(min_date,max_date),"income":dws_income,"expense":dws_expense,
        "net":dws_net,"source_net":source_net,"difference":validation_difference,
        "unmapped":(unmapped_income,unmapped_expense,unmapped_net),
        "bidirectional_errors":bidirectional_errors,"duplicate_ads_keys":duplicate_ads_keys,
        "samples":samples,"platform_income_totals":platform_income_totals,
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name,table_name in NEW_TABLES:
        cursor.execute(
            """SELECT obj_description(c.oid,'pg_class') FROM pg_class c
               JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname=%s AND c.relname=%s""",
            (schema_name,table_name),
        )
        row=cursor.fetchone()
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
    conn=psycopg2.connect(host=args.host,port=args.port,dbname=args.dbname,user=args.user,password=args.password)
    try:
        with conn.cursor() as cursor:
            execute_files(cursor,PREPARE_SQL_FILES)
            source_rows,batch_count=validate_ods(cursor)
            mappings=validate_batch_shop_mapping(cursor)
            execute_files(cursor,CREATE_SQL_FILES)
            execute_files(cursor,REFRESH_SQL_FILES)
            result=validate_pipeline(cursor,source_rows)
            validate_comments(cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS来源行数/批次数：{source_rows}/{batch_count}")
    print("批次店铺映射：")
    for batch_id,rows,_,shop_code,shop_name,status in mappings:
        print(f"  批次{batch_id}：{rows}行 -> {shop_code} / {shop_name} / {status}")
    print(f"DWD行数（收入/支出/净额）：{result['dwd_rows']}")
    print(f"DWS行数（收入类型/支出类型/净额日）：{result['dws_rows']}")
    print(f"DWS收入/支出/净额纳入事件数：{result['events']}")
    print(f"ADS视频号日期范围：{result['date_range'][0]} 至 {result['date_range'][1]}")
    print(f"视频号收入金额：{result['income']:.2f}")
    print(f"视频号支出金额：{result['expense']:.2f}")
    print(f"视频号计算结算净额：{result['net']:.2f}")
    print(f"视频号源带符号流水合计：{result['source_net']:.2f}")
    print(f"视频号净额核验差额：{result['difference']:.2f}")
    print(f"ADS未匹配公司行数（收入/支出/净额）：{result['unmapped']}")
    print(f"DWS/ADS双向差异（收入/支出/净额）：{result['bidirectional_errors']}")
    print(f"ADS重复主键组（收入/支出/净额）：{result['duplicate_ads_keys']}")
    print(f"跨平台收入合计：{result['platform_income_totals']}")
    print("公式抽样（动账类型,方向,source_id,流水号,日期,收入,支出,净额,源带符号金额,差额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())

