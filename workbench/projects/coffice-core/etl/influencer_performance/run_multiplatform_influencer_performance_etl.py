#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新七个平台达人业绩DWD/DWS及达人日、月排名、商务月ADS。"""

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


PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "dim/166_dim_influencer_business_config_postgres.sql",
    "dim/394_dim_company_influencer_postgres.sql",
    "dim/395_migrate_company_influencer_legacy_postgres.sql",
]

CREATE_SQL_FILES = [
    "douyin/influencer_performance/167_dwd_douyin_influencer_sales_order_item_detail_postgres.sql",
    "douyin/influencer_performance/168_dws_douyin_influencer_sales_order_item_postgres.sql",
    "wechat_channels/influencer_performance/277_wechat_channels_influencer_performance_tables_postgres.sql",
    "ks/influencer_performance/279_ks_influencer_performance_tables_postgres.sql",
    "tmall/influencer_performance/281_tmall_influencer_performance_tables_postgres.sql",
    "jd/influencer_performance/283_jd_influencer_performance_tables_postgres.sql",
    "xhs/influencer_performance/285_xhs_influencer_performance_tables_postgres.sql",
    "pdd/influencer_performance/287_pdd_influencer_performance_tables_postgres.sql",
    "ads/influencer_performance/169_ads_influencer_company_shop_daily_postgres.sql",
    "ads/influencer_performance/170_ads_influencer_company_shop_monthly_ranking_postgres.sql",
    "ads/influencer_performance/171_ads_influencer_business_monthly_postgres.sql",
    "common/396_dws_influencer_identity_resolved_view_postgres.sql",
    "ads/influencer_performance/397_alter_ads_influencer_identity_postgres.sql",
]

REFRESH_SQL_FILES = [
    "douyin/influencer_performance/172_refresh_dwd_douyin_influencer_sales_order_item_detail_postgres.sql",
    "douyin/influencer_performance/173_refresh_dws_douyin_influencer_sales_order_item_postgres.sql",
    "wechat_channels/influencer_performance/278_refresh_wechat_channels_influencer_performance_postgres.sql",
    "ks/influencer_performance/280_refresh_ks_influencer_performance_postgres.sql",
    "tmall/influencer_performance/282_refresh_tmall_influencer_performance_postgres.sql",
    "jd/influencer_performance/284_refresh_jd_influencer_performance_postgres.sql",
    "xhs/influencer_performance/286_refresh_xhs_influencer_performance_postgres.sql",
    "pdd/influencer_performance/288_refresh_pdd_influencer_performance_postgres.sql",
    "ads/influencer_performance/399_refresh_ads_influencer_company_shop_daily_company_identity_postgres.sql",
    "ads/influencer_performance/400_refresh_ads_influencer_monthly_ranking_company_identity_postgres.sql",
    "ads/influencer_performance/401_refresh_ads_influencer_business_monthly_company_identity_postgres.sql",
]

SOURCE_SPECS = {
    "douyin": (
        "ods_douyin_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "主订单编号", "子订单编号", "所属门店ID", "订单提交时间", "流量来源",
            "订单状态", "售后状态", "达人ID", "达人昵称", "商品单价", "订单应付金额",
        },
    ),
    "wechat_channels": (
        "ods_wechat_channels_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单下单时间", "订单状态", "商品售后", "带货ID",
            "带货账号昵称", "带货方式", "带货账号类型", "商品价格(单件)",
            "订单实际支付金额",
        },
    ),
    "ks": (
        "ods_ks_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单创建时间", "订单状态", "售后状态", "CPS达人ID",
            "CPS达人昵称", "渠道", "订单载体", "商品单价", "实付款",
        },
    ),
    "tmall": (
        "ods_tmall_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_sheet_name", "source_row_no",
            "ingest_time", "子订单编号", "主订单编号", "订单创建时间",
            "订单状态", "商品标题", "购买数量", "买家应付货款",
        },
    ),
    "jd": (
        "ods_jd_order_raw",
        {"id", "batch_id", "source_file_name", "source_row_no", "ingest_time", "订单号", "下单时间", "订单状态"},
    ),
    "xhs": (
        "ods_xhs_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单创建时间", "订单状态", "售后状态", "店铺名称",
        },
    ),
    "pdd": (
        "ods_pdd_order_raw",
        {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单成交时间", "订单状态", "售后状态",
        },
    ),
}

NEW_TABLES = [
    ("dwd", "dwd_wechat_channels_influencer_sales_order_item_detail"),
    ("dws", "dws_wechat_channels_influencer_sales_order_item"),
    ("dwd", "dwd_ks_influencer_sales_order_item_detail"),
    ("dws", "dws_ks_influencer_sales_order_item"),
    ("dwd", "dwd_tmall_influencer_sales_order_detail"),
    ("dws", "dws_tmall_influencer_sales_order"),
    ("dwd", "dwd_jd_influencer_zero_order_detail"),
    ("dws", "dws_jd_influencer_sales_shop_daily_zero"),
    ("dwd", "dwd_xhs_influencer_zero_order_detail"),
    ("dws", "dws_xhs_influencer_sales_shop_daily_zero"),
    ("dwd", "dwd_pdd_influencer_zero_order_detail"),
    ("dws", "dws_pdd_influencer_sales_shop_daily_zero"),
]

DWD_TABLES = {
    "douyin": "dwd.dwd_douyin_influencer_sales_order_item_detail",
    "wechat_channels": "dwd.dwd_wechat_channels_influencer_sales_order_item_detail",
    "ks": "dwd.dwd_ks_influencer_sales_order_item_detail",
    "tmall": "dwd.dwd_tmall_influencer_sales_order_detail",
    "jd": "dwd.dwd_jd_influencer_zero_order_detail",
    "xhs": "dwd.dwd_xhs_influencer_zero_order_detail",
    "pdd": "dwd.dwd_pdd_influencer_zero_order_detail",
}

ACTIVE_DWS_TABLES = {
    "douyin": "dws.dws_douyin_influencer_sales_order_item",
    "wechat_channels": "dws.dws_wechat_channels_influencer_sales_order_item",
    "ks": "dws.dws_ks_influencer_sales_order_item",
    "tmall": "dws.dws_tmall_influencer_sales_order",
}

ZERO_DWS_TABLES = {
    "jd": "dws.dws_jd_influencer_sales_shop_daily_zero",
    "xhs": "dws.dws_xhs_influencer_sales_shop_daily_zero",
    "pdd": "dws.dws_pdd_influencer_sales_shop_daily_zero",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新多平台达人业绩指标。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, files: list[str]) -> None:
    prepare_report_sources(cursor, ('douyin', 'tmall', 'jd', 'ks', 'pdd', 'xhs', 'wechat_channels'), pdd_settlement=False)
    for file_name in files:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_sources(cursor) -> dict[str, int]:
    source_rows: dict[str, int] = {}
    for platform_code, (table_name, required_columns) in SOURCE_SPECS.items():
        runtime = getattr(cursor.connection, 'refresh_scope', None)
        if runtime is not None and not runtime.full and platform_code not in runtime.platforms:
            continue
        cursor.execute("SELECT to_regclass(%s)", (f"ods.{table_name}",))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少来源表：ods.{table_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'ods' AND table_name = %s
            """,
            (table_name,),
        )
        actual_columns = {row[0] for row in cursor.fetchall()}
        missing = sorted(required_columns - actual_columns)
        if missing:
            raise RuntimeError(f"{platform_code} ODS缺少必需字段：{', '.join(missing)}")
        cursor.execute(f"SELECT COUNT(*) FROM common.v_current_{platform_code}_order_raw")
        rows = cursor.fetchone()[0]
        if rows == 0:
            source_rows[platform_code] = 0
            print(f"[WARN] {platform_code}订单ODS为空，按0值刷新该平台")
            continue
        source_rows[platform_code] = rows
    return source_rows


def validate_batch_mappings(cursor) -> list[tuple]:
    results: list[tuple] = []
    for platform_code, (table_name, _) in SOURCE_SPECS.items():
        runtime = getattr(cursor.connection, 'refresh_scope', None)
        if runtime is not None and not runtime.full and platform_code not in runtime.platforms:
            continue
        cursor.execute(
            """
            WITH source_batches AS (
                SELECT batch_id, COUNT(*) AS source_rows
                FROM ods.""" + table_name + """
                GROUP BY batch_id
            )
            SELECT
                b.batch_id,
                b.source_rows,
                COUNT(c.batch_id) AS mapping_count,
                MAX(c.shop_code),
                MAX(c.shop_name)
            FROM source_batches b
            LEFT JOIN common.v_ingest_batch_shop_context c
              ON c.batch_id = b.batch_id
             AND c.platform_code = %s
             AND c.target_table = %s
             AND c.shop_mapping_status = 'mapped'
            GROUP BY b.batch_id, b.source_rows
            ORDER BY b.batch_id NULLS FIRST
            """,
            (platform_code, table_name),
        )
        rows = cursor.fetchall()
        invalid = [row for row in rows if row[0] is None or row[2] != 1]
        if invalid:
            raise RuntimeError(f"{platform_code}存在未映射、空批次或冲突批次：{invalid}")
        results.extend((platform_code, *row) for row in rows)
    return results


def validate_dwd(cursor, source_rows: dict[str, int]) -> dict[str, int]:
    expected_rows = dict(source_rows)
    runtime = getattr(cursor.connection, 'refresh_scope', None)
    if runtime is not None and not runtime.full:
        actual_rows = {}
        for platform_code in source_rows:
            cursor.execute(f'''SELECT COUNT(*),COUNT(*)-COUNT(DISTINCT source_id),
                COUNT(*) FILTER(WHERE stat_date IS NULL OR source_updated_at IS NULL)
                FROM {DWD_TABLES[platform_code]}''')
            rows, duplicates, nulls = cursor.fetchone()
            if platform_code in ('douyin', 'tmall'):
                cursor.execute(f'''SELECT COUNT(DISTINCT(c.shop_identity_key,NULLIF(BTRIM(r."子订单编号", E' \\t\\r\\n'),'')))
                    FROM common.v_current_{platform_code}_order_raw r
                    JOIN common.v_ingest_batch_shop_context c USING(batch_id)''')
                expected_rows[platform_code] = cursor.fetchone()[0]
            if rows != expected_rows[platform_code] or duplicates or nulls:
                raise RuntimeError(f'{platform_code}达人DWD校验失败：{rows}/{expected_rows[platform_code]}, duplicate={duplicates}, null={nulls}')
            actual_rows[platform_code] = rows
        return actual_rows
    cursor.execute(
        """
        SELECT COUNT(DISTINCT (c.shop_identity_key,NULLIF(BTRIM(r."子订单编号", E' \t\r\n'), '')))
        FROM common.v_current_douyin_order_raw r
        JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
        """
    )
    expected_rows["douyin"] = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(DISTINCT (c.shop_identity_key,NULLIF(BTRIM(r."子订单编号", E' \t\r\n'), '')))
        FROM common.v_current_tmall_order_raw r
        JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
        """
    )
    expected_rows["tmall"] = cursor.fetchone()[0]

    actual_rows: dict[str, int] = {}
    for platform_code, table_name in DWD_TABLES.items():
        cursor.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(*) - COUNT(DISTINCT source_id),
                COUNT(*) FILTER (WHERE stat_date IS NULL OR source_updated_at IS NULL)
            FROM {table_name}
            """
        )
        rows, duplicate_sources, null_required = cursor.fetchone()
        if rows != expected_rows[platform_code] or duplicate_sources or null_required:
            raise RuntimeError(
                f"{platform_code} DWD失败：rows={rows}/{expected_rows[platform_code]}, "
                f"duplicate_sources={duplicate_sources}, null_required={null_required}"
            )
        actual_rows[platform_code] = rows
    return actual_rows


def validate_active_dws(cursor) -> dict[str, tuple]:
    formula_predicates = {
        "douyin": (
            "traffic_source <> '精选联盟' OR gmv_amount <> product_unit_price "
            "OR refund_amount <> CASE WHEN order_status='已关闭' THEN product_unit_price ELSE 0 END"
        ),
        "wechat_channels": (
            "gmv_amount <> product_unit_price "
            "OR refund_amount <> CASE WHEN order_status='已取消' THEN product_unit_price ELSE 0 END "
            "OR influencer_id IN ('','-','0')"
        ),
        "ks": (
            "gmv_amount <> product_unit_price "
            "OR refund_amount <> CASE WHEN order_status='交易关闭' THEN product_unit_price ELSE 0 END "
            "OR influencer_id IN ('','-','0')"
        ),
        "tmall": (
            "gmv_amount <> order_pay_amount "
            "OR refund_amount <> CASE WHEN order_status='交易关闭' THEN order_pay_amount ELSE 0 END "
            "OR (influencer_name='胡可' AND influencer_id<>'3333333') "
            "OR (influencer_name='芳芳' AND influencer_id<>'4444444')"
        ),
    }
    expected_current = {
        "douyin": (237, 35, Decimal("22931.00"), Decimal("6443.00")),
        "wechat_channels": (416, 10, Decimal("78940.00"), Decimal("13294.00")),
        "ks": (1227, 27, Decimal("157928.00"), Decimal("79862.10")),
        "tmall": (5, 1, Decimal("495.00"), Decimal("99.00")),
    }
    results: dict[str, tuple] = {}
    for platform_code, table_name in ACTIVE_DWS_TABLES.items():
        cursor.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(*) - COUNT(DISTINCT source_id),
                COUNT(*) FILTER (WHERE {formula_predicates[platform_code]}),
                COUNT(DISTINCT influencer_key) FILTER (WHERE gmv_amount > 0),
                MIN(stat_date),
                MAX(stat_date),
                COALESCE(SUM(gmv_amount), 0),
                COALESCE(SUM(refund_amount), 0),
                COALESCE(SUM(included_sub_order_count), 0)
            FROM {table_name}
            """
        )
        row = cursor.fetchone()
        rows, duplicates, formula_errors, active_count, _, _, gmv, refund, included = row
        if duplicates or formula_errors or included != rows:
            raise RuntimeError(
                f"{platform_code} DWS失败：duplicates={duplicates}, "
                f"formula_errors={formula_errors}, included={included}/{rows}"
            )
        results[platform_code] = row

    current_source_rows = {}
    runtime = getattr(cursor.connection, 'refresh_scope', None)
    if runtime is None or runtime.full:
        for platform_code, (table_name, _) in SOURCE_SPECS.items():
            cursor.execute(f"SELECT COUNT(*) FROM common.v_current_{platform_code}_order_raw")
            current_source_rows[platform_code] = cursor.fetchone()[0]
    if current_source_rows == {
        "douyin": 19469, "wechat_channels": 452, "ks": 1378, "tmall": 1098,
        "jd": 35, "xhs": 12, "pdd": 1116,
    }:
        for platform_code, expected in expected_current.items():
            row = results[platform_code]
            actual = (row[0], row[3], row[6], row[7])
            if actual != expected:
                raise RuntimeError(
                    f"{platform_code}与已确认基准不一致：actual={actual}, expected={expected}"
                )
    return results


def validate_zero_dws(cursor) -> dict[str, tuple]:
    expected_rows = {"jd": 11, "xhs": 6, "pdd": 11}
    results: dict[str, tuple] = {}
    for platform_code, table_name in ZERO_DWS_TABLES.items():
        cursor.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(*) - COUNT(DISTINCT (stat_date, platform_code, shop_code, influencer_id)),
                COUNT(*) FILTER (
                    WHERE influencer_id <> '__no_influencer__'
                       OR gmv_amount <> 0
                       OR refund_amount <> 0
                       OR included_sub_order_count <> 0
                ),
                MIN(stat_date),
                MAX(stat_date)
            FROM {table_name}
            """
        )
        row = cursor.fetchone()
        if row[1] or row[2]:
            raise RuntimeError(
                f"{platform_code}补零DWS失败：duplicates={row[1]}, formula_errors={row[2]}"
            )
        results[platform_code] = row

    cursor.execute("SELECT COUNT(*) FROM ods.ods_jd_order_raw")
    jd_rows = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM ods.ods_xhs_order_raw")
    xhs_rows = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM ods.ods_pdd_order_raw")
    pdd_rows = cursor.fetchone()[0]
    if (jd_rows, xhs_rows, pdd_rows) == (35, 12, 1116):
        for platform_code, expected in expected_rows.items():
            if results[platform_code][0] != expected:
                raise RuntimeError(
                    f"{platform_code}补零店铺日与基准不一致："
                    f"{results[platform_code][0]}/{expected}"
                )
    return results


def validate_ads(cursor, active_results: dict[str, tuple]) -> dict[str, object]:
    expected_gmv = sum((row[6] for row in active_results.values()), Decimal("0"))
    expected_refund = sum((row[7] for row in active_results.values()), Decimal("0"))
    expected_orders = sum(row[8] for row in active_results.values())
    cursor.execute(
        """
        SELECT COUNT(DISTINCT influencer_identity_key)
        FROM dws.v_influencer_identity_resolved
        WHERE gmv_amount > 0
          AND source_influencer_id <> '__no_influencer__'
        """
    )
    expected_influencers = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COALESCE(SUM(included_sub_order_count), 0)
        FROM (
            SELECT gmv_amount, included_sub_order_count
            FROM dws.dws_douyin_influencer_sales_order_item
            UNION ALL
            SELECT gmv_amount, included_sub_order_count
            FROM dws.dws_wechat_channels_influencer_sales_order_item
            UNION ALL
            SELECT gmv_amount, included_sub_order_count
            FROM dws.dws_ks_influencer_sales_order_item
            UNION ALL
            SELECT gmv_amount, included_sub_order_count
            FROM dws.dws_tmall_influencer_sales_order
        ) active_rows
        WHERE gmv_amount > 0
        """
    )
    expected_ranking_orders = cursor.fetchone()[0]

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) - COUNT(DISTINCT (
                stat_date, platform_code, company_code, shop_code,
                influencer_identity_key
            )),
            COALESCE(SUM(gmv_amount), 0),
            COALESCE(SUM(refund_amount), 0),
            COALESCE(SUM(included_sub_order_count), 0),
            COUNT(DISTINCT influencer_key) FILTER (WHERE gmv_amount > 0),
            COUNT(*) FILTER (WHERE company_code = 'unmapped'),
            COUNT(*) FILTER (
                WHERE refund_rate <> COALESCE(ROUND(refund_amount / NULLIF(gmv_amount, 0), 6), 0)
            ),
            MIN(stat_date),
            MAX(stat_date)
        FROM ads.ads_influencer_company_shop_daily
        """
    )
    daily = cursor.fetchone()
    if daily[1] or daily[6] or daily[7]:
        raise RuntimeError(
            f"达人日ADS失败：duplicates={daily[1]}, unmapped={daily[6]}, ratio_errors={daily[7]}"
        )
    if (daily[2], daily[3], daily[4], daily[5]) != (
        expected_gmv, expected_refund, expected_orders, expected_influencers
    ):
        raise RuntimeError(
            "DWS与达人日ADS不一致："
            f"actual={(daily[2], daily[3], daily[4], daily[5])}, "
            f"expected={(expected_gmv, expected_refund, expected_orders, expected_influencers)}"
        )

    cursor.execute(
        """
        WITH source_rows AS (
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_douyin_influencer_sales_order_item
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_wechat_channels_influencer_sales_order_item
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_ks_influencer_sales_order_item
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_tmall_influencer_sales_order
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_jd_influencer_sales_shop_daily_zero
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_xhs_influencer_sales_shop_daily_zero
            UNION ALL
            SELECT stat_date, stat_month, platform_code, platform_name, shop_code, shop_name,
                   influencer_id, influencer_name, influencer_key, gmv_amount, refund_amount,
                   included_sub_order_count, source_updated_at
            FROM dws.dws_pdd_influencer_sales_shop_daily_zero
        ), enriched AS (
            SELECT
                s.*,
                COALESCE(company.company_code, 'unmapped') AS company_code,
                COALESCE(company.company_name, '未匹配公司') AS company_name,
                COALESCE(assignment.business_owner_id, 0) AS business_owner_id,
                COALESCE(assignment.business_owner_name, '未分配商务') AS business_owner_name,
                assignment.effective_month AS assignment_effective_month
            FROM source_rows s
            LEFT JOIN dim.dim_platform_shop_company company
              ON company.platform_code = s.platform_code
             AND company.shop_code = s.shop_code
             AND company.is_active
             AND s.stat_date >= company.valid_from
             AND (company.valid_to IS NULL OR s.stat_date <= company.valid_to)
            LEFT JOIN LATERAL (
                SELECT
                    CASE WHEN a.is_active THEN a.business_owner_id END AS business_owner_id,
                    CASE WHEN a.is_active THEN b.business_owner_name END AS business_owner_name,
                    a.effective_month
                FROM dim.dim_influencer_business_assignment_monthly a
                LEFT JOIN dim.dim_business_owner b
                  ON b.business_owner_id = a.business_owner_id
                WHERE a.platform_code = s.platform_code
                  AND a.influencer_id = s.influencer_id
                  AND a.effective_month <= s.stat_month
                ORDER BY a.effective_month DESC
                LIMIT 1
            ) assignment ON TRUE
        ), expected AS (
            SELECT
                stat_date, stat_month, platform_code, platform_name, company_code, company_name,
                shop_code, shop_name, influencer_id, MAX(influencer_name) AS influencer_name,
                influencer_key, business_owner_id, business_owner_name,
                assignment_effective_month, ROUND(SUM(gmv_amount), 2) AS gmv_amount,
                ROUND(SUM(refund_amount), 2) AS refund_amount,
                COALESCE(ROUND(SUM(refund_amount) / NULLIF(SUM(gmv_amount), 0), 6), 0) AS refund_rate,
                SUM(included_sub_order_count) AS included_sub_order_count,
                MAX(source_updated_at) AS source_updated_at
            FROM enriched
            GROUP BY stat_date, stat_month, platform_code, platform_name, company_code,
                     company_name, shop_code, shop_name, influencer_id, influencer_key,
                     business_owner_id, business_owner_name, assignment_effective_month
        ), actual AS (
            SELECT
                stat_date, stat_month, platform_code, platform_name, company_code, company_name,
                shop_code, shop_name, influencer_id, influencer_name, influencer_key,
                business_owner_id, business_owner_name, assignment_effective_month,
                gmv_amount, refund_amount, refund_rate, included_sub_order_count,
                source_updated_at
            FROM ads.ads_influencer_company_shop_daily
        )
        SELECT
            (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) d),
            (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) d)
        """
    )
    dws_minus_ads, ads_minus_dws = cursor.fetchone()
    cursor.execute(
        """
        WITH expected AS (
            SELECT
                source.stat_date,
                source.stat_month,
                source.platform_code,
                COALESCE(company.company_code, 'unmapped') AS company_code,
                source.shop_code,
                source.influencer_identity_key,
                ROUND(SUM(source.gmv_amount), 2) AS gmv_amount,
                ROUND(SUM(source.refund_amount), 2) AS refund_amount,
                SUM(source.included_sub_order_count) AS included_sub_order_count
            FROM dws.v_influencer_identity_resolved source
            LEFT JOIN dim.dim_platform_shop_company company
              ON company.platform_code = source.platform_code
             AND company.shop_code = source.shop_code
             AND company.is_active
             AND source.stat_date >= company.valid_from
             AND (company.valid_to IS NULL OR source.stat_date <= company.valid_to)
            GROUP BY
                source.stat_date, source.stat_month, source.platform_code,
                COALESCE(company.company_code, 'unmapped'), source.shop_code,
                source.influencer_identity_key
        ), actual AS (
            SELECT
                stat_date, stat_month, platform_code, company_code, shop_code,
                influencer_identity_key, gmv_amount, refund_amount,
                included_sub_order_count
            FROM ads.ads_influencer_company_shop_daily
        )
        SELECT
            (SELECT COUNT(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual) d),
            (SELECT COUNT(*) FROM (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected) d)
        """
    )
    dws_minus_ads, ads_minus_dws = cursor.fetchone()
    if dws_minus_ads or ads_minus_dws:
        raise RuntimeError(
            f"DWS按达人日ADS粒度双向差异非0：{dws_minus_ads}/{ads_minus_dws}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) - COUNT(DISTINCT (
                stat_month, platform_code, company_code, shop_code,
                influencer_identity_key
            )),
            COALESCE(SUM(current_month_gmv), 0),
            COALESCE(SUM(included_sub_order_count), 0),
            COUNT(*) FILTER (WHERE influencer_id = '__no_influencer__' OR current_month_gmv <= 0),
            COUNT(*) FILTER (
                WHERE mom_growth_rate IS DISTINCT FROM CASE
                    WHEN previous_month_gmv = 0 THEN NULL
                    ELSE ROUND((current_month_gmv - previous_month_gmv) / previous_month_gmv, 6)
                END
            )
        FROM ads.ads_influencer_company_shop_monthly_ranking
        """
    )
    ranking = cursor.fetchone()
    if ranking[1] or ranking[4] or ranking[5]:
        raise RuntimeError(
            f"达人月排名ADS失败：duplicates={ranking[1]}, "
            f"placeholder_or_zero={ranking[4]}, ratio_errors={ranking[5]}"
        )
    if (ranking[2], ranking[3]) != (expected_gmv, expected_ranking_orders):
        raise RuntimeError(
            f"月排名ADS与DWS不一致：{(ranking[2], ranking[3])}/"
            f"{(expected_gmv, expected_ranking_orders)}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) - COUNT(DISTINCT (stat_month, business_owner_id)),
            COALESCE(SUM(actual_gmv_amount), 0),
            COALESCE(SUM(refund_amount), 0),
            COUNT(*) FILTER (
                WHERE completion_rate <> COALESCE(ROUND(actual_gmv_amount / NULLIF(gmv_target, 0), 6), 0)
                   OR refund_rate <> COALESCE(ROUND(refund_amount / NULLIF(actual_gmv_amount, 0), 6), 0)
            )
        FROM ads.ads_influencer_business_monthly
        """
    )
    business = cursor.fetchone()
    if business[1] or business[4]:
        raise RuntimeError(
            f"商务月ADS失败：duplicates={business[1]}, ratio_errors={business[4]}"
        )
    if (business[2], business[3]) != (expected_gmv, expected_refund):
        raise RuntimeError(
            f"商务月ADS与DWS不一致：{(business[2], business[3])}/"
            f"{(expected_gmv, expected_refund)}"
        )

    cursor.execute(
        """
        SELECT platform_code, COUNT(*) AS rows,
               COUNT(DISTINCT influencer_identity_key) FILTER (WHERE gmv_amount > 0) AS active_influencers,
               COALESCE(SUM(gmv_amount), 0) AS gmv,
               COALESCE(SUM(refund_amount), 0) AS refund
        FROM ads.ads_influencer_company_shop_daily
        GROUP BY platform_code
        ORDER BY platform_code
        """
    )
    platform_rows = cursor.fetchall()
    return {
        "daily": daily,
        "ranking": ranking,
        "business": business,
        "platform_rows": platform_rows,
        "expected_gmv": expected_gmv,
        "expected_refund": expected_refund,
        "daily_bidirectional_diff": (dws_minus_ads, ads_minus_dws),
    }


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """
            SELECT obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
            """,
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relname = %s
              AND a.attnum > 0 AND NOT a.attisdropped
              AND col_description(c.oid, a.attnum) IS NULL
            ORDER BY a.attnum
            """,
            (schema_name, table_name),
        )
        missing.extend(f"{schema_name}.{table_name}.{row[0]}" for row in cursor.fetchall())
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def fetch_samples(cursor) -> list[tuple]:
    cursor.execute(
        """
        (SELECT '视频号正常' AS sample_type, main_order_no, influencer_id,
                influencer_name, order_status, gmv_amount, refund_amount
         FROM dws.dws_wechat_channels_influencer_sales_order_item
         WHERE order_status <> '已取消'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '视频号退款', main_order_no, influencer_id,
                influencer_name, order_status, gmv_amount, refund_amount
         FROM dws.dws_wechat_channels_influencer_sales_order_item
         WHERE order_status = '已取消'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '快手退款', main_order_no, influencer_id,
                influencer_name, order_status, gmv_amount, refund_amount
         FROM dws.dws_ks_influencer_sales_order_item
         WHERE order_status = '交易关闭'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '天猫胡可归并', main_order_no, influencer_id,
                influencer_name, order_status, gmv_amount, refund_amount
         FROM dws.dws_tmall_influencer_sales_order
         WHERE influencer_name = '胡可'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '天猫退款', main_order_no, influencer_id,
                influencer_name, order_status, gmv_amount, refund_amount
         FROM dws.dws_tmall_influencer_sales_order
         WHERE order_status = '交易关闭'
         ORDER BY source_id LIMIT 1)
        UNION ALL
        (SELECT '拼多多日期兜底', order_no, '__no_influencer__',
                '无达人', stat_date_source, 0::numeric, 0::numeric
         FROM dwd.dwd_pdd_influencer_zero_order_detail
         WHERE stat_date_source = 'order_no_prefix'
         ORDER BY source_id LIMIT 1)
        """
    )
    return cursor.fetchall()


def run_pipeline(args: argparse.Namespace) -> dict[str, object]:
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
            source_rows = validate_sources(cursor)
            mappings = validate_batch_mappings(cursor)
            # 天猫达人DWD/DWS建表脚本会重建目标表；统一身份视图是可派生对象，
            # 先移除后由396号SQL在同一事务内恢复，保证ETL可重复执行。
            cursor.execute("DROP VIEW IF EXISTS dws.v_influencer_identity_resolved")
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            dwd_rows = validate_dwd(cursor, source_rows)
            active_results = validate_active_dws(cursor)
            zero_results = validate_zero_dws(cursor)
            ads_results = validate_ads(cursor, active_results)
            validate_comments(cursor)
            samples = fetch_samples(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "source_rows": source_rows,
        "mappings": mappings,
        "dwd_rows": dwd_rows,
        "active_results": active_results,
        "zero_results": zero_results,
        "ads_results": ads_results,
        "samples": samples,
    }


def print_result(args: argparse.Namespace, result: dict[str, object]) -> None:
    print(f"数据库：{args.dbname}")
    print("ODS/DWD行数：")
    for platform_code, source_rows in result["source_rows"].items():
        print(f"  {platform_code}: {source_rows}/{result['dwd_rows'][platform_code]}")
    print("批次店铺映射：")
    for platform_code, batch_id, rows, _, shop_code, shop_name in result["mappings"]:
        print(f"  {platform_code} 批次{batch_id}: {rows}行 -> {shop_code} / {shop_name}")
    print("有达人平台DWS（行数/活跃达人/GMV/退款/日期）：")
    for platform_code, row in result["active_results"].items():
        print(
            f"  {platform_code}: {row[0]}/{row[3]}/{row[6]:.2f}/{row[7]:.2f}/"
            f"{row[4]}至{row[5]}"
        )
    print("无达人平台补零DWS（店铺日/日期）：")
    for platform_code, row in result["zero_results"].items():
        print(f"  {platform_code}: {row[0]}/{row[3]}至{row[4]}")
    ads = result["ads_results"]
    print(
        "ADS行数（日/月排名/商务月）："
        f"{ads['daily'][0]}/{ads['ranking'][0]}/{ads['business'][0]}"
    )
    print(f"达人总GMV：{ads['expected_gmv']:.2f}")
    print(f"达人总退款：{ads['expected_refund']:.2f}")
    rate = (
        ads["expected_refund"] / ads["expected_gmv"]
        if ads["expected_gmv"]
        else Decimal("0")
    )
    print(f"达人总退款率：{rate:.2%}")
    print(f"DWS与达人日ADS双向差异：{ads['daily_bidirectional_diff'][0]}/{ads['daily_bidirectional_diff'][1]}")
    print("平台汇总（平台/ADS行数/活跃达人/GMV/退款）：")
    for row in ads["platform_rows"]:
        print(f"  {row}")
    print("公式抽样（类型/订单/达人ID/达人/状态/GMV/退款）：")
    for row in result["samples"]:
        print(f"  {row}")


if __name__ == "__main__":
    parsed_args = build_parser().parse_args()
    print_result(parsed_args, run_pipeline(parsed_args))
