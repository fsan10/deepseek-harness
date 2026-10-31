#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新子订单粒度天猫GSV DWD、DWS和共享GSV ADS。"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.report_sources import prepare_report_sources

ODS_SCHEMA_SQL_FILE = "tmall/ods/18_ods_tmall_order_raw_postgres.sql"
SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "tmall/gsv/40_dwd_tmall_gsv_order_detail_postgres.sql",
    "tmall/gsv/41_dws_tmall_gsv_shop_daily_postgres.sql",
    "douyin/gsv/27_dws_douyin_gsv_shop_daily_postgres.sql",
    "jd/gsv/45_dws_jd_gsv_shop_daily_postgres.sql",
    "pdd/gsv/49_dws_pdd_gsv_shop_daily_postgres.sql",
    "ks/gsv/55_dws_ks_gsv_shop_daily_postgres.sql",
    "wechat_channels/gsv/59_dws_wechat_channels_gsv_shop_daily_postgres.sql",
    "xhs/gsv/63_dws_xhs_gsv_shop_daily_postgres.sql",
    "ads/gsv/28_ads_gsv_company_daily_postgres.sql",
    "tmall/gsv/42_refresh_dwd_tmall_gsv_order_detail_postgres.sql",
    "tmall/gsv/43_refresh_dws_tmall_gsv_shop_daily_postgres.sql",
    "ads/gsv/31_refresh_ads_gsv_company_daily_postgres.sql",
]
REQUIRED_ODS_COLUMNS = {
    "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no",
    "ingest_time", "子订单编号", "主订单编号", "商品标题", "买家实付金额", "订单状态",
    "退款状态", "退款金额", "订单创建时间", "订单付款时间",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新天猫GSV子订单指标链路。")
    parser.add_argument(
        "--enforce-current-file-baseline",
        action="store_true",
        help="校验当前最新1098个子订单版本的退款状态口径固定基准。",
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor) -> None:
    for file_name in SQL_FILES:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_source(cursor) -> tuple[int, int, int]:
    cursor.execute("SELECT to_regclass('ods.ods_tmall_order_raw')")
    if cursor.fetchone()[0] is None:
        raise RuntimeError("缺少来源表：ods.ods_tmall_order_raw")
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='ods' AND table_name='ods_tmall_order_raw'
        """
    )
    actual = {row[0] for row in cursor.fetchall()}
    missing = sorted(REQUIRED_ODS_COLUMNS - actual)
    if missing:
        raise RuntimeError(f"天猫订单ODS缺少必需字段：{', '.join(missing)}")
    cursor.execute(
        "SELECT COUNT(*) FROM common.v_current_tmall_order_raw"
    )
    source_rows = cursor.fetchone()[0]
    cursor.execute(
        """
        WITH source_context AS (
            SELECT o.*, c.shop_code
            FROM common.v_current_tmall_order_raw o
            JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id = o.batch_id
             AND c.platform_code = 'tmall'
             AND c.target_table = 'ods_tmall_order_raw'
             AND c.shop_mapping_status = 'mapped'
        ), latest_source AS (
            SELECT DISTINCT ON (
                shop_code,
                NULLIF(BTRIM("子订单编号"), '')
            ) *
            FROM source_context
            WHERE NULLIF(BTRIM("子订单编号"), '') IS NOT NULL
            ORDER BY
                shop_code,
                NULLIF(BTRIM("子订单编号"), ''),
                ingest_time DESC,
                id DESC
        )
        SELECT
            COUNT(*),
            COUNT(DISTINCT NULLIF(BTRIM("主订单编号"), '')),
            COUNT(*) FILTER (
                WHERE NULLIF(BTRIM("子订单编号"), '') IS NULL
                   OR NULLIF(BTRIM("主订单编号"), '') IS NULL
                   OR NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-') IS NULL
            ),
            COUNT(*) FILTER (
                WHERE NULLIF(REGEXP_REPLACE(
                    BTRIM(COALESCE("买家实付金额", '')),
                    '[,\\s￥¥元]', '', 'g'
                ), '') IS NOT NULL
                  AND REGEXP_REPLACE(
                    BTRIM("买家实付金额"),
                    '[,\\s￥¥元]', '', 'g'
                  ) !~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$'
            ),
            COUNT(*) FILTER (
                WHERE NULLIF(BTRIM("退款状态"), '') IS NULL
            ),
            COUNT(*) FILTER (
                WHERE NULLIF(BTRIM("退款金额"), '') IS NOT NULL
                  AND BTRIM("退款金额") NOT IN ('-', '无退款申请')
                  AND REGEXP_REPLACE(
                    BTRIM("退款金额"),
                    '[,\\s￥¥元]', '', 'g'
                  ) !~ '^[+-]?[0-9]+(?:\\.[0-9]+)?$'
            )
        FROM latest_source
        """
    )
    (
        sub_orders,
        main_orders,
        missing_keys,
        invalid_amounts,
        missing_refund_statuses,
        invalid_refund_amounts,
    ) = cursor.fetchone()
    if (
        not source_rows
        or not sub_orders
        or missing_keys
        or invalid_amounts
        or missing_refund_statuses
        or invalid_refund_amounts
    ):
        raise RuntimeError(
            "天猫订单ODS质量失败："
            f"rows={source_rows}, latest_sub_orders={sub_orders}, "
            f"missing_keys_or_dates={missing_keys}, "
            f"invalid_buyer_paid={invalid_amounts}, "
            f"missing_refund_status={missing_refund_statuses}, "
            f"invalid_refund_amount={invalid_refund_amounts}"
        )
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id FROM ods.ods_tmall_order_raw GROUP BY batch_id
        )
        SELECT COUNT(*)
        FROM source_batches b
        LEFT JOIN common.v_ingest_batch_shop_context c
          ON c.batch_id=b.batch_id
         AND c.platform_code='tmall'
         AND c.target_table='ods_tmall_order_raw'
         AND c.shop_mapping_status='mapped'
        GROUP BY b.batch_id
        HAVING b.batch_id IS NULL OR COUNT(c.batch_id)<>1
        """
    )
    invalid_mappings = len(cursor.fetchall())
    if invalid_mappings:
        raise RuntimeError(f"天猫订单ODS存在{invalid_mappings}个无效批次店铺映射")
    return source_rows, sub_orders, main_orders


def validate_layers(cursor, source_sub_orders: int, enforce_baseline: bool) -> dict:
    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*)-COUNT(DISTINCT sub_order_no),
            COUNT(*) FILTER (WHERE stat_date IS NULL),
            COUNT(*) FILTER (WHERE shop_code_source<>'batch_context'),
            COUNT(*) FILTER (WHERE stat_date_source='payment_time'),
            COUNT(*) FILTER (WHERE stat_date_source='creation_time')
        FROM dwd.dwd_tmall_gsv_order_detail
        """
    )
    dwd = cursor.fetchone()
    if dwd[0] != source_sub_orders or dwd[1] or dwd[2] or dwd[3]:
        raise RuntimeError(f"天猫GSV DWD验收失败：{dwd}, source={source_sub_orders}")
    cursor.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE order_status='交易关闭'),
            COUNT(*) FILTER (
                WHERE COALESCE(order_status,'')<>'交易关闭'
                  AND COALESCE(product_title,'') LIKE '%购物金%'
            ),
            COUNT(*) FILTER (
                WHERE COALESCE(order_status,'')<>'交易关闭'
                  AND COALESCE(product_title,'') NOT LIKE '%购物金%'
                  AND COALESCE(refund_status,'')='退款成功'
            ),
            COUNT(*) FILTER (
                WHERE COALESCE(order_status,'')<>'交易关闭'
                  AND COALESCE(refund_status,'')<>'退款成功'
                  AND COALESCE(product_title,'') NOT LIKE '%购物金%'
            ),
            COUNT(DISTINCT main_order_no) FILTER (
                WHERE COALESCE(order_status,'')<>'交易关闭'
                  AND COALESCE(refund_status,'')<>'退款成功'
                  AND COALESCE(product_title,'') NOT LIKE '%购物金%'
            ),
            COALESCE(SUM(buyer_paid_amount) FILTER (
                WHERE COALESCE(order_status,'')<>'交易关闭'
                  AND COALESCE(refund_status,'')<>'退款成功'
                  AND COALESCE(product_title,'') NOT LIKE '%购物金%'
            ),0)
        FROM dwd.dwd_tmall_gsv_order_detail
        """
    )
    (
        closed_suborders,
        shopping_card_suborders,
        refund_success_suborders,
        included_suborders,
        included_orders,
        expected_gsv,
    ) = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
               COALESCE(SUM(gsv_amount),0),
               COALESCE(SUM(included_order_count),0),
               COALESCE(SUM(included_sub_order_count),0)
        FROM dws.dws_tmall_gsv_shop_daily
        """
    )
    dws = cursor.fetchone()
    if (
        dws[3] != expected_gsv
        or dws[4] != included_orders
        or dws[5] != included_suborders
    ):
        raise RuntimeError(
            f"天猫GSV DWS重算不一致：dws={dws}, "
            f"expected={expected_gsv}/{included_orders}/{included_suborders}"
        )
    cursor.execute(
        """
        SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
               COALESCE(SUM(gsv_amount),0),
               COUNT(*) FILTER (WHERE company_code='unmapped')
        FROM ads.ads_gsv_company_daily
        WHERE platform_code='tmall'
        """
    )
    ads = cursor.fetchone()
    if ads[3] != dws[3] or ads[4]:
        raise RuntimeError(f"天猫GSV ADS验收失败：ads={ads}, dws={dws}")
    if enforce_baseline:
        actual = (
            source_sub_orders,
            closed_suborders,
            shopping_card_suborders,
            refund_success_suborders,
            included_suborders,
            included_orders,
            dws[3],
            dws[1],
            dws[2],
        )
        expected = (
            1098,
            238,
            9,
            1,
            850,
            429,
            Decimal("43934.37"),
            __import__("datetime").date(2026, 6, 25),
            __import__("datetime").date(2026, 7, 5),
        )
        if actual != expected:
            raise RuntimeError(f"天猫GSV当前文件基准不一致：{actual}/{expected}")
    cursor.execute(
        """
        (
            SELECT '正常成交', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE order_status='交易成功'
              AND COALESCE(refund_status,'')<>'退款成功'
              AND COALESCE(product_title,'') NOT LIKE '%购物金%'
              AND buyer_paid_amount>0
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '购物金', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE COALESCE(order_status,'')<>'交易关闭'
              AND COALESCE(product_title,'') LIKE '%购物金%'
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '退款成功', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE COALESCE(order_status,'')<>'交易关闭'
              AND COALESCE(product_title,'') NOT LIKE '%购物金%'
              AND refund_status='退款成功'
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '交易关闭', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE order_status='交易关闭' AND buyer_paid_amount>0
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '创建时间兜底', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE stat_date_source='creation_time'
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '零实付', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE buyer_paid_amount=0
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '付款日期', sub_order_no, main_order_no, stat_date,
                   order_status, refund_status, buyer_paid_amount,
                   refund_amount, stat_date_source
            FROM dwd.dwd_tmall_gsv_order_detail
            WHERE stat_date_source='payment_time'
            ORDER BY source_id LIMIT 1
        )
        """
    )
    samples = cursor.fetchall()
    if len(samples) != 7:
        raise RuntimeError(f"天猫GSV公式抽样不足：{samples}")
    return {
        "dwd": dwd,
        "dws": dws,
        "ads": ads,
        "closed_suborders": closed_suborders,
        "shopping_card_suborders": shopping_card_suborders,
        "refund_success_suborders": refund_success_suborders,
        "included_suborders": included_suborders,
        "included_orders": included_orders,
        "samples": samples,
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
            prepare_report_sources(cursor, ('tmall',))
            cursor.execute(
                (SQL_DIR / ODS_SCHEMA_SQL_FILE).read_text(encoding="utf-8")
            )
            source = validate_source(cursor)
            execute_files(cursor)
            result = validate_layers(
                cursor,
                source[1],
                args.enforce_current_file_baseline,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(f"数据库：{args.dbname}")
    print(f"ODS来源行/唯一子订单/唯一主订单：{source[0]}/{source[1]}/{source[2]}")
    print(f"DWD：{result['dwd']}")
    print(f"DWS：{result['dws']}")
    print(f"ADS：{result['ads']}")
    print(
        "排除交易关闭/排除购物金/排除退款成功/纳入子订单："
        f"{result['closed_suborders']}/{result['shopping_card_suborders']}/"
        f"{result['refund_success_suborders']}/"
        f"{result['included_suborders']}"
    )
    print(f"纳入唯一主订单：{result['included_orders']}")
    print("公式抽样：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
