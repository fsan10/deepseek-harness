#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新抖音GSV指标专属的DWD、DWS和ADS。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.report_sources import prepare_report_sources

SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "douyin/gsv/26_dwd_douyin_gsv_order_detail_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
    "douyin/gsv/29_refresh_dwd_douyin_gsv_order_detail_postgres.sql",
    "douyin/gsv/30_refresh_dws_douyin_gsv_shop_daily_postgres.sql",
    "ads/gsv/31_refresh_ads_gsv_company_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_row_no",
    "ingest_time",
    "主订单编号",
    "子订单编号",
    "所属门店ID",
    "订单提交时间",
    "支付完成时间",
    "订单状态",
    "售后状态",
    "订单应付金额",
    "优惠总金额",
    "商家实际承担优惠金额",
    "商家优惠",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新抖音GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods(cursor) -> int:
    cursor.execute("SELECT to_regclass('ods.ods_douyin_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_douyin_order_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_douyin_order_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"抖音订单ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute("SELECT COUNT(*) FROM common.v_current_douyin_order_raw")
    source_rows = cursor.fetchone()[0]
    if source_rows == 0:
        raise RuntimeError("ods.ods_douyin_order_raw没有数据，停止刷新指标层")
    return source_rows


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
            prepare_report_sources(cursor, ('douyin',), pdd_settlement=False)
            source_rows = validate_ods(cursor)
            for file_name in SQL_FILES:
                sql_path = SQL_DIR / file_name
                cursor.execute(sql_path.read_text(encoding="utf-8"))

            cursor.execute("SELECT COUNT(*) FROM dwd.dwd_douyin_gsv_order_detail")
            dwd_rows = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(included_sub_order_count), 0)
                FROM dws.dws_douyin_gsv_shop_daily
                """
            )
            dws_rows, included_sub_orders = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*), MIN(stat_date), MAX(stat_date), COALESCE(SUM(gsv_amount), 0)
                FROM ads.ads_gsv_company_daily
                WHERE platform_code = 'douyin'
                """
            )
            ads_rows, min_date, max_date, total_gsv = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS来源行数：{source_rows}")
    print(f"DWD明细行数：{dwd_rows}")
    print(f"DWS汇总行数：{dws_rows}")
    print(f"DWS纳入子订单数：{included_sub_orders}")
    print(f"抖音ADS公司店铺日行数：{ads_rows}")
    print(f"抖音ADS日期范围：{min_date} 至 {max_date}")
    print(f"抖音ADS GSV合计：{total_gsv:.2f}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
