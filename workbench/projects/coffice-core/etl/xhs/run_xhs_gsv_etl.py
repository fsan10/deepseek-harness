#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新小红书GSV指标专属DWD、DWS和共享GSV ADS。"""

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
    "xhs/gsv/62_dwd_xhs_gsv_order_item_detail_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
]
REFRESH_SQL_FILES = [
    "xhs/gsv/64_refresh_dwd_xhs_gsv_order_item_detail_postgres.sql",
    "xhs/gsv/65_refresh_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/31_refresh_ads_gsv_company_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no", "ingest_time",
    "订单号", "订单状态", "售后状态", "规格ID", "商品ID", "商品名称", "SKU名称",
    "SKU件数", "商家应收金额(元)（支付金额）", "店铺优惠(元)", "用户应付金额(元)",
    "平台优惠(元)", "支付时间", "订单创建时间", "店铺名称",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新小红书GSV指标的DWD、DWS和ADS。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def validate_ods_and_batches(cursor) -> tuple[int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_xhs_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_xhs_order_raw")

    cursor.execute(
        """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'ods' AND table_name = 'ods_xhs_order_raw'
        """
    )
    missing = sorted(REQUIRED_ODS_COLUMNS - {row[0] for row in cursor.fetchall()})
    if missing:
        raise RuntimeError(f"小红书订单ODS缺少必需字段：{', '.join(missing)}")

    cursor.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT NULLIF(BTRIM("订单号"), ''))
        FROM common.v_current_xhs_order_raw
        """
    )
    source_rows, source_orders = cursor.fetchone()
    if not source_rows or not source_orders:
        raise RuntimeError("小红书订单ODS没有有效订单数据")

    cursor.execute(
        r"""
        WITH cleaned AS (
            SELECT
                NULLIF(regexp_replace(BTRIM("商家应收金额(元)（支付金额）"), '[,\s￥¥元]', '', 'g'), '') AS receivable_raw,
                NULLIF(regexp_replace(BTRIM("店铺优惠(元)"), '[,\s￥¥元]', '', 'g'), '') AS shop_discount_raw,
                NULLIF(regexp_replace(BTRIM("用户应付金额(元)"), '[,\s￥¥元]', '', 'g'), '') AS payable_raw,
                NULLIF(regexp_replace(BTRIM("平台优惠(元)"), '[,\s￥¥元]', '', 'g'), '') AS platform_discount_raw,
                NULLIF(regexp_replace(BTRIM("SKU件数"), '[,\s]', '', 'g'), '') AS quantity_raw,
                NULLIF(NULLIF(BTRIM("支付时间"), ''), '-') AS paid_at_raw,
                NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-') AS created_at_raw
            FROM common.v_current_xhs_order_raw
        )
        SELECT
            COUNT(*) FILTER (WHERE receivable_raw IS NULL OR receivable_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE shop_discount_raw IS NULL OR shop_discount_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE payable_raw IS NULL OR payable_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE platform_discount_raw IS NULL OR platform_discount_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE quantity_raw IS NULL OR quantity_raw !~ '^[+-]?[0-9]+(?:\.[0-9]+)?$'),
            COUNT(*) FILTER (WHERE paid_at_raw IS NULL AND created_at_raw IS NULL)
        FROM cleaned
        """
    )
    bad_receivable, bad_shop_discount, bad_payable, bad_platform_discount, bad_quantity, missing_dates = cursor.fetchone()
    if any((bad_receivable, bad_shop_discount, bad_payable, bad_platform_discount, bad_quantity, missing_dates)):
        raise RuntimeError(
            "小红书ODS质量校验失败："
            f"商家应收无效{bad_receivable}条，店铺优惠无效{bad_shop_discount}条，"
            f"用户应付无效{bad_payable}条，平台优惠无效{bad_platform_discount}条，"
            f"SKU件数无效{bad_quantity}条，支付和创建时间同时缺失{missing_dates}条"
        )

    cursor.execute(
        """
        SELECT COUNT(DISTINCT raw.batch_id)
        FROM common.v_current_xhs_order_raw raw
        WHERE NOT EXISTS (
            SELECT 1 FROM common.v_ingest_batch_shop_context ctx
            WHERE ctx.batch_id = raw.batch_id
              AND ctx.platform_code = 'xhs'
              AND ctx.target_table = 'ods_xhs_order_raw'
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
        raise RuntimeError(f"小红书订单存在{invalid_batches}个未映射、冲突或DIM未命中的导入批次")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM common.v_current_xhs_order_raw raw
        INNER JOIN common.v_ingest_batch_shop_context ctx ON ctx.batch_id = raw.batch_id
        WHERE NULLIF(BTRIM(raw."店铺名称"), '') IS NOT NULL
          AND BTRIM(raw."店铺名称") <> ctx.shop_name
        """
    )
    shop_conflicts = cursor.fetchone()[0]
    if shop_conflicts:
        raise RuntimeError(f"小红书ODS有{shop_conflicts}条源店铺名称与批次店铺上下文冲突")
    return source_rows, source_orders


def run_pipeline(args: argparse.Namespace) -> None:
    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=args.password
    )
    try:
        with conn.cursor() as cursor:
            prepare_report_sources(cursor, ('xhs',), pdd_settlement=False)
            for file_name in SETUP_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))
            source_rows, source_orders = validate_ods_and_batches(cursor)
            for file_name in REFRESH_SQL_FILES:
                cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT source_id), COUNT(DISTINCT order_no),
                       COUNT(*) FILTER (WHERE stat_date_source = 'payment_time'),
                       COUNT(*) FILTER (WHERE stat_date_source = 'creation_time'),
                       COUNT(*) FILTER (WHERE shop_code_source <> 'batch_context')
                FROM dwd.dwd_xhs_gsv_order_item_detail
                """
            )
            dwd_rows, unique_source_ids, dwd_orders, payment_items, fallback_items, invalid_mapping = cursor.fetchone()
            if (dwd_rows, unique_source_ids, dwd_orders) != (source_rows, source_rows, source_orders):
                raise RuntimeError(
                    f"DWD粒度校验失败：预期{source_rows}行/{source_orders}单，"
                    f"实际{dwd_rows}行/{unique_source_ids}源ID/{dwd_orders}单"
                )
            if invalid_mapping:
                raise RuntimeError(f"DWD存在{invalid_mapping}条非批次上下文店铺映射")

            cursor.execute(
                """
                SELECT COUNT(*), COUNT(DISTINCT order_no),
                       COALESCE(SUM(merchant_receivable_amount), 0),
                       COALESCE(SUM(shop_discount_amount), 0),
                       COALESCE(SUM(merchant_receivable_amount), 0)
                FROM dwd.dwd_xhs_gsv_order_item_detail
                WHERE stat_date IS NOT NULL
                  AND COALESCE(BTRIM(order_status), '') = '已完成'
                  AND COALESCE(BTRIM(after_sale_status), '') = '无售后'
                """
            )
            expected_items, expected_orders, expected_receivable, expected_shop_discount, expected_gsv = cursor.fetchone()
            cursor.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(included_item_count), 0),
                       COALESCE(SUM(included_order_count), 0),
                       COALESCE(SUM(merchant_receivable_amount), 0),
                       COALESCE(SUM(shop_discount_amount), 0), COALESCE(SUM(gsv_amount), 0)
                FROM dws.dws_xhs_gsv_shop_daily
                """
            )
            dws_rows, included_items, included_orders, dws_receivable, dws_shop_discount, dws_gsv = cursor.fetchone()
            if (included_items, included_orders, dws_receivable, dws_shop_discount, dws_gsv) != (
                expected_items, expected_orders, expected_receivable, expected_shop_discount, expected_gsv
            ):
                raise RuntimeError("小红书DWS与DWD按已确认口径重算不一致")

            cursor.execute(
                """
                SELECT COUNT(*), MIN(stat_date), MAX(stat_date), COALESCE(SUM(gsv_amount), 0),
                       COUNT(*) FILTER (WHERE company_code = 'unmapped')
                FROM ads.ads_gsv_company_daily WHERE platform_code = 'xhs'
                """
            )
            ads_rows, min_date, max_date, ads_gsv, unmapped_rows = cursor.fetchone()
            if ads_gsv != dws_gsv or unmapped_rows:
                raise RuntimeError(f"小红书ADS验收失败：DWS={dws_gsv}，ADS={ads_gsv}，未匹配公司={unmapped_rows}")

            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.columns c
                WHERE c.table_schema IN ('dwd','dws','ads')
                  AND c.table_name IN ('dwd_xhs_gsv_order_item_detail',
                                       'dws_xhs_gsv_shop_daily', 'ads_gsv_company_daily')
                  AND col_description((quote_ident(c.table_schema)||'.'||quote_ident(c.table_name))::regclass,
                                      c.ordinal_position) IS NULL
                """
            )
            missing_comments = cursor.fetchone()[0]
            if missing_comments:
                raise RuntimeError(f"指标链路存在{missing_comments}个缺少注释的字段")

            cursor.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT stat_date, platform_code, company_code, shop_code
                    FROM ads.ads_gsv_company_daily
                    GROUP BY stat_date, platform_code, company_code, shop_code HAVING COUNT(*) > 1
                ) duplicate_keys
                """
            )
            duplicate_ads_keys = cursor.fetchone()[0]
            if duplicate_ads_keys:
                raise RuntimeError(f"ADS存在{duplicate_ads_keys}组重复主键")

            cursor.execute("SELECT COUNT(*), COALESCE(SUM(gsv_amount), 0) FROM ads.ads_gsv_company_daily")
            all_ads_rows, all_platform_gsv = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"数据库：{args.dbname}")
    print(f"ODS SKU行/唯一订单：{source_rows}/{source_orders}")
    print(f"DWD SKU行/唯一源ID/唯一订单：{dwd_rows}/{unique_source_ids}/{dwd_orders}")
    print(f"DWD日期来源：支付时间{payment_items}行，创建时间兜底{fallback_items}行")
    print(f"DWS日汇总/纳入SKU行/纳入订单：{dws_rows}/{included_items}/{included_orders}")
    print(f"纳入商家应收/店铺优惠：{Decimal(dws_receivable):.2f}/{Decimal(dws_shop_discount):.2f}")
    print(f"小红书ADS日期范围：{min_date} 至 {max_date}")
    print(f"小红书ADS公司店铺日行数/GSV：{ads_rows}/{Decimal(ads_gsv):.2f}")
    print(f"小红书ADS未匹配公司：{unmapped_rows}条")
    print(f"全平台GSV ADS：{all_ads_rows}行/{Decimal(all_platform_gsv):.2f}元")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
