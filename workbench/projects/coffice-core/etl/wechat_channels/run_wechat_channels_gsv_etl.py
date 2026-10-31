#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新视频号GSV指标专属DWD、DWS和共享GSV ADS。"""

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
    "wechat_channels/gsv/58_dwd_wechat_channels_gsv_order_detail_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "wechat_channels/gsv/60_refresh_dwd_wechat_channels_gsv_order_detail_postgres.sql",
    "wechat_channels/gsv/61_refresh_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "ads/gsv/31_refresh_ads_gsv_company_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no",
    "ingest_time", "订单号", "订单下单时间", "支付时间", "订单状态", "商品售后",
    "订单实际收款金额", "活动商家补贴", "订单实际支付金额", "商品平台券优惠",
    "商品已退款金额",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新视频号GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods_and_batches(cursor) -> tuple[int, int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_wechat_channels_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_wechat_channels_order_raw")

    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_wechat_channels_order_raw'
        """
    )
    missing = sorted(REQUIRED_ODS_COLUMNS - {row[0] for row in cursor.fetchall()})
    if missing:
        raise RuntimeError(f"视频号订单ODS缺少必需字段：{', '.join(missing)}")

    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_wechat_channels_order_raw
        """
    )
    source_rows, source_orders = cursor.fetchone()
    if not source_rows or not source_orders:
        raise RuntimeError("视频号订单ODS没有有效订单数据")

    cursor.execute(
        r"""
        WITH cleaned AS (
            SELECT
                NULLIF(regexp_replace(BTRIM("订单实际收款金额"), '[,\s￥¥元]', '', 'g'), '') AS received_raw,
                NULLIF(regexp_replace(BTRIM("订单实际支付金额"), '[,\s￥¥元]', '', 'g'), '') AS paid_raw,
                NULLIF(NULLIF(regexp_replace(BTRIM("活动商家补贴"), '[,\s￥¥元]', '', 'g'), ''), '-') AS subsidy_raw,
                NULLIF(NULLIF(regexp_replace(BTRIM("商品平台券优惠"), '[,\s￥¥元]', '', 'g'), ''), '-') AS coupon_raw,
                NULLIF(NULLIF(regexp_replace(BTRIM("商品已退款金额"), '[,\s￥¥元]', '', 'g'), ''), '-') AS refund_raw,
                NULLIF(NULLIF(BTRIM("支付时间"), ''), '-') AS paid_at_raw,
                NULLIF(NULLIF(BTRIM("订单下单时间"), ''), '-') AS created_at_raw
            FROM common.v_current_wechat_channels_order_raw
        )
        SELECT
            COUNT(*) FILTER (WHERE received_raw IS NULL OR received_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE paid_raw IS NULL OR paid_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE subsidy_raw IS NOT NULL AND subsidy_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE coupon_raw IS NOT NULL AND coupon_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE refund_raw IS NOT NULL AND refund_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE paid_at_raw IS NULL AND created_at_raw IS NULL)
        FROM cleaned
        """
    )
    invalid_received, invalid_paid, invalid_subsidy, invalid_coupon, invalid_refund, missing_dates = cursor.fetchone()
    if any((invalid_received, invalid_paid, invalid_subsidy, invalid_coupon, invalid_refund, missing_dates)):
        raise RuntimeError(
            f"视频号ODS质量校验失败：实际收款无效{invalid_received}条，"
            f"实际支付无效{invalid_paid}条，活动商家补贴无效{invalid_subsidy}条，"
            f"平台券无效{invalid_coupon}条，退款金额无效{invalid_refund}条，"
            f"支付和下单时间同时缺失{missing_dates}条"
        )

    cursor.execute(
        """
        SELECT COUNT(DISTINCT raw.batch_id)
        FROM common.v_current_wechat_channels_order_raw raw
        WHERE NOT EXISTS (
            SELECT 1 FROM common.v_ingest_batch_shop_context ctx
            WHERE ctx.batch_id = raw.batch_id
              AND ctx.platform_code = 'wechat_channels'
              AND ctx.target_table = 'ods_wechat_channels_order_raw'
              AND ctx.shop_mapping_status = 'mapped'
              AND ctx.ingest_status = 'success'
              AND ctx.shop_code IS NOT NULL
              AND ctx.shop_identity_key IS NOT NULL
              AND ctx.company_code IS NOT NULL
        )
        """
    )
    invalid_batches = cursor.fetchone()[0]
    if invalid_batches:
        raise RuntimeError(f"视频号订单存在{invalid_batches}个未映射、冲突或DIM未命中的导入批次")

    cursor.execute(
        r"""
        WITH normalized AS (
            SELECT NULLIF(BTRIM("订单号"), '') AS order_no, batch_id, ingest_time,
                   NULLIF(BTRIM("订单状态"), '') AS order_status,
                   NULLIF(NULLIF(BTRIM("支付时间"), ''), '-') AS paid_at,
                   NULLIF(NULLIF(BTRIM("订单下单时间"), ''), '-') AS created_at,
                   NULLIF(regexp_replace(BTRIM("订单实际收款金额"), '[,\s￥¥元]', '', 'g'), '') AS received,
                   NULLIF(regexp_replace(BTRIM("订单实际支付金额"), '[,\s￥¥元]', '', 'g'), '') AS paid
            FROM common.v_current_wechat_channels_order_raw
            WHERE NULLIF(BTRIM("订单号"), '') IS NOT NULL
        ), inconsistent AS (
            SELECT order_no FROM normalized GROUP BY order_no
            HAVING COUNT(DISTINCT order_status) > 1 OR COUNT(DISTINCT paid_at) > 1
                OR COUNT(DISTINCT created_at) > 1 OR COUNT(DISTINCT received) > 1
                OR COUNT(DISTINCT paid) > 1
        )
        SELECT (SELECT COUNT(*) FROM normalized), (SELECT COUNT(*) FROM inconsistent)
        """
    )
    latest_source_rows, inconsistent_orders = cursor.fetchone()
    if inconsistent_orders:
        raise RuntimeError(f"视频号ODS有{inconsistent_orders}个订单的订单级字段在商品行间不一致")
    return source_rows, source_orders, latest_source_rows


def run_pipeline(args: argparse.Namespace) -> None:
    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password
    )
    try:
        with conn.cursor() as cursor:
            prepare_report_sources(cursor, ('wechat_channels',), pdd_settlement=False)
            for file_name in SETUP_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
            source_rows, source_orders, latest_source_rows = validate_ods_and_batches(cursor)
            for file_name in REFRESH_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT COUNT(DISTINCT source_id)
                FROM dwd.dwd_wechat_channels_gsv_order_detail d
                CROSS JOIN LATERAL UNNEST(d.source_ids) AS source_id
                """
            )
            traced_ids = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(source_line_count), 0),
                       COUNT(*) FILTER (WHERE order_status <> '已完成'),
                       COUNT(*) FILTER (WHERE after_sale_statuses && ARRAY['退货退款完成','退款完成']::TEXT[]),
                       COUNT(*) FILTER (WHERE stat_date_source = 'payment_time'),
                       COUNT(*) FILTER (WHERE stat_date_source = 'order_time'),
                       COUNT(*) FILTER (WHERE shop_code_source <> 'batch_context')
                FROM dwd.dwd_wechat_channels_gsv_order_detail
                """
            )
            (
                dwd_rows, dwd_source_lines, non_completed_orders, completed_refund_orders,
                payment_rows, fallback_rows, invalid_mapping,
            ) = cursor.fetchone()
            if dwd_rows != source_orders or dwd_source_lines != latest_source_rows or traced_ids != latest_source_rows:
                raise RuntimeError(
                    f"DWD粒度/追溯校验失败：预期{source_orders}单/{latest_source_rows}源行，"
                    f"实际{dwd_rows}单/{dwd_source_lines}源行/{traced_ids}唯一源ID"
                )
            if invalid_mapping:
                raise RuntimeError(f"DWD存在{invalid_mapping}条非批次上下文店铺映射")

            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(source_line_count), 0),
                       COALESCE(SUM(actual_received_amount), 0),
                       COALESCE(SUM(activity_merchant_subsidy_amount), 0),
                       COALESCE(SUM(actual_received_amount), 0)
                FROM dwd.dwd_wechat_channels_gsv_order_detail
                WHERE stat_date IS NOT NULL AND COALESCE(BTRIM(order_status), '') = '已完成'
                  AND NOT (after_sale_statuses && ARRAY['退货退款完成','退款完成']::TEXT[])
                """
            )
            expected_orders, expected_lines, expected_received, expected_subsidy, expected_gsv = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(included_order_count), 0), COALESCE(SUM(source_line_count), 0),
                       COALESCE(SUM(actual_received_amount), 0),
                       COALESCE(SUM(activity_merchant_subsidy_amount), 0), COALESCE(SUM(gsv_amount), 0)
                FROM dws.dws_wechat_channels_gsv_shop_daily
                """
            )
            dws_rows, included_orders, included_lines, dws_received, dws_subsidy, dws_gsv = cursor.fetchone()
            if (included_orders, included_lines, dws_received, dws_subsidy, dws_gsv) != (
                expected_orders, expected_lines, expected_received, expected_subsidy, expected_gsv
            ):
                raise RuntimeError("视频号DWS与DWD按已确认口径重算不一致")

            cursor.execute(
                """
                SELECT COUNT(*), MIN(stat_date), MAX(stat_date), COALESCE(SUM(gsv_amount), 0),
                       COUNT(*) FILTER (WHERE company_code = 'unmapped')
                FROM ads.ads_gsv_company_daily WHERE platform_code = 'wechat_channels'
                """
            )
            ads_rows, min_date, max_date, ads_gsv, unmapped_rows = cursor.fetchone()
            if ads_gsv != dws_gsv or unmapped_rows:
                raise RuntimeError(f"视频号ADS验收失败：DWS={dws_gsv}，ADS={ads_gsv}，未匹配公司={unmapped_rows}")

            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns c
                WHERE c.table_schema IN ('dwd','dws','ads')
                  AND c.table_name IN ('dwd_wechat_channels_gsv_order_detail',
                                       'dws_wechat_channels_gsv_shop_daily',
                                       'ads_gsv_company_daily')
                  AND col_description((quote_ident(c.table_schema)||'.'||quote_ident(c.table_name))::regclass, c.ordinal_position) IS NULL
                """
            )
            missing_comments = cursor.fetchone()[0]
            if missing_comments:
                raise RuntimeError(f"指标链路存在{missing_comments}个缺少注释的字段")

            cursor.execute("SELECT COUNT(*), COALESCE(SUM(gsv_amount), 0) FROM ads.ads_gsv_company_daily")
            all_ads_rows, all_platform_gsv = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS商品行/唯一订单：{source_rows}/{source_orders}")
    print(f"DWD订单/最新批次源行/唯一源ID：{dwd_rows}/{dwd_source_lines}/{traced_ids}")
    print(f"DWD日期来源：支付时间{payment_rows}单，下单时间兜底{fallback_rows}单")
    print(
        f"DWS排除非已完成订单：{non_completed_orders}；"
        f"含完成退款售后的订单：{completed_refund_orders}"
    )
    print(f"DWS日汇总/纳入订单/源商品行：{dws_rows}/{included_orders}/{included_lines}")
    print(f"纳入订单实际收款/活动商家补贴：{Decimal(dws_received):.2f}/{Decimal(dws_subsidy):.2f}")
    print(f"视频号ADS日期范围：{min_date} 至 {max_date}")
    print(f"视频号ADS公司店铺日行数/GSV：{ads_rows}/{Decimal(ads_gsv):.2f}")
    print(f"全平台GSV ADS：{all_ads_rows}行/{Decimal(all_platform_gsv):.2f}元")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
