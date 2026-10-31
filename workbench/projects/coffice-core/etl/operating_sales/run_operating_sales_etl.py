#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量刷新抖音、视频号、京东、快手、小红书、拼多多和天猫运营成交链路。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.report_sources import prepare_report_sources
from etl.common.product_mapping_workbench import lock_product_refresh, publish_workbench

PREPARE_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
    "dim/183_dim_influencer_product_category_postgres.sql",
    "dim/200_dim_company_product_code_mapping_postgres.sql",
    "dim/203_normalize_influencer_product_catalog_postgres.sql",
    "dim/204_enforce_product_code_one_to_one_postgres.sql",
    "dim/393_dim_product_source_mapping_postgres.sql",
    "dim/427_refactor_company_product_identity_postgres.sql",
    "dim/304_seed_tmall_shopping_fund_product_postgres.sql",
    "dim/306_seed_tmall_preorder_voucher_product_postgres.sql",
    "dim/305_seed_red_envelope_product_postgres.sql",
    "dim/428_seed_company_product_alias_rules_postgres.sql",
    "dim/429_company_product_code_normalization_rules_postgres.sql",
    "common/457_product_mapping_refresh_state_postgres.sql",
    "ads/operating_sales/458_ads_product_code_mapping_workbench_postgres.sql",
]

CREATE_SQL_FILES = [
    "douyin/operating_sales/156_dwd_douyin_operating_sales_order_item_detail_postgres.sql",
    "douyin/operating_sales/157_dws_douyin_operating_sales_order_item_postgres.sql",
    "douyin/operating_sales/201_dws_douyin_operating_sales_product_allocation_postgres.sql",
    "tmall/operating_sales/298_dwd_tmall_operating_sales_order_item_detail_postgres.sql",
    "tmall/operating_sales/299_dws_tmall_operating_sales_order_item_postgres.sql",
    "tmall/operating_sales/300_dws_tmall_operating_sales_product_allocation_postgres.sql",
    "wechat_channels/operating_sales/246_dwd_wechat_channels_operating_sales_order_item_detail_postgres.sql",
    "wechat_channels/operating_sales/247_dws_wechat_channels_operating_sales_order_item_postgres.sql",
    "wechat_channels/operating_sales/248_dws_wechat_channels_operating_sales_product_allocation_postgres.sql",
    "jd/operating_sales/249_dwd_jd_operating_sales_order_item_detail_postgres.sql",
    "jd/operating_sales/250_dws_jd_operating_sales_order_item_postgres.sql",
    "jd/operating_sales/251_dws_jd_operating_sales_product_allocation_postgres.sql",
    "ks/operating_sales/252_dwd_ks_operating_sales_order_item_detail_postgres.sql",
    "ks/operating_sales/253_dws_ks_operating_sales_order_item_postgres.sql",
    "ks/operating_sales/254_dws_ks_operating_sales_product_allocation_postgres.sql",
    "xhs/operating_sales/255_dwd_xhs_operating_sales_order_item_detail_postgres.sql",
    "xhs/operating_sales/256_dws_xhs_operating_sales_order_item_postgres.sql",
    "xhs/operating_sales/257_dws_xhs_operating_sales_product_allocation_postgres.sql",
    "pdd/operating_sales/258_dwd_pdd_operating_sales_order_item_detail_postgres.sql",
    "pdd/operating_sales/259_dws_pdd_operating_sales_order_item_postgres.sql",
    "pdd/operating_sales/260_dws_pdd_operating_sales_product_allocation_postgres.sql",
    "common/276_operating_sales_product_allocation_refresh_helper_postgres.sql",
    "common/398_operating_sales_product_code_observation_view_postgres.sql",
    "ads/operating_sales/158_ads_operating_sales_company_shop_daily_postgres.sql",
    "ads/operating_sales/159_ads_operating_sales_traffic_company_shop_daily_postgres.sql",
    "ads/operating_sales/160_ads_operating_sales_product_company_shop_daily_postgres.sql",
]

REFRESH_SQL_FILES = [
    "douyin/operating_sales/161_refresh_dwd_douyin_operating_sales_order_item_detail_postgres.sql",
    "douyin/operating_sales/162_refresh_dws_douyin_operating_sales_order_item_postgres.sql",
    "douyin/operating_sales/202_refresh_dws_douyin_operating_sales_product_allocation_postgres.sql",
    "wechat_channels/operating_sales/261_refresh_dwd_wechat_channels_operating_sales_order_item_detail_postgres.sql",
    "wechat_channels/operating_sales/262_refresh_dws_wechat_channels_operating_sales_order_item_postgres.sql",
    "wechat_channels/operating_sales/263_refresh_dws_wechat_channels_operating_sales_product_allocation_postgres.sql",
    "jd/operating_sales/264_refresh_dwd_jd_operating_sales_order_item_detail_postgres.sql",
    "jd/operating_sales/265_refresh_dws_jd_operating_sales_order_item_postgres.sql",
    "jd/operating_sales/266_refresh_dws_jd_operating_sales_product_allocation_postgres.sql",
    "ks/operating_sales/267_refresh_dwd_ks_operating_sales_order_item_detail_postgres.sql",
    "ks/operating_sales/268_refresh_dws_ks_operating_sales_order_item_postgres.sql",
    "ks/operating_sales/269_refresh_dws_ks_operating_sales_product_allocation_postgres.sql",
    "xhs/operating_sales/270_refresh_dwd_xhs_operating_sales_order_item_detail_postgres.sql",
    "xhs/operating_sales/271_refresh_dws_xhs_operating_sales_order_item_postgres.sql",
    "xhs/operating_sales/272_refresh_dws_xhs_operating_sales_product_allocation_postgres.sql",
    "pdd/operating_sales/273_refresh_dwd_pdd_operating_sales_order_item_detail_postgres.sql",
    "pdd/operating_sales/274_refresh_dws_pdd_operating_sales_order_item_postgres.sql",
    "pdd/operating_sales/275_refresh_dws_pdd_operating_sales_product_allocation_postgres.sql",
    "tmall/operating_sales/301_refresh_dwd_tmall_operating_sales_order_item_detail_postgres.sql",
    "tmall/operating_sales/302_refresh_dws_tmall_operating_sales_order_item_postgres.sql",
    "tmall/operating_sales/303_refresh_dws_tmall_operating_sales_product_allocation_postgres.sql",
    "ads/operating_sales/163_refresh_ads_operating_sales_company_shop_daily_postgres.sql",
    "ads/operating_sales/164_refresh_ads_operating_sales_traffic_company_shop_daily_postgres.sql",
    "ads/operating_sales/165_refresh_ads_operating_sales_product_company_shop_daily_postgres.sql",
]

PLATFORMS = {
    "douyin": {
        "name": "抖音",
        "ods": "ods_douyin_order_raw",
        "dwd": "dwd_douyin_operating_sales_order_item_detail",
        "dws": "dws_douyin_operating_sales_order_item",
        "product_dws": "dws_douyin_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "主订单编号", "子订单编号", "订单提交时间", "订单状态", "售后状态",
            "商品ID", "商家编码", "选购商品", "商品规格", "商品数量",
            "商品单价", "订单应付金额", "流量体裁", "流量渠道",
        },
        "numeric": ("商品数量", "商品单价", "订单应付金额"),
        "date": "订单提交时间",
        "order": "主订单编号",
        "source_expected_sql": 'COUNT(DISTINCT NULLIF(BTRIM("子订单编号"), \'\'))',
        "refund_predicate": "order_status = '已关闭'",
        "baseline": (19469, 19405, 9529, Decimal("1567842.00"), Decimal("443054.40"), Decimal("9191.00"), 13643, 411, 613),
    },
    "wechat_channels": {
        "name": "视频号",
        "ods": "ods_wechat_channels_order_raw",
        "dwd": "dwd_wechat_channels_operating_sales_order_item_detail",
        "dws": "dws_wechat_channels_operating_sales_order_item",
        "product_dws": "dws_wechat_channels_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单下单时间", "订单状态", "商品售后", "商品编码(平台)",
            "SKU编码(自定义)", "商品名称", "商品属性", "商品数量",
            "商品价格(单件)", "订单实际支付金额", "带货方式", "带货账号类型",
        },
        "numeric": ("商品数量", "商品价格(单件)", "订单实际支付金额"),
        "date": "订单下单时间",
        "order": "订单号",
        "source_expected_sql": "COUNT(*)",
        "refund_predicate": "order_status = '已取消'",
        "baseline": (452, 452, 444, Decimal("83247.90"), Decimal("14555.00"), Decimal("478.00"), 821, 32, 38),
    },
    "jd": {
        "name": "京东",
        "ods": "ods_jd_order_raw",
        "dwd": "dwd_jd_operating_sales_order_item_detail",
        "dws": "dws_jd_operating_sales_order_item",
        "product_dws": "dws_jd_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "商品ID", "商品名称", "订购数量", "下单时间", "京东价",
            "应付金额", "订单状态", "订单来源", "订单渠道", "商家SKUID",
        },
        "numeric": ("订购数量", "京东价", "应付金额"),
        "date": "下单时间",
        "order": "订单号",
        "source_expected_sql": "COUNT(*)",
        "refund_predicate": "order_status LIKE '(删除)%'",
        "baseline": (35, 35, 34, Decimal("3955.20"), Decimal("1378.00"), Decimal("35.00"), 54, 25, 30),
    },
    "ks": {
        "name": "快手",
        "ods": "ods_ks_order_raw",
        "dwd": "dwd_ks_operating_sales_order_item_detail",
        "dws": "dws_ks_operating_sales_order_item",
        "product_dws": "dws_ks_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单创建时间", "订单状态", "实付款", "成交数量",
            "售后状态", "订单载体", "商品名称", "商品ID", "商品规格",
            "SKU编码", "商品单价", "渠道",
        },
        "numeric": ("成交数量", "商品单价", "实付款"),
        "date": "订单创建时间",
        "order": "订单号",
        "source_expected_sql": "COUNT(*)",
        "refund_predicate": "order_status = '交易关闭'",
        "baseline": (1378, 1342, 1340, Decimal("170306.10"), Decimal("88290.00"), Decimal("1404.00"), 1826, 843, 1663),
    },
    "xhs": {
        "name": "小红书",
        "ods": "ods_xhs_order_raw",
        "dwd": "dwd_xhs_operating_sales_order_item_detail",
        "dws": "dws_xhs_operating_sales_order_item",
        "product_dws": "dws_xhs_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "订单号", "订单状态", "售后状态", "SKU名称", "SKU规格", "SKU件数",
            "商品总价(元)", "用户应付金额(元)", "订单创建时间", "店铺名称",
            "商家编码", "商品ID",
        },
        "numeric": ("SKU件数", "商品总价(元)", "用户应付金额(元)"),
        "date": "订单创建时间",
        "order": "订单号",
        "source_expected_sql": "COUNT(*)",
        "refund_predicate": "FALSE",
        "baseline": (12, 12, 9, Decimal("902.40"), Decimal("0.00"), Decimal("12.00"), 17, 5, 9),
    },
    "pdd": {
        "name": "拼多多",
        "ods": "ods_pdd_order_raw",
        "dwd": "dwd_pdd_operating_sales_order_item_detail",
        "dws": "dws_pdd_operating_sales_order_item",
        "product_dws": "dws_pdd_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_row_no", "ingest_time",
            "商品", "订单号", "订单状态", "商品总价(元)", "用户实付金额(元)",
            "商品数量(件)", "商品id", "商品规格", "商家编码-规格维度",
            "售后状态", "订单成交时间",
        },
        "numeric": ("商品数量(件)", "商品总价(元)", "用户实付金额(元)"),
        "date": "订单成交时间",
        "order": "订单号",
        "source_expected_sql": "COUNT(*)",
        "refund_predicate": "order_status = '已取消' OR order_status LIKE '%退款成功%'",
        "baseline": (1116, 1116, 1116, Decimal("135041.30"), Decimal("39956.50"), Decimal("1121.00"), 1116, 750, 769),
    },
    "tmall": {
        "name": "天猫",
        "ods": "ods_tmall_order_raw",
        "dwd": "dwd_tmall_operating_sales_order_item_detail",
        "dws": "dws_tmall_operating_sales_order_item",
        "product_dws": "dws_tmall_operating_sales_product_allocation",
        "required": {
            "id", "batch_id", "source_file_name", "source_sheet_name",
            "source_row_no", "ingest_time", "子订单编号", "主订单编号",
            "商品标题", "购买数量", "商品属性", "订单状态", "商家编码",
            "买家应付货款", "订单创建时间",
        },
        "numeric": ("购买数量", "买家应付货款"),
        "numeric_allow_blank": ("买家应付货款",),
        "date": "订单创建时间",
        "order": "主订单编号",
        "source_expected_sql": 'COUNT(DISTINCT NULLIF(BTRIM("子订单编号"), \'\'))',
        "refund_predicate": "order_status = '交易关闭'",
        "effective_gmv_sql": (
            "CASE WHEN COALESCE(product_name, '') = 'MOCK推荐官' "
            "OR COALESCE(product_name, '') LIKE '%赠品勿拍%' "
            "THEN 0 ELSE product_unit_price END"
        ),
        "brush_rule": "main_order_sum_gt",
        "baseline": (
            1098, 1098, 558, Decimal("64891.08"), Decimal("9157.84"),
            Decimal("568.00"), 741,
        ),
    },
}

NEW_TABLES = [
    *(("dwd", config["dwd"]) for code, config in PLATFORMS.items() if code != "douyin"),
    *(("dws", config["dws"]) for code, config in PLATFORMS.items() if code != "douyin"),
    *(("dws", config["product_dws"]) for code, config in PLATFORMS.items() if code != "douyin"),
    ("ads", "ads_operating_sales_company_shop_daily"),
    ("ads", "ads_operating_sales_traffic_company_shop_daily"),
    ("ads", "ads_operating_sales_product_company_shop_daily"),
    ("ads", "ads_product_code_mapping_workbench"),
    ("ops", "product_mapping_refresh_state"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新七平台运营成交GMV、退款、订单、件单价和占比图数据。")
    parser.add_argument(
        "--product-mapping-file",
        default=os.getenv("PRODUCT_MAPPING_FILE"),
        help=(
            "可选：显式指定产品编码Excel时，在本次事务中同步到DIM；"
            "未指定时直接使用数据库中的产品编码映射，不依赖本地文件。"
        ),
    )
    parser.add_argument(
        "--skip-product-mapping-load",
        action="store_true",
        help="兼容旧调用；设置后即使指定了产品编码文件也不加载。",
    )
    parser.add_argument(
        "--enforce-current-baseline",
        action="store_true",
        help="按当前探查报告校验固定行数和金额；新批次上线后不要使用。",
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    prepare_report_sources(cursor, ('douyin', 'tmall', 'jd', 'ks', 'pdd', 'xhs', 'wechat_channels'), pdd_settlement=False)
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_sources(cursor) -> dict[str, dict[str, object]]:
    source_summary: dict[str, dict[str, object]] = {}
    numeric_pattern = r"^-?[0-9]+(\.[0-9]+)?$"
    for platform_code, config in PLATFORMS.items():
        runtime = getattr(cursor.connection, 'refresh_scope', None)
        if runtime is not None and not runtime.full and platform_code not in runtime.platforms:
            continue
        ods_table = config["ods"]
        cursor.execute("SELECT to_regclass(%s)", (f"ods.{ods_table}",))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少来源表：ods.{ods_table}")

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'ods' AND table_name = %s
            """,
            (ods_table,),
        )
        actual_columns = {row[0] for row in cursor.fetchall()}
        missing = sorted(config["required"] - actual_columns)
        if missing:
            raise RuntimeError(f"{config['name']}ODS缺少必需字段：{', '.join(missing)}")

        cursor.execute(
            sql.SQL("SELECT COUNT(*), {} FROM common.{} r "
                    "JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id").format(
                sql.SQL('COUNT(DISTINCT (c.shop_identity_key,NULLIF(BTRIM(r."子订单编号"),\'\')))'
                        if platform_code in {'douyin','tmall'} else config["source_expected_sql"]),
                sql.Identifier("v_current_" + platform_code + "_order_raw"),
            )
        )
        source_rows, expected_dwd_rows = cursor.fetchone()
        if not source_rows:
            source_summary[platform_code] = {
                "source_rows": 0,
                "expected_dwd_rows": 0,
                "mappings": [],
            }
            print(f"[WARN] {config['name']}订单ODS为空，按0值刷新该平台")
            continue

        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) FROM ods.{} "
                "WHERE NULLIF(BTRIM({}, E' \\t\\r\\n'), '') IS NULL"
            ).format(sql.Identifier(ods_table), sql.Identifier(config["order"]))
        )
        missing_orders = cursor.fetchone()[0]
        if missing_orders:
            raise RuntimeError(f"{config['name']}订单号为空：{missing_orders}条")

        invalid_numeric: dict[str, int] = {}
        for column_name in config["numeric"]:
            allow_blank = column_name in config.get("numeric_allow_blank", ())
            cursor.execute(
                sql.SQL(
                    "SELECT COUNT(*) FROM ods.{} "
                    "WHERE {} COALESCE("
                    "REGEXP_REPLACE(BTRIM({}), '[,¥￥[:space:]]', '', 'g'),"
                    "'') !~ %s"
                ).format(
                    sql.Identifier(ods_table),
                    sql.SQL(
                        "COALESCE(REGEXP_REPLACE(BTRIM({}), '[,¥￥[:space:]]', '', 'g'), '') <> '' AND "
                    ).format(sql.Identifier(column_name))
                    if allow_blank
                    else sql.SQL(""),
                    sql.Identifier(column_name),
                ),
                (numeric_pattern,),
            )
            invalid_count = cursor.fetchone()[0]
            if invalid_count:
                invalid_numeric[column_name] = invalid_count
        if invalid_numeric:
            raise RuntimeError(f"{config['name']}数量或金额解析失败：{invalid_numeric}")

        if platform_code == "pdd":
            cursor.execute(
                sql.SQL(
                    """
                    SELECT COUNT(*)
                    FROM ods.{}
                    WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NULL
                      AND BTRIM({}) !~ '^[0-9]{{6}}'
                    """
                ).format(
                    sql.Identifier(ods_table),
                    sql.Identifier(config["date"]),
                    sql.Identifier(config["order"]),
                )
            )
        else:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT COUNT(*)
                    FROM ods.{}
                    WHERE NULLIF(NULLIF(BTRIM({}), ''), '-') IS NULL
                       OR BTRIM({}) !~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}'
                    """
                ).format(
                    sql.Identifier(ods_table),
                    sql.Identifier(config["date"]),
                    sql.Identifier(config["date"]),
                )
            )
        invalid_dates = cursor.fetchone()[0]
        if invalid_dates:
            raise RuntimeError(f"{config['name']}成交日期为空或格式无法解析：{invalid_dates}条")

        cursor.execute(
            sql.SQL(
                """
                WITH source_batches AS (
                    SELECT batch_id, COUNT(*) AS source_rows
                    FROM ods.{}
                    GROUP BY batch_id
                )
                SELECT
                    b.batch_id,
                    b.source_rows,
                    COUNT(c.batch_id) AS mapping_count,
                    MAX(c.shop_code) AS shop_code,
                    MAX(c.shop_name) AS shop_name,
                    MAX(c.shop_mapping_status) AS mapping_status
                FROM source_batches b
                LEFT JOIN common.v_ingest_batch_shop_context c
                  ON c.batch_id = b.batch_id
                 AND c.platform_code = %s
                 AND c.target_table = %s
                 AND c.shop_mapping_status = 'mapped'
                GROUP BY b.batch_id, b.source_rows
                ORDER BY b.batch_id
                """
            ).format(sql.Identifier(ods_table)),
            (platform_code, ods_table),
        )
        mappings = cursor.fetchall()
        invalid_mappings = [row for row in mappings if row[0] is None or row[2] != 1]
        if invalid_mappings:
            raise RuntimeError(f"{config['name']}批次店铺映射缺失或冲突：{invalid_mappings}")

        source_summary[platform_code] = {
            "source_rows": source_rows,
            "expected_dwd_rows": expected_dwd_rows,
            "mappings": mappings,
        }
    return source_summary


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """
            SELECT
                obj_description(to_regclass(%s), 'pg_class'),
                COUNT(*) FILTER (
                    WHERE col_description(c.oid, a.attnum) IS NULL
                       OR BTRIM(col_description(c.oid, a.attnum)) = ''
                )
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a
              ON a.attrelid = c.oid
             AND a.attnum > 0
             AND NOT a.attisdropped
            WHERE n.nspname = %s AND c.relname = %s
            GROUP BY c.oid
            """,
            (f"{schema_name}.{table_name}", schema_name, table_name),
        )
        row = cursor.fetchone()
        if row is None or not row[0] or row[1]:
            missing.append(f"{schema_name}.{table_name}")
    if missing:
        raise RuntimeError(f"表或字段注释不完整：{', '.join(missing)}")


def validate_platform_layers(
    cursor,
    source_summary: dict[str, dict[str, object]],
    enforce_baseline: bool,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for platform_code, config in PLATFORMS.items():
        if platform_code not in source_summary:
            continue
        dwd_table = config["dwd"]
        dws_table = config["dws"]
        product_table = config["product_dws"]

        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) - COUNT(DISTINCT (shop_code,sub_order_no)),
                    COUNT(*) FILTER (WHERE gmv_amount <> product_unit_price),
                    COUNT(*) FILTER (WHERE stat_date IS NULL)
                FROM dwd.{}
                """
            ).format(sql.Identifier(dwd_table))
        )
        dwd_rows, dwd_duplicates, dwd_formula_errors, missing_dates = cursor.fetchone()
        expected_dwd_rows = source_summary[platform_code]["expected_dwd_rows"]
        if dwd_rows != expected_dwd_rows or dwd_duplicates or dwd_formula_errors or missing_dates:
            raise RuntimeError(
                f"{config['name']}DWD失败：rows={dwd_rows}/{expected_dwd_rows}, "
                f"duplicates={dwd_duplicates}, formula={dwd_formula_errors}, dates={missing_dates}"
            )

        brush_predicate = (
            """
            (
                SELECT COALESCE(SUM(brush.order_pay_amount), 0)
                FROM dwd.{table} brush
                WHERE brush.platform_code = d.platform_code
                  AND brush.shop_code = d.shop_code
                  AND brush.main_order_no = d.main_order_no
            ) > 2000
            """
            if config.get("brush_rule") == "main_order_sum_gt"
            else
            """
            EXISTS (
                SELECT 1
                FROM dwd.{table} brush
                WHERE brush.platform_code = d.platform_code
                  AND brush.shop_code = d.shop_code
                  AND brush.main_order_no = d.main_order_no
                  AND brush.order_pay_amount >= 2000
            )
            """
        ).format(table=dwd_table)
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM dwd.{} d WHERE ").format(
                sql.Identifier(dwd_table)
            )
            + sql.SQL(brush_predicate)
        )
        excluded_rows = cursor.fetchone()[0]

        effective_gmv_sql = config.get("effective_gmv_sql", "product_unit_price")
        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) - COUNT(DISTINCT (shop_code,sub_order_no)),
                    COUNT(DISTINCT (shop_code,main_order_no)),
                    MIN(stat_date),
                    MAX(stat_date),
                    COALESCE(SUM(gmv_amount), 0),
                    COALESCE(SUM(refund_amount), 0),
                    COALESCE(SUM(sold_unit_count), 0),
                    COUNT(*) FILTER (
                        WHERE gmv_amount <> {}
                           OR refund_amount <> CASE WHEN {} THEN {} ELSE 0 END
                           OR is_closed_refund <> ({})
                           OR sold_unit_count <> CASE WHEN {} > 0 THEN (
                               SELECT product_quantity
                               FROM dwd.{} source
                               WHERE source.platform_code = d.platform_code
                                 AND source.shop_code = d.shop_code
                                 AND source.sub_order_no = d.sub_order_no
                           ) ELSE 0 END
                    )
                FROM dws.{} d
                """
            ).format(
                sql.SQL(effective_gmv_sql),
                sql.SQL(config["refund_predicate"]),
                sql.SQL(effective_gmv_sql),
                sql.SQL(config["refund_predicate"]),
                sql.SQL(effective_gmv_sql),
                sql.Identifier(dwd_table),
                sql.Identifier(dws_table),
            )
        )
        (
            dws_rows,
            dws_duplicates,
            order_count,
            min_date,
            max_date,
            gmv_amount,
            refund_amount,
            sold_units,
            formula_errors,
        ) = cursor.fetchone()
        if dws_rows != dwd_rows - excluded_rows or dws_duplicates or formula_errors:
            raise RuntimeError(
                f"{config['name']}DWS失败：rows={dws_rows}/{dwd_rows - excluded_rows}, "
                f"duplicates={dws_duplicates}, formula={formula_errors}"
            )

        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) - COUNT(DISTINCT (
                        platform_code, shop_code, sub_order_no, component_index
                    )),
                    COUNT(DISTINCT (shop_code,sub_order_no)),
                    COALESCE(SUM(allocated_gmv_amount), 0),
                    COUNT(*) FILTER (WHERE NOT is_mapped),
                    COUNT(DISTINCT merchant_code_component) FILTER (WHERE NOT is_mapped),
                    COALESCE(SUM(allocated_gmv_amount) FILTER (WHERE NOT is_mapped), 0),
                    COUNT(*) FILTER (WHERE paid_quantity > 0),
                    COUNT(*) FILTER (WHERE is_gift),
                    COALESCE(SUM(gift_quantity), 0),
                    COUNT(DISTINCT (shop_code,sub_order_no)) FILTER (WHERE source_line_gmv_amount > 0)
                FROM dws.{}
                """
            ).format(sql.Identifier(product_table))
        )
        (
            product_rows,
            product_duplicates,
            product_source_rows,
            product_gmv,
            unmapped_components,
            unmapped_distinct_codes,
            unmapped_gmv,
            paid_component_rows,
            gift_component_rows,
            gift_unit_count,
            positive_product_source_rows,
        ) = cursor.fetchone()
        unmapped_samples = []
        if unmapped_components:
            cursor.execute(
                sql.SQL(
                    """
                    SELECT merchant_code_component, COUNT(*) AS component_rows,
                           COALESCE(SUM(allocated_gmv_amount), 0) AS allocated_gmv
                    FROM dws.{}
                    WHERE NOT is_mapped
                    GROUP BY merchant_code_component
                    ORDER BY component_rows DESC, merchant_code_component
                    LIMIT 20
                    """
                ).format(sql.Identifier(product_table))
            )
            unmapped_samples = [
                {
                    "code": row[0],
                    "rows": row[1],
                    "gmv": row[2],
                }
                for row in cursor.fetchall()
            ]
        cursor.execute(
            sql.SQL(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT sub_order_no
                    FROM dws.{}
                    GROUP BY sub_order_no
                    HAVING SUM(allocated_gmv_amount) <> MAX(source_line_gmv_amount)
                       OR ABS(
                            SUM(allocation_weight)
                            - CASE WHEN MAX(source_line_gmv_amount) > 0 THEN 1 ELSE 0 END
                          ) > 0.00000001
                       OR COUNT(*) <> MAX(source_component_count)
                       OR COUNT(*) FILTER (WHERE paid_quantity > 0)
                            <> MAX(paid_component_count)
                       OR COUNT(*) FILTER (
                            WHERE is_gift AND allocated_gmv_amount <> 0
                          ) > 0
                ) errors
                """
            ).format(sql.Identifier(product_table))
        )
        product_formula_errors = cursor.fetchone()[0]
        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(gift_quantity), 0)
                FROM (
                    SELECT
                        sub_order_no,
                        MAX(source_component_count) AS source_component_count,
                        MAX(paid_component_count) AS paid_component_count,
                        COALESCE(MAX(gift_quantity) FILTER (WHERE source_component_count = 1), 0)
                            + COALESCE(SUM(gift_quantity) FILTER (WHERE source_component_count > 1), 0)
                            AS gift_quantity
                    FROM dws.{}
                    GROUP BY sub_order_no
                ) gift_rules
                WHERE gift_quantity > 0
                """
            ).format(sql.Identifier(product_table))
        )
        gift_rows, excluded_gift_components = cursor.fetchone()
        cursor.execute(
            sql.SQL("SELECT COUNT(*), COALESCE(SUM(gmv_amount), 0) FROM dws.{} WHERE gmv_amount > 0").format(
                sql.Identifier(dws_table)
            )
        )
        positive_rows, positive_gmv = cursor.fetchone()
        if (
            product_duplicates
            or product_formula_errors
            or positive_product_source_rows != positive_rows
            or product_gmv != positive_gmv
        ):
            raise RuntimeError(
                f"{config['name']}产品分摊失败：rows={product_rows}, "
                f"source={product_source_rows}/{positive_rows}, gmv={product_gmv}/{positive_gmv}, "
                f"unmapped={unmapped_components}, formula={product_formula_errors}, "
                f"unmapped_codes={unmapped_samples}"
            )

        if unmapped_components:
            print(
                "[WARN] "
                f"{config['name']}商品编码未配置："
                f"rows={unmapped_components}, distinct_codes={unmapped_distinct_codes}, "
                f"gmv={unmapped_gmv}, samples={unmapped_samples}",
                file=sys.stderr,
            )

        baseline = config["baseline"]
        if enforce_baseline:
            actual = (
                dwd_rows, dws_rows, order_count, gmv_amount, refund_amount,
                sold_units, product_rows, gift_rows, excluded_gift_components,
            )
            if actual[: len(baseline)] != baseline:
                raise RuntimeError(f"{config['name']}当前基准不一致：actual={actual}, expected={baseline}")

        result[platform_code] = {
            "name": config["name"],
            "dwd_rows": dwd_rows,
            "excluded_rows": excluded_rows,
            "dws_rows": dws_rows,
            "orders": order_count,
            "min_date": min_date,
            "max_date": max_date,
            "gmv": gmv_amount,
            "refund": refund_amount,
            "sold_units": sold_units,
            "unit_price": (gmv_amount / sold_units).quantize(Decimal("0.01")) if sold_units else Decimal("0"),
            "refund_rate": (refund_amount / gmv_amount).quantize(Decimal("0.000001")) if gmv_amount else Decimal("0"),
            "product_components": paid_component_rows,
            "all_product_components": product_rows,
            "gift_rows": gift_rows,
            "gift_components": gift_component_rows,
            "gift_units": gift_unit_count,
            "excluded_gift_components": excluded_gift_components,
            "unmapped_components": unmapped_components,
            "unmapped_distinct_codes": unmapped_distinct_codes,
            "unmapped_gmv": unmapped_gmv,
            "unmapped_samples": unmapped_samples,
        }
    return result


def validate_ads(cursor, platform_result: dict[str, dict[str, object]], enforce_baseline: bool) -> dict[str, object]:
    cursor.execute(
        """
        WITH source_union AS (
            SELECT * FROM dws.dws_douyin_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_jd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_ks_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_order_item
        ), expected AS (
            SELECT
                d.stat_date,
                d.platform_code,
                COALESCE(m.company_code, 'unmapped') AS company_code,
                d.shop_code,
                ROUND(SUM(d.gmv_amount), 2) AS gmv_amount,
                ROUND(SUM(d.refund_amount), 2) AS refund_amount,
                COUNT(DISTINCT d.main_order_no) AS transaction_order_count,
                ROUND(SUM(d.sold_unit_count), 2) AS sold_unit_count,
                SUM(d.included_sub_order_count) AS included_sub_order_count
            FROM source_union d
            LEFT JOIN dim.dim_platform_shop_company m
              ON m.platform_code = d.platform_code
             AND m.shop_code = d.shop_code
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
            GROUP BY d.stat_date, d.platform_code,
                     COALESCE(m.company_code, 'unmapped'), d.shop_code
        ), actual AS (
            SELECT
                stat_date, platform_code, company_code, shop_code,
                gmv_amount, refund_amount, transaction_order_count,
                sold_unit_count, included_sub_order_count
            FROM ads.ads_operating_sales_company_shop_daily
        ), differences AS (
            (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
        )
        SELECT COUNT(*) FROM differences
        """
    )
    card_bidirectional_differences = cursor.fetchone()[0]

    cursor.execute(
        """
        WITH source_union AS (
            SELECT * FROM dws.dws_douyin_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_jd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_ks_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_order_item
        ), expected AS (
            SELECT
                d.stat_date,
                d.platform_code,
                COALESCE(m.company_code, 'unmapped') AS company_code,
                d.shop_code,
                COALESCE(NULLIF(BTRIM(d.traffic_content_type), ''), '未提供')
                    AS traffic_content_type,
                COALESCE(NULLIF(BTRIM(d.traffic_channel), ''), '未提供')
                    AS traffic_channel,
                ROUND(SUM(d.gmv_amount), 2) AS gmv_amount,
                SUM(d.included_sub_order_count) AS included_sub_order_count
            FROM source_union d
            LEFT JOIN dim.dim_platform_shop_company m
              ON m.platform_code = d.platform_code
             AND m.shop_code = d.shop_code
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
            GROUP BY d.stat_date, d.platform_code,
                     COALESCE(m.company_code, 'unmapped'), d.shop_code,
                     COALESCE(NULLIF(BTRIM(d.traffic_content_type), ''), '未提供'),
                     COALESCE(NULLIF(BTRIM(d.traffic_channel), ''), '未提供')
        ), actual AS (
            SELECT
                stat_date, platform_code, company_code, shop_code,
                traffic_content_type, traffic_channel,
                gmv_amount, included_sub_order_count
            FROM ads.ads_operating_sales_traffic_company_shop_daily
        ), differences AS (
            (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
        )
        SELECT COUNT(*) FROM differences
        """
    )
    traffic_bidirectional_differences = cursor.fetchone()[0]

    cursor.execute(
        """
        WITH source_union AS (
            SELECT * FROM dws.dws_douyin_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_jd_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_ks_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_product_allocation
            UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_product_allocation
        ), expected AS (
            SELECT
                d.stat_date,
                d.platform_code,
                COALESCE(m.company_code, 'unmapped') AS company_code,
                d.shop_code,
                COALESCE(d.company_product_id, 'unmapped:' || d.code_expression) AS product_id,
                COALESCE(d.company_product_code, d.code_expression) AS company_product_code,
                COALESCE(d.product_type, 'unmapped') AS product_type,
                d.large_product_category,
                d.product_category_l2,
                d.product_name,
                ROUND(SUM(d.allocated_gmv_amount), 2) AS gmv_amount,
                COUNT(*) FILTER (WHERE d.paid_quantity > 0) AS paid_component_count,
                COUNT(*) FILTER (WHERE d.is_gift) AS gift_component_count,
                COUNT(*) FILTER (WHERE d.is_mapped) AS mapped_component_count,
                COUNT(*) FILTER (WHERE NOT d.is_mapped) AS unmapped_component_count,
                ROUND(SUM(d.paid_quantity), 2) AS paid_unit_count,
                ROUND(SUM(d.gift_quantity), 2) AS gift_unit_count,
                COUNT(DISTINCT d.sub_order_no) AS source_sub_order_count
            FROM source_union d
            LEFT JOIN dim.dim_platform_shop_company m
              ON m.platform_code = d.platform_code
             AND m.shop_code = d.shop_code
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
            GROUP BY d.stat_date, d.platform_code,
                     COALESCE(m.company_code, 'unmapped'), d.shop_code,
                     COALESCE(d.company_product_id, 'unmapped:' || d.code_expression),
                     COALESCE(d.company_product_code, d.code_expression),
                     COALESCE(d.product_type, 'unmapped'),
                     d.large_product_category, d.product_category_l2, d.product_name
        ), actual AS (
            SELECT
                stat_date, platform_code, company_code, shop_code,
                product_id, company_product_code, product_type,
                large_product_category, product_category_l2, product_name,
                gmv_amount, paid_component_count, gift_component_count,
                mapped_component_count, unmapped_component_count,
                paid_unit_count, gift_unit_count, source_sub_order_count
            FROM ads.ads_operating_sales_product_company_shop_daily
        ), differences AS (
            (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
        )
        SELECT COUNT(*) FROM differences
        """
    )
    product_bidirectional_differences = cursor.fetchone()[0]
    if (
        card_bidirectional_differences
        or traffic_bidirectional_differences
        or product_bidirectional_differences
    ):
        raise RuntimeError(
            "DWS与三张ADS最终粒度双向核对失败："
            f"{card_bidirectional_differences}/"
            f"{traffic_bidirectional_differences}/"
            f"{product_bidirectional_differences}"
        )

    cursor.execute(
        """
        SELECT
            COUNT(*),
            COUNT(*) - COUNT(DISTINCT (stat_date, platform_code, company_code, shop_code)),
            MIN(stat_date),
            MAX(stat_date),
            COALESCE(SUM(gmv_amount), 0),
            COALESCE(SUM(refund_amount), 0),
            COALESCE(SUM(transaction_order_count), 0),
            COALESCE(SUM(sold_unit_count), 0),
            COUNT(*) FILTER (
                WHERE refund_rate <> COALESCE(ROUND(refund_amount / NULLIF(gmv_amount, 0), 6), 0)
                   OR transaction_unit_price <> COALESCE(ROUND(gmv_amount / NULLIF(sold_unit_count, 0), 2), 0)
            )
        FROM ads.ads_operating_sales_company_shop_daily
        """
    )
    card = cursor.fetchone()
    if card[1] or card[8]:
        raise RuntimeError(f"指标卡ADS主键或比率失败：duplicates={card[1]}, ratios={card[8]}")

    cursor.execute(
        """
        SELECT platform_code, SUM(gmv_amount), SUM(refund_amount),
               SUM(transaction_order_count), SUM(sold_unit_count)
        FROM ads.ads_operating_sales_company_shop_daily
        GROUP BY platform_code
        """
    )
    card_by_platform = {row[0]: row[1:] for row in cursor.fetchall()}
    zero_card = (Decimal("0"), Decimal("0"), 0, Decimal("0"))
    for platform_code, item in platform_result.items():
        expected = (item["gmv"], item["refund"], item["orders"], item["sold_units"])
        actual = card_by_platform.get(platform_code, zero_card)
        if actual != expected:
            raise RuntimeError(
                f"{item['name']}DWS与指标卡ADS不一致："
                f"{actual}/{expected}"
            )

    cursor.execute(
        """
        SELECT platform_code, SUM(gmv_amount), SUM(included_sub_order_count)
        FROM ads.ads_operating_sales_traffic_company_shop_daily
        GROUP BY platform_code
        """
    )
    traffic_by_platform = {row[0]: row[1:] for row in cursor.fetchall()}
    cursor.execute(
        """
        SELECT platform_code, SUM(gmv_amount), SUM(paid_component_count),
               SUM(unmapped_component_count)
        FROM ads.ads_operating_sales_product_company_shop_daily
        GROUP BY platform_code
        """
    )
    product_by_platform = {row[0]: row[1:] for row in cursor.fetchall()}
    zero_traffic = (Decimal("0"), 0)
    zero_product = (Decimal("0"), 0, 0)
    for platform_code, item in platform_result.items():
        traffic = traffic_by_platform.get(platform_code, zero_traffic)
        product = product_by_platform.get(platform_code, zero_product)
        if traffic[0] != item["gmv"]:
            raise RuntimeError(f"{item['name']}流量ADS与DWS GMV不一致")
        if product != (
            item["gmv"], item["product_components"], item["unmapped_components"]
        ):
            raise RuntimeError(f"{item['name']}产品ADS与产品DWS不一致")

    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM ads.ads_operating_sales_company_shop_daily WHERE company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_operating_sales_traffic_company_shop_daily WHERE company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_operating_sales_product_company_shop_daily WHERE company_code = 'unmapped'),
            (SELECT COUNT(*) FROM ads.ads_operating_sales_traffic_company_shop_daily),
            (SELECT COUNT(*) FROM ads.ads_operating_sales_product_company_shop_daily)
        """
    )
    unmapped_card, unmapped_traffic, unmapped_product, traffic_rows, product_rows = cursor.fetchone()
    if unmapped_card or unmapped_traffic or unmapped_product:
        raise RuntimeError(
            "ADS存在未匹配公司："
            f"{unmapped_card}/{unmapped_traffic}/{unmapped_product}"
        )

    if enforce_baseline and (
        card[4] != Decimal("2026185.98")
        or card[5] != Decimal("596391.74")
        or card[6] != 13030
        or card[7] != Decimal("12809.00")
    ):
        raise RuntimeError(
            "七平台当前总基准不一致："
            f"GMV={card[4]},退款={card[5]},订单={card[6]},件数={card[7]}"
        )

    cursor.execute(
        """
        SELECT platform_code, sub_order_no, order_status, after_sale_status,
               order_pay_amount, product_unit_price, refund_amount, sold_unit_count
        FROM (
            SELECT * FROM dws.dws_douyin_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_wechat_channels_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_jd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_ks_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_xhs_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_pdd_operating_sales_order_item
            UNION ALL SELECT * FROM dws.dws_tmall_operating_sales_order_item
        ) sample
        ORDER BY platform_code, is_closed_refund DESC, source_id
        """
    )
    samples_by_platform: dict[str, tuple] = {}
    for row in cursor.fetchall():
        samples_by_platform.setdefault(row[0], row)

    cursor.execute(
        """
        (
            SELECT '正常商品', sub_order_no, main_order_no, order_status,
                   product_unit_price, gmv_amount, refund_amount, sold_unit_count
            FROM dws.dws_tmall_operating_sales_order_item
            WHERE order_status <> '交易关闭' AND gmv_amount > 0
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '交易关闭退款', sub_order_no, main_order_no, order_status,
                   product_unit_price, gmv_amount, refund_amount, sold_unit_count
            FROM dws.dws_tmall_operating_sales_order_item
            WHERE order_status = '交易关闭' AND gmv_amount > 0
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '推荐官辅助行', sub_order_no, main_order_no, order_status,
                   product_unit_price, gmv_amount, refund_amount, sold_unit_count
            FROM dws.dws_tmall_operating_sales_order_item
            WHERE product_name = 'MOCK推荐官'
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '赠品勿拍辅助行', sub_order_no, main_order_no, order_status,
                   product_unit_price, gmv_amount, refund_amount, sold_unit_count
            FROM dws.dws_tmall_operating_sales_order_item
            WHERE product_name LIKE '%赠品勿拍%'
            ORDER BY source_id LIMIT 1
        )
        UNION ALL
        (
            SELECT '未付款零GMV', sub_order_no, main_order_no, order_status,
                   product_unit_price, gmv_amount, refund_amount, sold_unit_count
            FROM dws.dws_tmall_operating_sales_order_item
            WHERE product_unit_price = 0
              AND product_name <> 'MOCK推荐官'
              AND product_name NOT LIKE '%赠品勿拍%'
            ORDER BY source_id LIMIT 1
        )
        """
    )
    tmall_samples = cursor.fetchall()
    if platform_result.get("tmall", {}).get("dws_rows", 0) and len(tmall_samples) < 5:
        print(
            f"[WARN] 天猫运营成交公式抽样场景不足5个，当前仅{len(tmall_samples)}个；"
            "不影响按实际来源刷新。",
            file=sys.stderr,
        )

    return {
        "card_rows": card[0],
        "traffic_rows": traffic_rows,
        "product_rows": product_rows,
        "min_date": card[2],
        "max_date": card[3],
        "gmv": card[4],
        "refund": card[5],
        "orders": card[6],
        "sold_units": card[7],
        "refund_rate": (card[5] / card[4]).quantize(Decimal("0.000001")) if card[4] else Decimal("0"),
        "unit_price": (card[4] / card[7]).quantize(Decimal("0.01")) if card[7] else Decimal("0"),
        "unmapped_company": (unmapped_card, unmapped_traffic, unmapped_product),
        "bidirectional_differences": (
            card_bidirectional_differences,
            traffic_bidirectional_differences,
            product_bidirectional_differences,
        ),
        "samples": list(samples_by_platform.values()),
        "tmall_samples": tmall_samples,
    }


def json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def run_pipeline(args: argparse.Namespace) -> None:
    product_mappings = None
    # 产品编码的运行时事实来源是 DIM。Excel 只作为显式维护/回填工具，不能
    # 作为运营成交ETL的默认依赖，否则正式 Docker 镜像没有 data/ 文件时会
    # 在刷新前直接失败。
    if args.product_mapping_file and not args.skip_product_mapping_load:
        from etl.common.load_company_product_code_mapping import (  # noqa: PLC0415
            parse_product_code_workbook,
        )

        product_mappings = parse_product_code_workbook(args.product_mapping_file)

    connection = psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    try:
        with connection.cursor() as cursor:
            lock_product_refresh(cursor, global_lock_held=os.getenv("MOCK_COFFICE_ETL_LOCK_HELD") == "1")
            execute_files(cursor, PREPARE_SQL_FILES)
            product_mapping_result = None
            if product_mappings is not None:
                from etl.common.load_company_product_code_mapping import (  # noqa: PLC0415
                    upsert_product_code_mappings,
                )

                product_mapping_result = upsert_product_code_mappings(
                    cursor, product_mappings
                )
            source_summary = validate_sources(cursor)
            # 300号天猫产品DWS脚本会重建表；先移除可重建的观察视图，
            # 398号SQL会在所有七平台DWS结构就绪后于同一事务恢复。
            cursor.execute(
                "DROP VIEW IF EXISTS common.v_operating_sales_product_code_observation"
            )
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            platform_result = validate_platform_layers(
                cursor,
                source_summary,
                args.enforce_current_baseline,
            )
            ads_result = validate_ads(
                cursor,
                platform_result,
                args.enforce_current_baseline,
            )
            validate_comments(cursor)
            workbench_result = publish_workbench(cursor)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    output = {
        "database": args.dbname,
        "product_mapping": product_mapping_result,
        "platforms": platform_result,
        "ads": ads_result,
        "product_mapping_workbench": workbench_result,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=json_default))


def main() -> None:
    run_pipeline(build_parser().parse_args())


if __name__ == "__main__":
    main()
