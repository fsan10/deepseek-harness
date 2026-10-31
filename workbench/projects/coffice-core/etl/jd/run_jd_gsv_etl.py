#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新京东GSV指标专属的DWD、DWS和共享GSV ADS。"""

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

from etl.common.report_sources import prepare_report_sources

SETUP_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "jd/gsv/44_dwd_jd_gsv_order_detail_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "jd/gsv/46_refresh_dwd_jd_gsv_order_detail_postgres.sql",
    "jd/gsv/47_refresh_dws_jd_gsv_shop_daily_postgres.sql",
    "ads/gsv/31_refresh_ads_gsv_company_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id",
    "batch_id",
    "source_file_name",
    "source_sheet_name",
    "source_row_no",
    "ingest_time",
    "订单号",
    "应付金额",
    "订单金额",
    "商家应收",
    "订单状态",
    "订单类型",
    "下单时间",
    "付款确认时间",
    "履约门店ID",
    "下单门店Id",
    "门店名称",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新京东GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods_and_dim(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_jd_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_jd_order_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_jd_order_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"京东订单ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_jd_order_raw
        """
    )
    source_rows, source_orders = cursor.fetchone()
    if source_rows == 0:
        raise RuntimeError("ods.ods_jd_order_raw没有数据，停止刷新指标层")
    if source_orders == 0:
        raise RuntimeError("京东订单ODS没有有效订单号")

    cursor.execute(
        r"""
        WITH cleaned AS (
            SELECT
                NULLIF(regexp_replace(BTRIM("应付金额"), '[,\s￥¥元]', '', 'g'), '')
                    AS payable_raw,
                NULLIF(regexp_replace(BTRIM("订单金额"), '[,\s￥¥元]', '', 'g'), '')
                    AS order_amount_raw,
                NULLIF(NULLIF(BTRIM("付款确认时间"), ''), '-') AS paid_at_raw,
                NULLIF(NULLIF(BTRIM("下单时间"), ''), '-') AS created_at_raw
            FROM common.v_current_jd_order_raw
        )
        SELECT
            COUNT(*) FILTER (
                WHERE payable_raw IS NULL
                   OR payable_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (
                WHERE order_amount_raw IS NULL
                   OR order_amount_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (WHERE paid_at_raw IS NULL AND created_at_raw IS NULL)
        FROM cleaned
        """
    )
    invalid_payable, invalid_order_amount, missing_stat_dates = cursor.fetchone()
    if invalid_payable or invalid_order_amount or missing_stat_dates:
        raise RuntimeError(
            "京东订单ODS质量校验失败："
            f"应付金额无效{invalid_payable}条，"
            f"订单金额无效{invalid_order_amount}条，"
            f"付款确认和下单时间同时缺失{missing_stat_dates}条"
        )

    cursor.execute(
        r"""
        WITH normalized AS (
            SELECT
                NULLIF(BTRIM("订单号"), '') AS order_no,
                batch_id,
                ingest_time,
                NULLIF(regexp_replace(BTRIM("应付金额"), '[,\s￥¥元]', '', 'g'), '')
                    AS payable_raw,
                NULLIF(regexp_replace(BTRIM("订单金额"), '[,\s￥¥元]', '', 'g'), '')
                    AS order_amount_raw,
                NULLIF(BTRIM("订单状态"), '') AS order_status,
                NULLIF(NULLIF(BTRIM("付款确认时间"), ''), '-') AS paid_at_raw,
                NULLIF(NULLIF(BTRIM("下单时间"), ''), '-') AS created_at_raw
            FROM common.v_current_jd_order_raw
            WHERE NULLIF(BTRIM("订单号"), '') IS NOT NULL
        )
        SELECT COUNT(*)
        FROM (
            SELECT n.order_no
            FROM normalized n
            GROUP BY n.order_no
            HAVING COUNT(DISTINCT n.payable_raw) > 1
                OR COUNT(DISTINCT n.order_amount_raw) > 1
                OR COUNT(DISTINCT n.order_status) > 1
                OR COUNT(DISTINCT n.paid_at_raw) > 1
                OR COUNT(DISTINCT n.created_at_raw) > 1
        ) inconsistent_orders
        """
    )
    inconsistent_orders = cursor.fetchone()[0]
    if inconsistent_orders:
        raise RuntimeError(
            f"京东ODS有{inconsistent_orders}个订单的多商品行存在订单级金额、状态或日期不一致"
        )

    cursor.execute(
        """
        SELECT COUNT(DISTINCT raw.batch_id)
        FROM common.v_current_jd_order_raw raw
        WHERE NOT EXISTS (
            SELECT 1
            FROM common.v_ingest_batch_shop_context ctx
            WHERE ctx.batch_id = raw.batch_id
              AND ctx.platform_code = 'jd'
              AND ctx.shop_mapping_status = 'mapped'
        )
        """
    )
    unmapped_batches = cursor.fetchone()[0]
    if unmapped_batches:
        raise RuntimeError(f"京东订单存在{unmapped_batches}个未映射店铺的导入批次")
    return source_rows, source_orders


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
            prepare_report_sources(cursor, ('jd',), pdd_settlement=False)
            for file_name in SETUP_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
            source_rows, source_orders = validate_ods_and_dim(cursor)
            for file_name in REFRESH_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(DISTINCT order_no),
                    COALESCE(SUM(source_line_count), 0),
                    COUNT(*) FILTER (WHERE stat_date_source = 'payment_confirmation_time'),
                    COUNT(*) FILTER (WHERE stat_date_source = 'order_time'),
                    COUNT(*) FILTER (WHERE shop_code_source <> 'batch_context')
                FROM dwd.dwd_jd_gsv_order_detail
                """
            )
            (
                dwd_rows,
                dwd_orders,
                dwd_source_lines,
                payment_date_orders,
                order_date_fallback_orders,
                invalid_mapping_orders,
            ) = cursor.fetchone()
            if dwd_rows != source_orders or dwd_orders != source_orders:
                raise RuntimeError(
                    f"DWD粒度校验失败：ODS唯一订单{source_orders}，"
                    f"DWD行数{dwd_rows}，DWD唯一订单{dwd_orders}"
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE COALESCE(order_status, '') LIKE '(删除)%'),
                    COUNT(*) FILTER (WHERE COALESCE(order_status, '') NOT LIKE '(删除)%'),
                    COALESCE(SUM(payable_amount) FILTER (
                        WHERE COALESCE(order_status, '') NOT LIKE '(删除)%'
                    ), 0)
                FROM dwd.dwd_jd_gsv_order_detail
                """
            )
            excluded_orders, expected_included_orders, expected_gsv = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(included_order_count), 0),
                    COALESCE(SUM(source_line_count), 0),
                    COALESCE(SUM(gsv_amount), 0)
                FROM dws.dws_jd_gsv_shop_daily
                """
            )
            dws_rows, included_orders, included_source_lines, dws_gsv = cursor.fetchone()
            if included_orders != expected_included_orders or dws_gsv != expected_gsv:
                raise RuntimeError(
                    f"DWS重算不一致：预期{expected_included_orders}单/{expected_gsv}元，"
                    f"实际{included_orders}单/{dws_gsv}元"
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    MIN(stat_date),
                    MAX(stat_date),
                    COALESCE(SUM(gsv_amount), 0),
                    COUNT(*) FILTER (WHERE company_code = 'unmapped'),
                    COALESCE(SUM(gsv_amount) FILTER (WHERE company_code = 'unmapped'), 0)
                FROM ads.ads_gsv_company_daily
                WHERE platform_code = 'jd'
                """
            )
            ads_rows, min_date, max_date, ads_gsv, unmapped_rows, unmapped_gsv = cursor.fetchone()
            if ads_gsv != dws_gsv:
                raise RuntimeError(f"ADS与DWS不一致：DWS={dws_gsv}，ADS={ads_gsv}")
            if unmapped_rows:
                raise RuntimeError(
                    f"京东ADS存在{unmapped_rows}条未匹配公司数据，金额{unmapped_gsv}"
                )

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT stat_date, platform_code, company_code, shop_code
                    FROM ads.ads_gsv_company_daily
                    GROUP BY stat_date, platform_code, company_code, shop_code
                    HAVING COUNT(*) > 1
                ) duplicate_keys
                """
            )
            ads_duplicate_keys = cursor.fetchone()[0]
            if ads_duplicate_keys:
                raise RuntimeError(f"ADS存在{ads_duplicate_keys}组重复主键")

            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(gsv_amount), 0)
                FROM ads.ads_gsv_company_daily
                """
            )
            all_ads_rows, all_platform_gsv = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS商品行数/唯一订单数：{source_rows}/{source_orders}")
    print(f"DWD订单数/唯一订单数/追溯商品行：{dwd_rows}/{dwd_orders}/{dwd_source_lines}")
    print(f"DWD日期来源：付款确认时间{payment_date_orders}单，下单时间兜底{order_date_fallback_orders}单")
    print(f"DWD非批次上下文映射：{invalid_mapping_orders}单")
    print(f"DWS排除删除状态订单数：{excluded_orders}")
    print(f"DWS汇总行数/纳入订单数/来源商品行：{dws_rows}/{included_orders}/{included_source_lines}")
    print(f"京东ADS公司店铺日行数：{ads_rows}")
    print(f"京东ADS日期范围：{min_date} 至 {max_date}")
    print(f"京东ADS GSV合计：{Decimal(ads_gsv):.2f}")
    print(f"京东ADS未匹配公司：{unmapped_rows}条/{Decimal(unmapped_gsv):.2f}元")
    print(f"全平台GSV ADS：{all_ads_rows}行/{Decimal(all_platform_gsv):.2f}元")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
