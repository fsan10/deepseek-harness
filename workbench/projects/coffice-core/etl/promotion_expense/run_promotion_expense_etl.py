#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""导入四个平台推广费来源，刷新日推广费ADS及GSV/实际推广费月度ADS。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

SETUP_SQL_FILES = [
    "common/00_ods_file_ingest_log_postgres.sql",
    "dim/32_dim_platform_shop_company_postgres.sql",
    "douyin/ods/33_ods_douyin_qianchuan_finance_raw_postgres.sql",
    "pdd/ods/205_ods_pdd_promotion_expense_raw_postgres.sql",
    "jd/ods/206_ods_jd_tong_promotion_expense_raw_postgres.sql",
    "jd/ods/207_ods_jd_union_promotion_expense_raw_postgres.sql",
    "tmall/ods/208_ods_tmall_taobao_union_promotion_expense_raw_postgres.sql",
    "tmall/ods/209_ods_tmall_wanxiangtai_promotion_expense_raw_postgres.sql",
    "common/52_ingest_batch_shop_context_postgres.sql",
]

METRIC_TABLE_SQL_FILES = [
    "douyin/promotion_expense/210_dwd_douyin_promotion_expense_detail_postgres.sql",
    "douyin/promotion_expense/211_dws_douyin_promotion_expense_shop_daily_postgres.sql",
    "pdd/promotion_expense/212_dwd_pdd_promotion_expense_detail_postgres.sql",
    "pdd/promotion_expense/213_dws_pdd_promotion_expense_shop_daily_postgres.sql",
    "jd/promotion_expense/214_dwd_jd_promotion_expense_detail_postgres.sql",
    "jd/promotion_expense/215_dws_jd_promotion_expense_shop_daily_postgres.sql",
    "tmall/promotion_expense/216_dwd_tmall_promotion_expense_detail_postgres.sql",
    "tmall/promotion_expense/217_dws_tmall_promotion_expense_shop_daily_postgres.sql",
    "ads/promotion_expense/218_ads_promotion_expense_company_shop_daily_postgres.sql",
    "ads/gsv_promotion_expense/413_ads_gsv_promotion_expense_company_shop_monthly_postgres.sql",
]

DWD_DWS_REFRESH_SQL_FILES = [
    "douyin/promotion_expense/219_refresh_dwd_douyin_promotion_expense_detail_postgres.sql",
    "douyin/promotion_expense/220_refresh_dws_douyin_promotion_expense_shop_daily_postgres.sql",
    "pdd/promotion_expense/221_refresh_dwd_pdd_promotion_expense_detail_postgres.sql",
    "pdd/promotion_expense/222_refresh_dws_pdd_promotion_expense_shop_daily_postgres.sql",
    "jd/promotion_expense/223_refresh_dwd_jd_promotion_expense_detail_postgres.sql",
    "jd/promotion_expense/224_refresh_dws_jd_promotion_expense_shop_daily_postgres.sql",
    "tmall/promotion_expense/225_refresh_dwd_tmall_promotion_expense_detail_postgres.sql",
    "tmall/promotion_expense/226_refresh_dws_tmall_promotion_expense_shop_daily_postgres.sql",
]

ADS_REFRESH_SQL_FILES = [
    "ads/promotion_expense/227_refresh_ads_promotion_expense_company_shop_daily_postgres.sql",
]

MONTHLY_REFRESH_SQL_FILES = [
    "ads/gsv_promotion_expense/414_refresh_ads_gsv_promotion_expense_company_shop_monthly_postgres.sql",
]


@dataclass(frozen=True)
class SourceSpec:
    label: str
    table_name: str
    loader_path: str
    file_argument: str
    shop_argument: str
    required_columns: tuple[str, ...]


SOURCES = (
    SourceSpec(
        "抖音千川",
        "ods.ods_douyin_qianchuan_finance_raw",
        "etl/douyin/load_douyin_qianchuan_finance_ods.py",
        "douyin_file",
        "douyin_shop_code",
        ("日期", "非赠款消耗(元)", "赠款消耗(元)"),
    ),
    SourceSpec(
        "拼多多推广费",
        "ods.ods_pdd_promotion_expense_raw",
        "etl/pdd/load_pdd_promotion_expense_ods.py",
        "pdd_file",
        "pdd_shop_code",
        ("时间", "资金类型", "流水类型", "店铺名称", "交易金额"),
    ),
    SourceSpec(
        "京东通",
        "ods.ods_jd_tong_promotion_expense_raw",
        "etl/jd/load_jd_tong_promotion_expense_ods.py",
        "jd_tong_file",
        "jd_shop_code",
        ("流水单号", "投放账户ID", "交易类型", "支出", "结算时间"),
    ),
    SourceSpec(
        "京东联盟",
        "ods.ods_jd_union_promotion_expense_raw",
        "etl/jd/load_jd_union_promotion_expense_ods.py",
        "jd_union_file",
        "jd_shop_code",
        ("流水单号", "结算金额", "状态", "结算时间", "结算类型"),
    ),
    SourceSpec(
        "天猫淘宝联盟",
        "ods.ods_tmall_taobao_union_promotion_expense_raw",
        "etl/tmall/load_tmall_taobao_union_promotion_expense_ods.py",
        "tmall_taobao_union_file",
        "tmall_shop_code",
        ("日期", "结算支出费用(元)"),
    ),
    SourceSpec(
        "天猫万相台",
        "ods.ods_tmall_wanxiangtai_promotion_expense_raw",
        "etl/tmall/load_tmall_wanxiangtai_promotion_expense_ods.py",
        "tmall_wanxiangtai_file",
        "tmall_shop_code",
        ("记账时间", "收支类型", "交易类型", "操作金额(元)"),
    ),
)

COMMENTED_TABLES = (
    "ods.ods_douyin_qianchuan_finance_raw",
    "ods.ods_pdd_promotion_expense_raw",
    "ods.ods_jd_tong_promotion_expense_raw",
    "ods.ods_jd_union_promotion_expense_raw",
    "ods.ods_tmall_taobao_union_promotion_expense_raw",
    "ods.ods_tmall_wanxiangtai_promotion_expense_raw",
    "dwd.dwd_douyin_promotion_expense_detail",
    "dwd.dwd_pdd_promotion_expense_detail",
    "dwd.dwd_jd_promotion_expense_detail",
    "dwd.dwd_tmall_promotion_expense_detail",
    "dws.dws_douyin_promotion_expense_shop_daily",
    "dws.dws_pdd_promotion_expense_shop_daily",
    "dws.dws_jd_promotion_expense_shop_daily",
    "dws.dws_tmall_promotion_expense_shop_daily",
    "ads.ads_promotion_expense_company_shop_daily",
    "ads.ads_gsv_promotion_expense_company_shop_monthly",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="导入并刷新四个平台真实推广费，以及快手、视频号、小红书零值占位。"
    )
    parser.add_argument(
        "--douyin-file",
        default=str(PROJECT_ROOT / "data" / "千川" / "MOCK冲饮旗舰店-千川推广.xlsx"),
    )
    parser.add_argument(
        "--pdd-file",
        default=str(PROJECT_ROOT / "data" / "拼多多" / "推广费" / "MOCK饮品旗舰店-推广费-拼多多.xls"),
    )
    parser.add_argument(
        "--jd-tong-file",
        default=str(PROJECT_ROOT / "data" / "京东" / "推广费" / "京东-MOCK咖啡旗舰店-推广费-京东通.xls"),
    )
    parser.add_argument(
        "--jd-union-file",
        default=str(PROJECT_ROOT / "data" / "京东" / "推广费" / "京东-MOCK咖啡旗舰店-推广费-京东联盟.xlsx"),
    )
    parser.add_argument(
        "--tmall-taobao-union-file",
        default=str(PROJECT_ROOT / "data" / "天猫" / "推广费" / "天猫-MOCK旗舰店-淘宝联盟-推广费.csv"),
    )
    parser.add_argument(
        "--tmall-wanxiangtai-file",
        default=str(PROJECT_ROOT / "data" / "天猫" / "推广费" / "天猫-MOCK旗舰店-万相台-推广费.csv"),
    )
    parser.add_argument("--douyin-shop-code", help="抖音千川文件归属的标准店铺编码。")
    parser.add_argument("--pdd-shop-code", help="拼多多推广费文件归属的标准店铺编码。")
    parser.add_argument("--jd-shop-code", help="京东通与京东联盟文件归属的标准店铺编码。")
    parser.add_argument("--tmall-shop-code", help="淘宝联盟与万相台文件归属的标准店铺编码。")
    parser.add_argument("--skip-ods-load", action="store_true", help="跳过六个源文件导入，只刷新指标层。")
    parser.add_argument(
        "--shop-mapping-source",
        choices=("manual_selected", "robot_selected"),
        default="manual_selected",
    )
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def connect(args: argparse.Namespace):
    return psycopg2.connect(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def prepare_sources(args: argparse.Namespace) -> None:
    connection = connect(args)
    try:
        with connection.cursor() as cursor:
            execute_files(cursor, SETUP_SQL_FILES)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    if args.skip_ods_load:
        return

    missing_shop_arguments = sorted(
        {
            spec.shop_argument
            for spec in SOURCES
            if not getattr(args, spec.shop_argument)
        }
    )
    if missing_shop_arguments:
        flags = ", ".join("--" + item.replace("_", "-") for item in missing_shop_arguments)
        raise ValueError(f"导入推广费文件必须显式传入标准店铺编码：{flags}")

    env = os.environ.copy()
    env.update(
        {
            "PGHOST": args.host,
            "PGPORT": str(args.port),
            "PGDATABASE": args.dbname,
            "PGUSER": args.user,
        }
    )
    if args.password:
        env["PGPASSWORD"] = args.password

    for spec in SOURCES:
        file_path = Path(getattr(args, spec.file_argument))
        if not file_path.exists():
            raise FileNotFoundError(f"{spec.label}源文件不存在：{file_path}")
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / spec.loader_path),
                "--file",
                str(file_path),
                "--shop-code",
                getattr(args, spec.shop_argument),
                "--shop-mapping-source",
                args.shop_mapping_source,
            ],
            check=True,
            cwd=PROJECT_ROOT,
            env=env,
        )


def split_table_name(table_name: str) -> tuple[str, str]:
    schema_name, relation_name = table_name.split(".", 1)
    return schema_name, relation_name


def validate_source_tables(cursor) -> dict[str, int]:
    source_counts: dict[str, int] = {}
    for spec in SOURCES:
        schema_name, relation_name = split_table_name(spec.table_name)
        cursor.execute("SELECT to_regclass(%s)", (spec.table_name,))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少推广费来源表：{spec.table_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            """,
            (schema_name, relation_name),
        )
        actual_columns = {row[0] for row in cursor.fetchall()}
        missing_columns = sorted(set(spec.required_columns) - actual_columns)
        if missing_columns:
            raise RuntimeError(f"{spec.table_name}缺少必需字段：{missing_columns}")
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema_name),
                sql.Identifier(relation_name),
            )
        )
        source_counts[spec.table_name] = cursor.fetchone()[0]
        if source_counts[spec.table_name] == 0:
            print(f"[WARN] {spec.table_name}为空，按0值刷新对应平台")

    cursor.execute(
        """
        WITH source_batches AS (
            SELECT batch_id, 'douyin'::text AS platform_code, 'ods_douyin_qianchuan_finance_raw'::text AS target_table
            FROM ods.ods_douyin_qianchuan_finance_raw
            UNION
            SELECT batch_id, 'pdd', 'ods_pdd_promotion_expense_raw'
            FROM ods.ods_pdd_promotion_expense_raw
            UNION
            SELECT batch_id, 'jd', 'ods_jd_tong_promotion_expense_raw'
            FROM ods.ods_jd_tong_promotion_expense_raw
            UNION
            SELECT batch_id, 'jd', 'ods_jd_union_promotion_expense_raw'
            FROM ods.ods_jd_union_promotion_expense_raw
            UNION
            SELECT batch_id, 'tmall', 'ods_tmall_taobao_union_promotion_expense_raw'
            FROM ods.ods_tmall_taobao_union_promotion_expense_raw
            UNION
            SELECT batch_id, 'tmall', 'ods_tmall_wanxiangtai_promotion_expense_raw'
            FROM ods.ods_tmall_wanxiangtai_promotion_expense_raw
        )
        SELECT COUNT(*)
        FROM source_batches src
        LEFT JOIN common.v_ingest_batch_shop_context ctx
            ON ctx.batch_id = src.batch_id
           AND ctx.platform_code = src.platform_code
           AND ctx.target_table = src.target_table
        WHERE ctx.batch_id IS NULL
           OR ctx.shop_mapping_status <> 'mapped'
           OR ctx.ingest_status <> 'success'
           OR ctx.shop_code IS NULL
           OR ctx.shop_identity_key IS NULL
        """
    )
    invalid_batch_count = cursor.fetchone()[0]
    if invalid_batch_count:
        raise RuntimeError(f"推广费来源存在{invalid_batch_count}个未映射、冲突或未成功批次")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ods.ods_pdd_promotion_expense_raw raw
        JOIN common.v_ingest_batch_shop_context ctx ON ctx.batch_id = raw.batch_id
        WHERE NULLIF(BTRIM(raw."店铺名称"), '') IS NOT NULL
          AND BTRIM(raw."店铺名称") <> ctx.shop_name
        """
    )
    pdd_shop_conflicts = cursor.fetchone()[0]
    if pdd_shop_conflicts:
        raise RuntimeError(f"拼多多来源店铺名称与批次标准店铺冲突：{pdd_shop_conflicts}行")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ods.ods_jd_tong_promotion_expense_raw raw
        JOIN common.v_ingest_batch_shop_context ctx ON ctx.batch_id = raw.batch_id
        WHERE NULLIF(BTRIM(raw."投放账户ID"), '') IS NOT NULL
          AND BTRIM(raw."投放账户ID") <> ctx.shop_code
        """
    )
    jd_tong_conflicts = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ods.ods_jd_union_promotion_expense_raw raw
        JOIN common.v_ingest_batch_shop_context ctx ON ctx.batch_id = raw.batch_id
        WHERE SUBSTRING(BTRIM(raw."流水单号") FROM '_([0-9]+)_') IS NOT NULL
          AND SUBSTRING(BTRIM(raw."流水单号") FROM '_([0-9]+)_') <> ctx.shop_code
        """
    )
    jd_union_conflicts = cursor.fetchone()[0]
    if jd_tong_conflicts or jd_union_conflicts:
        raise RuntimeError(
            f"京东来源账号与批次标准店铺冲突：京东通{jd_tong_conflicts}行，京东联盟{jd_union_conflicts}行"
        )
    return source_counts


def count_refresh_rows(cursor, table: str, platform: str) -> int:
    """Compare only the frozen shop/months this transaction actually replaces."""
    schema, name = table.split('.')
    scope = getattr(cursor.connection, 'refresh_scope', None)
    if scope is None or scope.full:
        cursor.execute(sql.SQL('SELECT COUNT(*) FROM {}').format(sql.Identifier(schema, name)))
    else:
        from etl.common.refresh_runtime import SOURCE_DATES
        columns = cursor.connection.columns(schema, name)
        date_expression = SOURCE_DATES.get(name) if schema == 'ods' else None
        predicate = scope.predicate(cursor.connection, name, columns, date_expression=date_expression)
        shops = scope.context.get('shops', {}).get(platform, [])
        if schema == 'ods' and shops:
            # Raw facts only carry batch_id. Shop attribution always comes
            # from the same frozen, validated batch context as the DWD SQL.
            predicate += sql.SQL(''' AND batch_id IN (
                SELECT batch_id FROM common.v_ingest_batch_shop_context
                WHERE platform_code={} AND target_table={} AND shop_code=ANY({}::text[]))''').format(
                    sql.Literal(platform), sql.Literal(name), sql.Literal(shops)).as_string(cursor.connection)
        cursor.execute(sql.SQL('SELECT COUNT(*) FROM {} WHERE {}').format(
            sql.Identifier(schema, name), sql.SQL(predicate)))
    return cursor.fetchone()[0]


def validate_dwd_and_dws(cursor) -> None:
    count_checks = (
        (
            "抖音",
            "douyin", ("ods.ods_douyin_qianchuan_finance_raw",),
            "dwd.dwd_douyin_promotion_expense_detail",
        ),
        (
            "拼多多",
            "pdd", ("ods.ods_pdd_promotion_expense_raw",),
            "dwd.dwd_pdd_promotion_expense_detail",
        ),
        (
            "京东",
            "jd", ("ods.ods_jd_tong_promotion_expense_raw", "ods.ods_jd_union_promotion_expense_raw"),
            "dwd.dwd_jd_promotion_expense_detail",
        ),
        (
            "天猫",
            "tmall", ("ods.ods_tmall_taobao_union_promotion_expense_raw", "ods.ods_tmall_wanxiangtai_promotion_expense_raw"),
            "dwd.dwd_tmall_promotion_expense_detail",
        ),
    )
    for label, platform, sources, dwd_table in count_checks:
        source_count = sum(count_refresh_rows(cursor, table, platform) for table in sources)
        dwd_count = count_refresh_rows(cursor, dwd_table, platform)
        if source_count != dwd_count:
            raise RuntimeError(f"{label} ODS/DWD行数不一致：ODS={source_count}, DWD={dwd_count}")

    parse_checks = (
        (
            "抖音",
            """
            SELECT COUNT(*) FROM dwd.dwd_douyin_promotion_expense_detail
            WHERE expense_date IS NULL OR non_gift_spend_amount IS NULL
            """,
        ),
        (
            "拼多多",
            """
            SELECT COUNT(*) FROM dwd.dwd_pdd_promotion_expense_detail
            WHERE expense_date IS NULL OR transaction_amount IS NULL
            """,
        ),
        (
            "京东",
            """
            SELECT COUNT(*) FROM dwd.dwd_jd_promotion_expense_detail
            WHERE expense_date IS NULL OR source_amount IS NULL
            """,
        ),
        (
            "天猫",
            """
            SELECT COUNT(*) FROM dwd.dwd_tmall_promotion_expense_detail
            WHERE expense_date IS NULL OR source_amount IS NULL
            """,
        ),
    )
    for label, query in parse_checks:
        cursor.execute(query)
        invalid_count = cursor.fetchone()[0]
        if invalid_count:
            raise RuntimeError(f"{label} DWD存在{invalid_count}行日期或金额解析失败")

    formula_checks = (
        (
            "抖音",
            """
            SELECT COUNT(*) FROM dws.dws_douyin_promotion_expense_shop_daily
            WHERE promotion_expense_amount <> qianchuan_non_gift_spend_amount
            """,
        ),
        (
            "拼多多",
            """
            SELECT COUNT(*) FROM dws.dws_pdd_promotion_expense_shop_daily
            WHERE promotion_expense_amount <> cash_outflow_amount
            """,
        ),
        (
            "京东",
            """
            SELECT COUNT(*) FROM dws.dws_jd_promotion_expense_shop_daily
            WHERE promotion_expense_amount <> jd_tong_spend_amount + jd_union_spend_amount
            """,
        ),
        (
            "天猫",
            """
            SELECT COUNT(*) FROM dws.dws_tmall_promotion_expense_shop_daily
            WHERE promotion_expense_amount <> taobao_union_spend_amount + wanxiangtai_spend_amount
            """,
        ),
    )
    for label, query in formula_checks:
        cursor.execute(query)
        mismatch_count = cursor.fetchone()[0]
        if mismatch_count:
            raise RuntimeError(f"{label} DWS存在{mismatch_count}行组成金额公式不一致")


def validate_dim_date_matches(cursor) -> None:
    cursor.execute(
        """
        WITH real_platform_daily AS (
            SELECT stat_date, platform_code, shop_code FROM dws.dws_douyin_promotion_expense_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code FROM dws.dws_pdd_promotion_expense_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code FROM dws.dws_jd_promotion_expense_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, shop_code FROM dws.dws_tmall_promotion_expense_shop_daily
        ),
        date_spine AS (
            SELECT DISTINCT stat_date FROM real_platform_daily
        ),
        zero_platform_shops AS (
            SELECT DISTINCT platform_code, shop_code
            FROM dim.dim_platform_shop_company
            WHERE platform_code IN ('ks', 'wechat_channels', 'xhs')
              AND is_active
        ),
        platform_daily AS (
            SELECT stat_date, platform_code, shop_code FROM real_platform_daily
            UNION
            SELECT d.stat_date, s.platform_code, s.shop_code
            FROM date_spine d
            CROSS JOIN zero_platform_shops s
        ),
        match_counts AS (
            SELECT d.stat_date, d.platform_code, d.shop_code, COUNT(m.shop_company_sk) AS matched_count
            FROM platform_daily d
            LEFT JOIN dim.dim_platform_shop_company m
                ON m.platform_code = d.platform_code
               AND m.shop_code = d.shop_code
               AND m.is_active
               AND d.stat_date >= m.valid_from
               AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
            GROUP BY d.stat_date, d.platform_code, d.shop_code
        )
        SELECT COUNT(*) FROM match_counts WHERE matched_count > 1
        """
    )
    overlapping_count = cursor.fetchone()[0]
    if overlapping_count:
        raise RuntimeError(f"DIM有效期存在{overlapping_count}个店铺日多重匹配，停止刷新ADS")

    cursor.execute(
        """
        WITH required_platforms(platform_code) AS (
            VALUES ('ks'), ('wechat_channels'), ('xhs')
        ),
        date_spine AS (
            SELECT stat_date FROM dws.dws_douyin_promotion_expense_shop_daily
            UNION
            SELECT stat_date FROM dws.dws_pdd_promotion_expense_shop_daily
            UNION
            SELECT stat_date FROM dws.dws_jd_promotion_expense_shop_daily
            UNION
            SELECT stat_date FROM dws.dws_tmall_promotion_expense_shop_daily
        )
        SELECT STRING_AGG(p.platform_code, ', ' ORDER BY p.platform_code)
        FROM required_platforms p
        WHERE NOT EXISTS (
            SELECT 1
            FROM date_spine d
            JOIN dim.dim_platform_shop_company m
              ON m.platform_code = p.platform_code
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
        )
        """
    )
    missing_platforms = cursor.fetchone()[0]
    if missing_platforms:
        raise RuntimeError(f"补零平台在推广费日期范围内缺少有效DIM店铺：{missing_platforms}")


def validate_ads(cursor) -> None:
    cursor.execute(
        """
        WITH real_platform_daily AS (
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM dws.dws_douyin_promotion_expense_shop_daily
            UNION ALL
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM dws.dws_pdd_promotion_expense_shop_daily
            UNION ALL
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM dws.dws_jd_promotion_expense_shop_daily
            UNION ALL
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM dws.dws_tmall_promotion_expense_shop_daily
        ),
        date_spine AS (
            SELECT DISTINCT stat_date FROM real_platform_daily
        ),
        zero_platform_daily AS (
            SELECT
                d.stat_date,
                m.platform_code,
                m.platform_name,
                m.shop_code,
                m.shop_name,
                0::NUMERIC(18,2) AS promotion_expense_amount,
                0::BIGINT AS included_detail_count
            FROM date_spine d
            JOIN dim.dim_platform_shop_company m
              ON m.platform_code IN ('ks', 'wechat_channels', 'xhs')
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
        ),
        platform_daily AS (
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM real_platform_daily
            UNION ALL
            SELECT
                stat_date, platform_code, platform_name, shop_code, shop_name,
                promotion_expense_amount, included_detail_count
            FROM zero_platform_daily
        ),
        expected_grouped AS (
            SELECT
                d.stat_date,
                d.platform_code,
                COALESCE(m.company_code, 'unmapped') AS company_code,
                d.shop_code,
                ROUND(SUM(d.promotion_expense_amount), 2) AS amount,
                SUM(d.included_detail_count) AS included_count
            FROM platform_daily d
            LEFT JOIN dim.dim_platform_shop_company m
              ON m.platform_code = d.platform_code
             AND m.shop_code = d.shop_code
             AND m.is_active
             AND d.stat_date >= m.valid_from
             AND (m.valid_to IS NULL OR d.stat_date <= m.valid_to)
            GROUP BY
                d.stat_date,
                d.platform_code,
                COALESCE(m.company_code, 'unmapped'),
                d.shop_code
        ),
        ads_grouped AS (
            SELECT
                stat_date,
                platform_code,
                company_code,
                shop_code,
                ROUND(SUM(promotion_expense_amount), 2) AS amount,
                SUM(included_detail_count) AS included_count
            FROM ads.ads_promotion_expense_company_shop_daily
            GROUP BY stat_date, platform_code, company_code, shop_code
        ),
        differences AS (
            (SELECT * FROM expected_grouped EXCEPT ALL SELECT * FROM ads_grouped)
            UNION ALL
            (SELECT * FROM ads_grouped EXCEPT ALL SELECT * FROM expected_grouped)
        )
        SELECT COUNT(*) FROM differences
        """
    )
    difference_count = cursor.fetchone()[0]
    if difference_count:
        raise RuntimeError(f"DWS真实值及三平台零值占位与ADS双向核对存在{difference_count}条差异")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ads.ads_promotion_expense_company_shop_daily
        WHERE platform_code IN ('ks', 'wechat_channels', 'xhs')
          AND (
              promotion_expense_amount <> 0
              OR included_detail_count <> 0
              OR source_updated_at IS NOT NULL
          )
        """
    )
    invalid_zero_count = cursor.fetchone()[0]
    if invalid_zero_count:
        raise RuntimeError(f"推广费ADS存在{invalid_zero_count}条不符合口径的补零记录")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT stat_date, platform_code, company_code, shop_code, COUNT(*)
            FROM ads.ads_promotion_expense_company_shop_daily
            GROUP BY stat_date, platform_code, company_code, shop_code
            HAVING COUNT(*) > 1
        ) duplicated
        """
    )
    duplicate_count = cursor.fetchone()[0]
    if duplicate_count:
        raise RuntimeError(f"推广费ADS存在{duplicate_count}组重复主键")


def validate_monthly_sources(cursor) -> None:
    source_specs = {
        "ads.ads_gsv_company_daily": {
            "stat_date",
            "platform_code",
            "platform_name",
            "company_code",
            "company_name",
            "shop_code",
            "shop_name",
            "gsv_amount",
            "source_updated_at",
        },
        "ads.ads_promotion_expense_company_shop_daily": {
            "stat_date",
            "platform_code",
            "platform_name",
            "company_code",
            "company_name",
            "shop_code",
            "shop_name",
            "promotion_expense_amount",
            "source_updated_at",
        },
    }
    for table_name, required_columns in source_specs.items():
        schema_name, relation_name = split_table_name(table_name)
        cursor.execute("SELECT to_regclass(%s)", (table_name,))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"月度GSV推广费汇总缺少来源表：{table_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            """,
            (schema_name, relation_name),
        )
        missing_columns = sorted(required_columns - {row[0] for row in cursor.fetchall()})
        if missing_columns:
            raise RuntimeError(f"{table_name}缺少月度汇总必需字段：{missing_columns}")

    cursor.execute("SELECT COUNT(*) FROM ads.ads_gsv_company_daily")
    gsv_rows = cursor.fetchone()[0]
    if not gsv_rows:
        raise RuntimeError("ads.ads_gsv_company_daily没有有效数据，停止刷新月度GSV推广费汇总")

    duplicate_queries = (
        (
            "GSV",
            """
            SELECT COUNT(*)
            FROM (
                SELECT stat_date, platform_code, company_code, shop_code
                FROM ads.ads_gsv_company_daily
                GROUP BY stat_date, platform_code, company_code, shop_code
                HAVING COUNT(*) > 1
            ) duplicated
            """,
        ),
        (
            "推广费",
            """
            SELECT COUNT(*)
            FROM (
                SELECT stat_date, platform_code, company_code, shop_code
                FROM ads.ads_promotion_expense_company_shop_daily
                GROUP BY stat_date, platform_code, company_code, shop_code
                HAVING COUNT(*) > 1
            ) duplicated
            """,
        ),
    )
    for label, query in duplicate_queries:
        cursor.execute(query)
        duplicate_count = cursor.fetchone()[0]
        if duplicate_count:
            raise RuntimeError(f"月度汇总来源{label}日ADS存在{duplicate_count}组重复键")


def validate_monthly_ads(cursor) -> None:
    scope = getattr(cursor.connection, 'refresh_scope', None)
    predicate = 'TRUE'
    if scope is not None and not scope.full:
        table = 'ads_gsv_promotion_expense_company_shop_monthly'
        predicate = scope.predicate(cursor.connection, table, cursor.connection.columns('ads', table))
    cursor.execute(
        f"""
        WITH gsv_monthly AS (
            SELECT
                DATE_TRUNC('month', stat_date)::date AS stat_month,
                platform_code,
                company_code,
                shop_code,
                ROUND(SUM(gsv_amount), 2) AS gsv_amount
            FROM ads.ads_gsv_company_daily
            GROUP BY 1, 2, 3, 4
        ), promotion_monthly AS (
            SELECT
                DATE_TRUNC('month', stat_date)::date AS stat_month,
                platform_code,
                company_code,
                shop_code,
                ROUND(SUM(promotion_expense_amount), 2) AS actual_promotion_expense_amount
            FROM ads.ads_promotion_expense_company_shop_daily
            GROUP BY 1, 2, 3, 4
        ), expected AS (
            SELECT
                g.stat_month,
                g.platform_code,
                g.company_code,
                g.shop_code,
                g.gsv_amount,
                COALESCE(p.actual_promotion_expense_amount, 0)::numeric AS actual_promotion_expense_amount,
                CASE
                    WHEN COALESCE(p.actual_promotion_expense_amount, 0) = 0 THEN NULL
                    ELSE ROUND(g.gsv_amount / p.actual_promotion_expense_amount, 6)
                END AS roi
            FROM gsv_monthly g
            LEFT JOIN promotion_monthly p
              ON p.stat_month = g.stat_month
             AND p.platform_code = g.platform_code
             AND p.company_code = g.company_code
             AND p.shop_code = g.shop_code
        ), actual AS (
            SELECT
                stat_month,
                platform_code,
                company_code,
                shop_code,
                gsv_amount,
                actual_promotion_expense_amount,
                roi
            FROM ads.ads_gsv_promotion_expense_company_shop_monthly
        ), differences AS (
            (SELECT * FROM expected WHERE {predicate} EXCEPT ALL SELECT * FROM actual WHERE {predicate})
            UNION ALL
            (SELECT * FROM actual WHERE {predicate} EXCEPT ALL SELECT * FROM expected WHERE {predicate})
        )
        SELECT COUNT(*) FROM differences
        """
    )
    difference_count = cursor.fetchone()[0]
    if difference_count:
        raise RuntimeError(f"月度GSV推广费ADS与日ADS按月重算存在{difference_count}条双向差异")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ads.ads_gsv_promotion_expense_company_shop_monthly
        WHERE roi IS DISTINCT FROM CASE
            WHEN actual_promotion_expense_amount = 0 THEN NULL
            ELSE ROUND(gsv_amount / actual_promotion_expense_amount, 6)
        END
        """
    )
    roi_mismatch_count = cursor.fetchone()[0]
    if roi_mismatch_count:
        raise RuntimeError(f"月度GSV推广费ADS存在{roi_mismatch_count}条ROI公式不一致")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT stat_month, platform_code, company_code, shop_code, COUNT(*)
            FROM ads.ads_gsv_promotion_expense_company_shop_monthly
            GROUP BY stat_month, platform_code, company_code, shop_code
            HAVING COUNT(*) > 1
        ) duplicated
        """
    )
    duplicate_count = cursor.fetchone()[0]
    if duplicate_count:
        raise RuntimeError(f"月度GSV推广费ADS存在{duplicate_count}组重复主键")


def validate_comments(cursor) -> None:
    for table_name in COMMENTED_TABLES:
        cursor.execute("SELECT obj_description(%s::regclass, 'pg_class')", (table_name,))
        if not cursor.fetchone()[0]:
            raise RuntimeError(f"表缺少注释：{table_name}")
        schema_name, relation_name = split_table_name(table_name)
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND col_description(
                    (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass::oid,
                    ordinal_position
                  ) IS NULL
            ORDER BY ordinal_position
            """,
            (schema_name, relation_name),
        )
        missing_columns = [row[0] for row in cursor.fetchall()]
        if missing_columns:
            raise RuntimeError(f"表{table_name}存在未注释字段：{missing_columns}")


def collect_results(cursor, source_counts: dict[str, int]) -> dict:
    result: dict = {
        "source_counts": source_counts,
        "platforms": {},
        "zero_platforms": {},
        "samples": {},
    }
    summary_queries = {
        "douyin": """
            SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
                   SUM(included_detail_count), SUM(excluded_detail_count),
                   SUM(qianchuan_non_gift_spend_amount), SUM(promotion_expense_amount)
            FROM dws.dws_douyin_promotion_expense_shop_daily
        """,
        "pdd": """
            SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
                   SUM(included_detail_count), SUM(excluded_detail_count),
                   SUM(cash_outflow_amount), SUM(promotion_expense_amount)
            FROM dws.dws_pdd_promotion_expense_shop_daily
        """,
        "jd": """
            SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
                   SUM(included_detail_count), SUM(excluded_detail_count),
                   SUM(jd_tong_spend_amount), SUM(jd_union_spend_amount),
                   SUM(promotion_expense_amount)
            FROM dws.dws_jd_promotion_expense_shop_daily
        """,
        "tmall": """
            SELECT COUNT(*), MIN(stat_date), MAX(stat_date),
                   SUM(included_detail_count), SUM(excluded_detail_count),
                   SUM(taobao_union_spend_amount), SUM(wanxiangtai_spend_amount),
                   SUM(promotion_expense_amount)
            FROM dws.dws_tmall_promotion_expense_shop_daily
        """,
    }
    for platform_code, query in summary_queries.items():
        cursor.execute(query)
        result["platforms"][platform_code] = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            platform_code,
            MAX(platform_name),
            COUNT(*),
            COUNT(DISTINCT shop_code),
            MIN(stat_date),
            MAX(stat_date),
            SUM(promotion_expense_amount)
        FROM ads.ads_promotion_expense_company_shop_daily
        WHERE platform_code IN ('ks', 'wechat_channels', 'xhs')
        GROUP BY platform_code
        ORDER BY platform_code
        """
    )
    result["zero_platforms"] = {row[0]: row[1:] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(stat_date),
            MAX(stat_date),
            COALESCE(SUM(promotion_expense_amount), 0),
            COUNT(*) FILTER (WHERE company_code = 'unmapped')
        FROM ads.ads_promotion_expense_company_shop_daily
        """
    )
    result["ads"] = cursor.fetchone()

    cursor.execute(
        """
        SELECT
            COUNT(*),
            MIN(stat_month),
            MAX(stat_month),
            COALESCE(SUM(gsv_amount), 0),
            COALESCE(SUM(actual_promotion_expense_amount), 0),
            COALESCE(ROUND(
                SUM(gsv_amount) / NULLIF(SUM(actual_promotion_expense_amount), 0),
                6
            ), 0),
            COUNT(*) FILTER (WHERE company_code = 'unmapped')
        FROM ads.ads_gsv_promotion_expense_company_shop_monthly
        """
    )
    result["monthly"] = cursor.fetchone()

    sample_queries = {
        "douyin": """
            SELECT source_record_id, expense_date, non_gift_spend_amount, gift_spend_amount, source_file_name, source_row_no
            FROM dwd.dwd_douyin_promotion_expense_detail
            ORDER BY source_record_id DESC
            LIMIT 5
        """,
        "pdd": """
            SELECT source_record_id, expense_date, fund_type, flow_type, transaction_amount, source_file_name, source_row_no
            FROM dwd.dwd_pdd_promotion_expense_detail
            ORDER BY source_record_id
            LIMIT 5
        """,
        "jd": """
            SELECT source_type, source_record_id, expense_date, transaction_type, source_amount, source_file_name, source_row_no
            FROM dwd.dwd_jd_promotion_expense_detail
            ORDER BY source_type, source_record_id
            LIMIT 5
        """,
        "tmall": """
            SELECT source_type, source_record_id, expense_date, receipts_type, transaction_type, source_amount, source_file_name, source_row_no
            FROM dwd.dwd_tmall_promotion_expense_detail
            ORDER BY source_type, source_record_id
            LIMIT 5
        """,
    }
    for platform_code, query in sample_queries.items():
        cursor.execute(query)
        result["samples"][platform_code] = cursor.fetchall()
    return result


def refresh_metric(args: argparse.Namespace) -> dict:
    connection = connect(args)
    try:
        with connection.cursor() as cursor:
            source_counts = validate_source_tables(cursor)
            execute_files(cursor, METRIC_TABLE_SQL_FILES)
            execute_files(cursor, DWD_DWS_REFRESH_SQL_FILES)
            validate_dwd_and_dws(cursor)
            validate_dim_date_matches(cursor)
            execute_files(cursor, ADS_REFRESH_SQL_FILES)
            validate_ads(cursor)
            validate_monthly_sources(cursor)
            execute_files(cursor, MONTHLY_REFRESH_SQL_FILES)
            validate_monthly_ads(cursor)
            validate_comments(cursor)
            result = collect_results(cursor, source_counts)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def amount(value) -> str:
    return f"{Decimal(value or 0):,.2f}"


def print_results(args: argparse.Namespace, result: dict) -> None:
    print(f"数据库：{args.dbname}")
    for spec in SOURCES:
        print(f"{spec.label} ODS行数：{result['source_counts'][spec.table_name]}")

    labels = {
        "douyin": "抖音",
        "pdd": "拼多多",
        "jd": "京东",
        "tmall": "天猫",
    }
    for platform_code in ("douyin", "pdd", "jd", "tmall"):
        row = result["platforms"][platform_code]
        print(
            f"{labels[platform_code]} DWS：{row[0]}行，日期{row[1]}至{row[2]}，"
            f"纳入{row[3] or 0}行，排除{row[4] or 0}行"
        )
        if platform_code == "jd":
            print(
                f"  京东通={amount(row[5])}，京东联盟={amount(row[6])}，"
                f"推广费={amount(row[7])}"
            )
        elif platform_code == "tmall":
            print(
                f"  淘宝联盟={amount(row[5])}，万相台={amount(row[6])}，"
                f"推广费={amount(row[7])}"
            )
        else:
            print(f"  组成金额={amount(row[5])}，推广费={amount(row[6])}")

    zero_labels = {
        "ks": "快手",
        "wechat_channels": "视频号（微信小店）",
        "xhs": "小红书",
    }
    for platform_code in ("ks", "wechat_channels", "xhs"):
        row = result["zero_platforms"][platform_code]
        print(
            f"{zero_labels[platform_code]} ADS补零：{row[1]}行，{row[2]}家店，"
            f"日期{row[3]}至{row[4]}，推广费={amount(row[5])}"
        )

    ads = result["ads"]
    print(f"推广费ADS：{ads[0]}行，日期{ads[1]}至{ads[2]}")
    print(f"推广费ADS总额：{amount(ads[3])}")
    print(f"ADS未匹配公司行数：{ads[4]}")
    monthly = result["monthly"]
    print(f"GSV/实际推广费月ADS：{monthly[0]}行，月份{monthly[1]}至{monthly[2]}")
    print(f"月ADS GSV/实际推广费/汇总ROI：{amount(monthly[3])}/{amount(monthly[4])}/{Decimal(monthly[5] or 0):.6f}倍")
    print(f"月ADS未匹配公司行数：{monthly[6]}")
    for platform_code in ("douyin", "pdd", "jd", "tmall"):
        print(f"{labels[platform_code]} DWD抽样5条：")
        for sample in result["samples"][platform_code]:
            print(f"  {sample}")


if __name__ == "__main__":
    cli_args = build_parser().parse_args()
    prepare_sources(cli_args)
    metrics = refresh_metric(cli_args)
    print_results(cli_args, metrics)
