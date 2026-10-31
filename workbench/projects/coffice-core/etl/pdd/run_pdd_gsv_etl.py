#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新拼多多GSV指标专属的DWD、DWS和共享GSV ADS。"""

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
    "pdd/gsv/48_dwd_pdd_gsv_order_detail_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "pdd/gsv/50_refresh_dwd_pdd_gsv_order_detail_postgres.sql",
    "pdd/gsv/51_refresh_dws_pdd_gsv_shop_daily_postgres.sql",
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
    "订单状态",
    "售后状态",
    "订单成交时间",
    "商家实收金额(元)",
    "店铺优惠折扣(元)",
    "用户实付金额(元)",
}
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新拼多多GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods_and_dim(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_pdd_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_pdd_order_raw")

    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ods'
          AND table_name = 'ods_pdd_order_raw'
        """
    )
    actual_columns = {row[0] for row in cursor.fetchall()}
    missing_columns = sorted(REQUIRED_ODS_COLUMNS - actual_columns)
    if missing_columns:
        raise RuntimeError(f"拼多多订单ODS缺少必需字段：{', '.join(missing_columns)}")

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_pdd_order_raw
        """
    )
    source_rows, source_orders = cursor.fetchone()
    if source_rows == 0 or source_orders == 0:
        raise RuntimeError("ods.ods_pdd_order_raw没有有效订单数据")

    cursor.execute(
        r"""
        WITH cleaned AS (
            SELECT
                NULLIF(regexp_replace(BTRIM("商家实收金额(元)"), '[,\s￥¥元]', '', 'g'), '')
                    AS merchant_received_raw,
                NULLIF(regexp_replace(BTRIM("店铺优惠折扣(元)"), '[,\s￥¥元]', '', 'g'), '')
                    AS store_discount_raw,
                NULLIF(regexp_replace(BTRIM("用户实付金额(元)"), '[,\s￥¥元]', '', 'g'), '')
                    AS user_paid_raw,
                NULLIF(NULLIF(BTRIM("订单成交时间"), ''), '-') AS deal_at_raw,
                NULLIF(BTRIM("订单状态"), '') AS order_status
            FROM common.v_current_pdd_order_raw
        )
        SELECT
            COUNT(*) FILTER (
                WHERE merchant_received_raw IS NULL
                   OR merchant_received_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (
                WHERE store_discount_raw IS NULL
                   OR store_discount_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (
                WHERE user_paid_raw IS NULL
                   OR user_paid_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (
                WHERE order_status IN ('已发货，待收货', '已收货')
                  AND deal_at_raw IS NULL
            )
        FROM cleaned
        """
    )
    invalid_received, invalid_discount, invalid_user_paid, included_missing_dates = cursor.fetchone()
    if invalid_received or invalid_discount or invalid_user_paid or included_missing_dates:
        raise RuntimeError(
            "拼多多订单ODS质量校验失败："
            f"商家实收无效{invalid_received}条，"
            f"店铺优惠无效{invalid_discount}条，"
            f"用户实付无效{invalid_user_paid}条，"
            f"纳入订单缺少成交时间{included_missing_dates}条"
        )

    cursor.execute(
        """
        SELECT COUNT(DISTINCT raw.batch_id)
        FROM common.v_current_pdd_order_raw raw
        WHERE NOT EXISTS (
            SELECT 1
            FROM common.v_ingest_batch_shop_context ctx
            WHERE ctx.batch_id = raw.batch_id
              AND ctx.platform_code = 'pdd'
              AND ctx.shop_mapping_status = 'mapped'
        )
        """
    )
    unmapped_batches = cursor.fetchone()[0]
    if unmapped_batches:
        raise RuntimeError(f"拼多多订单存在{unmapped_batches}个未映射店铺的导入批次")
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
            prepare_report_sources(cursor, ('pdd',), pdd_settlement=False)
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
                    COUNT(*) FILTER (WHERE stat_date IS NULL),
                    COUNT(*) FILTER (WHERE shop_code_source = 'batch_context')
                FROM dwd.dwd_pdd_gsv_order_detail
                """
            )
            dwd_rows, dwd_orders, missing_dates, mapped_context_orders = cursor.fetchone()
            if dwd_rows != source_orders or dwd_orders != source_orders:
                raise RuntimeError(
                    f"DWD粒度校验失败：ODS唯一订单{source_orders}，"
                    f"DWD行数{dwd_rows}，DWD唯一订单{dwd_orders}"
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE BTRIM(order_status) IN ('已发货，待收货', '已收货')
                          AND BTRIM(after_sale_status) IN (
                              '无售后', '售后取消', '无售后或售后取消'
                          )
                    ),
                    COUNT(*) FILTER (
                        WHERE NOT (
                            BTRIM(order_status) IN ('已发货，待收货', '已收货')
                            AND BTRIM(after_sale_status) IN (
                                '无售后', '售后取消', '无售后或售后取消'
                            )
                        )
                    ),
                    COALESCE(SUM(merchant_received_amount) FILTER (
                        WHERE BTRIM(order_status) IN ('已发货，待收货', '已收货')
                          AND BTRIM(after_sale_status) IN (
                              '无售后', '售后取消', '无售后或售后取消'
                          )
                    ), 0),
                    COALESCE(SUM(store_discount_amount) FILTER (
                        WHERE BTRIM(order_status) IN ('已发货，待收货', '已收货')
                          AND BTRIM(after_sale_status) IN (
                              '无售后', '售后取消', '无售后或售后取消'
                          )
                    ), 0),
                    COALESCE(SUM(merchant_received_amount) FILTER (
                        WHERE BTRIM(order_status) IN ('已发货，待收货', '已收货')
                          AND BTRIM(after_sale_status) IN (
                              '无售后', '售后取消', '无售后或售后取消'
                          )
                    ), 0)
                FROM dwd.dwd_pdd_gsv_order_detail
                """
            )
            (
                expected_included_orders,
                excluded_orders,
                expected_received,
                expected_discount,
                expected_gsv,
            ) = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(included_order_count), 0),
                    COALESCE(SUM(merchant_received_amount), 0),
                    COALESCE(SUM(store_discount_amount), 0),
                    COALESCE(SUM(gsv_amount), 0)
                FROM dws.dws_pdd_gsv_shop_daily
                """
            )
            dws_rows, included_orders, dws_received, dws_discount, dws_gsv = cursor.fetchone()
            if (
                included_orders != expected_included_orders
                or dws_received != expected_received
                or dws_discount != expected_discount
                or dws_gsv != expected_gsv
            ):
                raise RuntimeError(
                    "DWS重算不一致："
                    f"预期{expected_included_orders}单/商家实收{expected_received}=GSV{expected_gsv}"
                    f"（店铺优惠审计{expected_discount}），"
                    f"实际{included_orders}单/商家实收{dws_received}=GSV{dws_gsv}"
                    f"（店铺优惠审计{dws_discount}）"
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
                WHERE platform_code = 'pdd'
                """
            )
            ads_rows, min_date, max_date, ads_gsv, unmapped_rows, unmapped_gsv = cursor.fetchone()
            if ads_gsv != dws_gsv:
                raise RuntimeError(f"ADS与DWS不一致：DWS={dws_gsv}，ADS={ads_gsv}")
            if unmapped_rows:
                raise RuntimeError(
                    f"拼多多ADS存在{unmapped_rows}条未匹配公司数据，金额{unmapped_gsv}"
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
    print(f"ODS来源行数/唯一订单数：{source_rows}/{source_orders}")
    print(f"DWD订单数/唯一订单数：{dwd_rows}/{dwd_orders}")
    print(f"DWD缺少成交日期：{missing_dates}单")
    print(f"DWD通过批次上下文映射：{mapped_context_orders}单")
    print(f"DWS纳入/排除订单数：{included_orders}/{excluded_orders}")
    print(f"DWS汇总行数：{dws_rows}")
    print(f"DWS商家实收合计：{Decimal(dws_received):.2f}")
    print(f"DWS店铺优惠合计：{Decimal(dws_discount):.2f}")
    print(f"拼多多ADS公司店铺日行数：{ads_rows}")
    print(f"拼多多ADS日期范围：{min_date} 至 {max_date}")
    print(f"拼多多ADS GSV合计：{Decimal(ads_gsv):.2f}")
    print(f"拼多多ADS未匹配公司：{unmapped_rows}条/{Decimal(unmapped_gsv):.2f}元")
    print(f"全平台GSV ADS：{all_ads_rows}行/{Decimal(all_platform_gsv):.2f}元")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
