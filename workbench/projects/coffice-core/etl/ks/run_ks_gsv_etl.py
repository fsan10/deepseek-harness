#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新快手GSV指标专属的DWD、DWS和共享GSV ADS。"""

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
    "ks/gsv/54_dwd_ks_gsv_order_item_detail_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "ks/gsv/56_refresh_dwd_ks_gsv_order_item_detail_postgres.sql",
    "ks/gsv/57_refresh_dws_ks_gsv_shop_daily_postgres.sql",
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
    "商品ID",
    "SKU编码",
    "订单创建时间",
    "订单支付时间",
    "订单状态",
    "售后状态",
    "实付款",
    "服务门店ID",
    "服务门店名称",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新快手GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods_and_batches(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_ks_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_ks_order_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_ks_order_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"快手订单ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_ks_order_raw
        """
    )
    source_rows, source_orders = cursor.fetchone()
    if source_rows == 0 or source_orders == 0:
        raise RuntimeError("ods.ods_ks_order_raw没有有效订单数据")

    cursor.execute(
        r"""
        WITH cleaned AS (
            SELECT
                NULLIF(regexp_replace(BTRIM("实付款"), '[,\s￥¥元]', '', 'g'), '') AS paid_raw,
                NULLIF(NULLIF(BTRIM("订单支付时间"), ''), '-') AS paid_at_raw,
                NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-') AS created_at_raw
            FROM common.v_current_ks_order_raw
        )
        SELECT
            COUNT(*) FILTER (
                WHERE paid_raw IS NULL
                   OR paid_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (WHERE paid_at_raw IS NULL AND created_at_raw IS NULL)
        FROM cleaned
        """
    )
    invalid_paid, missing_stat_dates = cursor.fetchone()
    if invalid_paid or missing_stat_dates:
        raise RuntimeError(
            "快手订单ODS质量校验失败："
            f"实付款无效{invalid_paid}条，"
            f"支付和创建时间同时缺失{missing_stat_dates}条"
        )

    cursor.execute(
        """
        SELECT COUNT(DISTINCT raw.batch_id)
        FROM common.v_current_ks_order_raw raw
        WHERE NOT EXISTS (
            SELECT 1
            FROM common.v_ingest_batch_shop_context ctx
            WHERE ctx.batch_id = raw.batch_id
              AND ctx.platform_code = 'ks'
              AND ctx.target_table = 'ods_ks_order_raw'
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
        raise RuntimeError(f"快手订单存在{invalid_batches}个未映射、冲突或DIM未命中的导入批次")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM common.v_current_ks_order_raw raw
        INNER JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = raw.batch_id
        WHERE (
                NULLIF(BTRIM(raw."服务门店ID"), '') IS NOT NULL
            AND BTRIM(raw."服务门店ID") <> ctx.shop_code
        ) OR (
                NULLIF(BTRIM(raw."服务门店名称"), '') IS NOT NULL
            AND BTRIM(raw."服务门店名称") <> ctx.shop_name
        )
        """
    )
    source_shop_conflicts = cursor.fetchone()[0]
    if source_shop_conflicts:
        raise RuntimeError(f"快手ODS有{source_shop_conflicts}条源服务门店与批次店铺上下文冲突")
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
            prepare_report_sources(cursor, ('ks',), pdd_settlement=False)
            for file_name in SETUP_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
            source_rows, source_orders = validate_ods_and_batches(cursor)
            for file_name in REFRESH_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(DISTINCT source_id),
                    COUNT(DISTINCT order_no),
                    COUNT(*) FILTER (WHERE stat_date_source = 'payment_time'),
                    COUNT(*) FILTER (WHERE stat_date_source = 'creation_time'),
                    COUNT(*) FILTER (WHERE shop_code_source <> 'batch_context')
                FROM dwd.dwd_ks_gsv_order_item_detail
                """
            )
            (
                dwd_rows,
                dwd_source_ids,
                dwd_orders,
                payment_date_items,
                creation_fallback_items,
                invalid_mapping_items,
            ) = cursor.fetchone()
            if dwd_rows != source_rows or dwd_source_ids != source_rows:
                raise RuntimeError(
                    f"DWD粒度校验失败：ODS行数{source_rows}，"
                    f"DWD行数{dwd_rows}，DWD唯一源ID{dwd_source_ids}"
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE COALESCE(BTRIM(order_status), '') = '交易关闭'),
                    COUNT(*) FILTER (
                        WHERE COALESCE(BTRIM(order_status), '') <> '交易关闭'
                          AND COALESCE(BTRIM(after_sale_status), '') = '退款成功'
                    ),
                    COUNT(*) FILTER (
                        WHERE COALESCE(BTRIM(order_status), '') <> '交易关闭'
                          AND COALESCE(BTRIM(after_sale_status), '') <> '退款成功'
                    ),
                    COUNT(DISTINCT order_no) FILTER (
                        WHERE COALESCE(BTRIM(order_status), '') <> '交易关闭'
                          AND COALESCE(BTRIM(after_sale_status), '') <> '退款成功'
                    ),
                    COALESCE(SUM(paid_amount) FILTER (
                        WHERE COALESCE(BTRIM(order_status), '') <> '交易关闭'
                          AND COALESCE(BTRIM(after_sale_status), '') <> '退款成功'
                    ), 0)
                FROM dwd.dwd_ks_gsv_order_item_detail
                """
            )
            (
                closed_items,
                refunded_items,
                expected_items,
                expected_orders,
                expected_gsv,
            ) = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(included_item_count), 0),
                    COALESCE(SUM(included_order_count), 0),
                    COALESCE(SUM(gsv_amount), 0)
                FROM dws.dws_ks_gsv_shop_daily
                """
            )
            dws_rows, included_items, included_orders, dws_gsv = cursor.fetchone()
            if included_items != expected_items or included_orders != expected_orders or dws_gsv != expected_gsv:
                raise RuntimeError(
                    f"DWS重算不一致：预期{expected_items}行/{expected_orders}单/{expected_gsv}元，"
                    f"实际{included_items}行/{included_orders}单/{dws_gsv}元"
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
                WHERE platform_code = 'ks'
                """
            )
            ads_rows, min_date, max_date, ads_gsv, unmapped_rows, unmapped_gsv = cursor.fetchone()
            if ads_gsv != dws_gsv:
                raise RuntimeError(f"ADS与DWS不一致：DWS={dws_gsv}，ADS={ads_gsv}")
            if unmapped_rows:
                raise RuntimeError(f"快手ADS存在{unmapped_rows}条未匹配公司数据，金额{unmapped_gsv}")

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

            cursor.execute("SELECT COUNT(*), COALESCE(SUM(gsv_amount), 0) FROM ads.ads_gsv_company_daily")
            all_ads_rows, all_platform_gsv = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS商品行数/唯一订单数：{source_rows}/{source_orders}")
    print(f"DWD商品行/唯一源ID/唯一订单：{dwd_rows}/{dwd_source_ids}/{dwd_orders}")
    print(f"DWD日期来源：支付时间{payment_date_items}行，创建时间兜底{creation_fallback_items}行")
    print(f"DWD非批次上下文映射：{invalid_mapping_items}行")
    print(f"DWS排除交易关闭/退款成功商品行：{closed_items}/{refunded_items}")
    print(f"DWS汇总行/纳入商品行/纳入订单：{dws_rows}/{included_items}/{included_orders}")
    print(f"快手ADS公司店铺日行数：{ads_rows}")
    print(f"快手ADS日期范围：{min_date} 至 {max_date}")
    print(f"快手ADS GSV合计：{Decimal(ads_gsv):.2f}")
    print(f"快手ADS未匹配公司：{unmapped_rows}条/{Decimal(unmapped_gsv):.2f}元")
    print(f"全平台GSV ADS：{all_ads_rows}行/{Decimal(all_platform_gsv):.2f}元")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
