#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""刷新八个平台达人佣金独立指标链路，其中四个平台按订单自然日补零。"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError as exc:
    raise SystemExit("缺少依赖：psycopg2。请先执行：pip install psycopg2-binary") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from etl.common.report_sources import prepare_report_sources


CREATE_SQL_FILES = [
    "douyin/influencer_commission/228_dwd_douyin_influencer_commission_event_detail_postgres.sql",
    "douyin/influencer_commission/229_dws_douyin_influencer_commission_shop_daily_postgres.sql",
    "ks/influencer_commission/230_dwd_ks_influencer_commission_event_detail_postgres.sql",
    "ks/influencer_commission/231_dws_ks_influencer_commission_shop_daily_postgres.sql",
    "wechat_channels/influencer_commission/232_dwd_wechat_channels_influencer_commission_event_detail_postgres.sql",
    "wechat_channels/influencer_commission/233_dws_wechat_channels_influencer_commission_shop_daily_postgres.sql",
    "bank/influencer_commission/234_dwd_bank_influencer_commission_statement_split_detail_postgres.sql",
    "bank/influencer_commission/235_dws_bank_influencer_commission_account_daily_postgres.sql",
    "ads/influencer_commission/236_ads_influencer_commission_company_platform_daily_postgres.sql",
    "tmall/influencer_commission/289_tmall_influencer_commission_zero_tables_postgres.sql",
    "jd/influencer_commission/291_jd_influencer_commission_zero_tables_postgres.sql",
    "xhs/influencer_commission/293_xhs_influencer_commission_zero_tables_postgres.sql",
    "pdd/influencer_commission/295_pdd_influencer_commission_zero_tables_postgres.sql",
]

REFRESH_SQL_FILES = [
    "douyin/influencer_commission/237_refresh_dwd_douyin_influencer_commission_event_detail_postgres.sql",
    "douyin/influencer_commission/238_refresh_dws_douyin_influencer_commission_shop_daily_postgres.sql",
    "ks/influencer_commission/239_refresh_dwd_ks_influencer_commission_event_detail_postgres.sql",
    "ks/influencer_commission/240_refresh_dws_ks_influencer_commission_shop_daily_postgres.sql",
    "wechat_channels/influencer_commission/241_refresh_dwd_wechat_channels_influencer_commission_event_detail_postgres.sql",
    "wechat_channels/influencer_commission/242_refresh_dws_wechat_channels_influencer_commission_shop_daily_postgres.sql",
    "bank/influencer_commission/243_refresh_dwd_bank_influencer_commission_statement_split_detail_postgres.sql",
    "bank/influencer_commission/244_refresh_dws_bank_influencer_commission_account_daily_postgres.sql",
    "tmall/influencer_commission/290_refresh_tmall_influencer_commission_zero_postgres.sql",
    "jd/influencer_commission/292_refresh_jd_influencer_commission_zero_postgres.sql",
    "xhs/influencer_commission/294_refresh_xhs_influencer_commission_zero_postgres.sql",
    "pdd/influencer_commission/296_refresh_pdd_influencer_commission_zero_postgres.sql",
    "ads/influencer_commission/245_refresh_ads_influencer_commission_company_platform_daily_postgres.sql",
]

NEW_TABLES = (
    ("dwd", "dwd_douyin_influencer_commission_event_detail"),
    ("dws", "dws_douyin_influencer_commission_shop_daily"),
    ("dwd", "dwd_ks_influencer_commission_event_detail"),
    ("dws", "dws_ks_influencer_commission_shop_daily"),
    ("dwd", "dwd_wechat_channels_influencer_commission_event_detail"),
    ("dws", "dws_wechat_channels_influencer_commission_shop_daily"),
    ("dwd", "dwd_bank_influencer_commission_statement_split_detail"),
    ("dws", "dws_bank_influencer_commission_account_daily"),
    ("dwd", "dwd_tmall_influencer_commission_zero_order_detail"),
    ("dws", "dws_tmall_influencer_commission_shop_daily_zero"),
    ("dwd", "dwd_jd_influencer_commission_zero_order_detail"),
    ("dws", "dws_jd_influencer_commission_shop_daily_zero"),
    ("dwd", "dwd_xhs_influencer_commission_zero_order_detail"),
    ("dws", "dws_xhs_influencer_commission_shop_daily_zero"),
    ("dwd", "dwd_pdd_influencer_commission_zero_order_detail"),
    ("dws", "dws_pdd_influencer_commission_shop_daily_zero"),
    ("ads", "ads_influencer_commission_company_platform_daily"),
)

SOURCE_COLUMNS = {
    ("ods", "ods_douyin_fund_raw"): (
        "id", "batch_id", "动账时间", "动帐流水号", "动账方向", "动账账户",
        "动账场景", "计费类型", "订单号", "子订单号", "达人ID", "达人名称",
        "订单类型", "佣金", "招商服务费", "商户主体名称",
    ),
    ("ods", "ods_ks_settlement_raw"): (
        "id", "batch_id", "实际结算时间", "商家ID", "订单号", "商品ID", "达人ID",
        "MCN机构ID", "团长id", "佣金模式", "结算规则", "资金渠道", "订单退款(元)",
        "达人佣金(元)", "团长佣金(元)", "其他收费", "其他收费明细",
    ),
    ("ods", "ods_wechat_channels_settlement_raw"): (
        "id", "batch_id", "流水单号", "记账时间", "动帐类型", "收支类型", "收支金额",
        "账户余额", "关联订单号", "关联售后单号", "关联提现单号", "详情",
    ),
    ("ods", "ods_bank_statement"): (
        "id", "batch_id", "account_no", "account_name", "transaction_date",
        "transaction_time", "transaction_type", "debit_amount", "credit_amount",
        "summary", "transaction_no",
    ),
    ("ods", "ods_tmall_order_raw"): (
        "id", "batch_id", "子订单编号", "主订单编号", "订单创建时间", "订单状态",
        "source_file_name", "source_sheet_name", "source_row_no", "ingest_time",
    ),
    ("ods", "ods_jd_order_raw"): (
        "id", "batch_id", "订单号", "下单时间", "订单状态",
        "source_file_name", "source_row_no", "ingest_time",
    ),
    ("ods", "ods_xhs_order_raw"): (
        "id", "batch_id", "店铺名称", "订单号", "订单创建时间", "订单状态",
        "售后状态", "source_file_name", "source_row_no", "ingest_time",
    ),
    ("ods", "ods_pdd_order_raw"): (
        "id", "batch_id", "订单号", "订单成交时间", "订单状态", "售后状态",
        "source_file_name", "source_row_no", "ingest_time",
    ),
    ("dwd", "dwd_statement_split"): (
        "id", "ods_id", "batch_id", "split_index", "split_amount", "expense_type_id",
        "account_entry_id", "original_amount", "adjusted_diff", "is_adjusted",
    ),
    ("fund", "import_record"): (
        "batch_id", "status", "is_submitted", "submitted_at",
    ),
}

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="刷新达人佣金八平台独立指标链路。")
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    return parser


def execute_files(cursor, file_names: list[str]) -> None:
    for file_name in file_names:
        cursor.execute((SQL_DIR / file_name).read_text(encoding="utf-8"))


def validate_required_columns(cursor) -> None:
    for (schema_name, table_name), required_columns in SOURCE_COLUMNS.items():
        qualified_name = f"{schema_name}.{table_name}"
        cursor.execute("SELECT to_regclass(%s)", (qualified_name,))
        if cursor.fetchone()[0] is None:
            raise RuntimeError(f"缺少达人佣金来源对象：{qualified_name}")
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            """,
            (schema_name, table_name),
        )
        actual_columns = {row[0] for row in cursor.fetchall()}
        missing_columns = sorted(set(required_columns) - actual_columns)
        if missing_columns:
            raise RuntimeError(f"{qualified_name}缺少必需字段：{missing_columns}")


def count_table(cursor, schema_name: str, table_name: str) -> int:
    cursor.execute(
        sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
    )
    return cursor.fetchone()[0]


def validate_text_column(
    cursor,
    table_name: str,
    column_name: str,
    *,
    kind: str,
    allow_blank: bool = False,
) -> None:
    identifier = sql.Identifier(column_name)
    table_identifier = sql.Identifier("ods", table_name)
    if kind == "numeric":
        pattern = r"^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)$"
        cursor.execute(
            sql.SQL(
                """
                SELECT COUNT(*)
                FROM {}
                WHERE BTRIM(COALESCE({}, '')) NOT IN ('', '-')
                  AND BTRIM({}) !~ %s
                """
            ).format(table_identifier, identifier, identifier),
            (pattern,),
        )
        invalid = cursor.fetchone()[0]
        if invalid:
            raise RuntimeError(f"{table_name}.{column_name}存在{invalid}个不可解析金额")
    elif kind == "timestamp":
        cursor.execute(
            sql.SQL(
                """
                SELECT
                    COUNT(*) FILTER (WHERE {} IS NULL OR BTRIM({}) IN ('', '-')),
                    MIN(NULLIF(NULLIF(BTRIM({}), ''), '-')::timestamp),
                    MAX(NULLIF(NULLIF(BTRIM({}), ''), '-')::timestamp)
                FROM {}
                """
            ).format(identifier, identifier, identifier, identifier, table_identifier)
        )
        blanks, date_from, date_to = cursor.fetchone()
        if blanks and not allow_blank:
            raise RuntimeError(f"{table_name}.{column_name}存在{blanks}个空日期")
        if date_from is None or date_to is None:
            raise RuntimeError(f"{table_name}.{column_name}没有可用日期")


def validate_platform_batches(cursor) -> None:
    cursor.execute(
        """
        WITH source_batches AS (
            SELECT DISTINCT batch_id, 'douyin'::text AS platform_code,
                   'ods_douyin_fund_raw'::text AS target_table
            FROM ods.ods_douyin_fund_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'ks', 'ods_ks_settlement_raw'
            FROM ods.ods_ks_settlement_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'wechat_channels',
                   'ods_wechat_channels_settlement_raw'
            FROM ods.ods_wechat_channels_settlement_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'tmall', 'ods_tmall_order_raw'
            FROM common.v_current_tmall_order_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'jd', 'ods_jd_order_raw'
            FROM common.v_current_jd_order_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'xhs', 'ods_xhs_order_raw'
            FROM common.v_current_xhs_order_raw
            UNION ALL
            SELECT DISTINCT batch_id, 'pdd', 'ods_pdd_order_raw'
            FROM common.v_current_pdd_order_raw
        )
        SELECT COUNT(*)
        FROM source_batches source
        LEFT JOIN common.v_ingest_batch_shop_context context
          ON context.batch_id = source.batch_id
         AND context.platform_code = source.platform_code
         AND context.target_table = source.target_table
        WHERE context.batch_id IS NULL
           OR context.shop_mapping_status <> 'mapped'
           OR context.ingest_status <> 'success'
           OR context.shop_code IS NULL
           OR context.shop_identity_key IS NULL
        """
    )
    invalid_batches = cursor.fetchone()[0]
    if invalid_batches:
        raise RuntimeError(f"达人佣金平台来源存在{invalid_batches}个未映射、冲突或失败批次")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ods.ods_ks_settlement_raw raw
        JOIN common.v_ingest_batch_shop_context context ON context.batch_id = raw.batch_id
        LEFT JOIN dim.dim_platform_shop_company account
          ON account.shop_identity_key = context.shop_identity_key AND account.is_active
         AND CURRENT_DATE >= account.valid_from
         AND (account.valid_to IS NULL OR CURRENT_DATE <= account.valid_to)
        WHERE NULLIF(BTRIM(raw."商家ID"), '') IS NOT NULL
          AND BTRIM(raw."商家ID") IS DISTINCT FROM NULLIF(BTRIM(account.account_id), '')
        """
    )
    ks_conflicts = cursor.fetchone()[0]
    if ks_conflicts:
        raise RuntimeError(f"快手源商家ID与DIM平台账号ID冲突：{ks_conflicts}行")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM ods.ods_douyin_fund_raw
        WHERE NULLIF(LTRIM(BTRIM("动帐流水号"), CHR(39)), '') IS NULL
        """
    )
    blank_flow_numbers = cursor.fetchone()[0]
    if blank_flow_numbers:
        raise RuntimeError(f"抖音资金单存在{blank_flow_numbers}行空动账流水号，无法执行跨批次去重")

def validate_bank_source(cursor) -> tuple[int, int]:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM fund.import_record
        WHERE status = 'success' AND is_submitted
        """
    )
    submitted_batches = cursor.fetchone()[0]
    if submitted_batches == 0:
        raise RuntimeError("没有成功且财务已提交的银行批次")

    cursor.execute(
        """
        SELECT COUNT(DISTINCT ods.id), COUNT(split.id)
        FROM fund.import_record record
        JOIN ods.ods_bank_statement ods ON ods.batch_id = record.batch_id
        LEFT JOIN dwd.dwd_statement_split split
          ON split.batch_id = ods.batch_id AND split.ods_id = ods.id
        WHERE record.status = 'success' AND record.is_submitted
        """
    )
    ods_rows, dwd_rows = cursor.fetchone()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT ods.account_no, ods.transaction_no
            FROM ods.ods_bank_statement ods
            JOIN fund.import_record record ON record.batch_id = ods.batch_id
            WHERE record.status = 'success' AND record.is_submitted
            GROUP BY ods.account_no, ods.transaction_no
            HAVING COUNT(DISTINCT ods.batch_id) > 1
        ) duplicate
        """
    )
    if cursor.fetchone()[0]:
        raise RuntimeError("银行已提交批次存在重复账号流水号")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dwd.dwd_statement_split split
        JOIN fund.import_record record ON record.batch_id = split.batch_id
        JOIN ods.ods_bank_statement ods ON ods.id = split.ods_id
        WHERE record.status = 'success'
          AND record.is_submitted
          AND (
            split.batch_id <> ods.batch_id
            OR split.expense_type_id IS NULL
            OR split.account_entry_id IS NULL
            OR split.original_amount + split.adjusted_diff <= 0
            OR NOT EXISTS (
                SELECT 1
                FROM dim.dim_account_entry_expense_type relation
                WHERE relation.expense_type_id = split.expense_type_id
                  AND relation.account_entry_id = split.account_entry_id
            )
          )
        """
    )
    invalid_details = cursor.fetchone()[0]
    if invalid_details:
        raise RuntimeError(f"银行已提交拆分存在{invalid_details}条分类、关系或金额异常")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT ods.id
            FROM ods.ods_bank_statement ods
            JOIN fund.import_record record ON record.batch_id = ods.batch_id
            LEFT JOIN dwd.dwd_statement_split split
              ON split.ods_id = ods.id AND split.batch_id = ods.batch_id
            WHERE record.status = 'success' AND record.is_submitted
            GROUP BY ods.id, ods.debit_amount, ods.credit_amount
            HAVING COUNT(split.id) = 0
               OR (ods.debit_amount IS NULL) = (ods.credit_amount IS NULL)
               OR ABS(
                    SUM(split.split_amount)
                    - COALESCE(ABS(ods.debit_amount), ABS(ods.credit_amount))
                  ) > 0.01
        ) invalid
        """
    )
    invalid_flows = cursor.fetchone()[0]
    if invalid_flows:
        raise RuntimeError(f"银行已提交批次存在{invalid_flows}条DWD缺失、方向或拆分不平流水")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT split.batch_id
            FROM dwd.dwd_statement_split split
            JOIN fund.import_record record ON record.batch_id = split.batch_id
            WHERE record.status = 'success' AND record.is_submitted
            GROUP BY split.batch_id
            HAVING ABS(SUM(split.adjusted_diff)) > 0.01
        ) invalid
        """
    )
    if cursor.fetchone()[0]:
        raise RuntimeError("银行已提交批次调账净差不为0")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM dim.dim_expense_type expense
        JOIN dim.dim_account_entry_expense_type relation
          ON relation.expense_type_id = expense.id
        JOIN dim.dim_account_entry account_entry
          ON account_entry.id = relation.account_entry_id
        WHERE expense.code = 'EXP006'
          AND expense.name = '销售费用'
          AND account_entry.code = 'ACC006'
          AND account_entry.name = '入账-达人佣金费用'
          AND expense.is_active
          AND account_entry.is_active
        """
    )
    if cursor.fetchone()[0] != 1:
        raise RuntimeError("银行分类关系不是唯一有效的销售费用 -> 入账-达人佣金费用")
    return ods_rows, dwd_rows


def validate_source(cursor) -> dict[str, int]:
    validate_required_columns(cursor)
    validate_platform_batches(cursor)
    for table_name, date_column in (
        ("ods_douyin_fund_raw", "动账时间"),
        ("ods_ks_settlement_raw", "实际结算时间"),
        ("ods_wechat_channels_settlement_raw", "记账时间"),
        ("ods_tmall_order_raw", "订单创建时间"),
        ("ods_jd_order_raw", "下单时间"),
        ("ods_xhs_order_raw", "订单创建时间"),
    ):
        validate_text_column(cursor, table_name, date_column, kind="timestamp")
    validate_text_column(
        cursor,
        "ods_pdd_order_raw",
        "订单成交时间",
        kind="timestamp",
        allow_blank=True,
    )
    for table_name, amount_columns in (
        ("ods_douyin_fund_raw", ("佣金", "招商服务费")),
        ("ods_ks_settlement_raw", ("订单退款(元)", "达人佣金(元)", "团长佣金(元)", "其他收费")),
        ("ods_wechat_channels_settlement_raw", ("收支金额", "账户余额")),
    ):
        for amount_column in amount_columns:
            validate_text_column(cursor, table_name, amount_column, kind="numeric")

    source_counts = {
        "douyin_ods_rows": count_table(cursor, "ods", "ods_douyin_fund_raw"),
        "ks_ods_rows": count_table(cursor, "ods", "ods_ks_settlement_raw"),
        "wechat_ods_rows": count_table(cursor, "ods", "ods_wechat_channels_settlement_raw"),
        "tmall_ods_rows": count_table(cursor, "common", "v_current_tmall_order_raw"),
        "jd_ods_rows": count_table(cursor, "common", "v_current_jd_order_raw"),
        "xhs_ods_rows": count_table(cursor, "common", "v_current_xhs_order_raw"),
        "pdd_ods_rows": count_table(cursor, "common", "v_current_pdd_order_raw"),
    }
    bank_ods_rows, bank_dwd_rows = validate_bank_source(cursor)
    source_counts.update(
        bank_ods_rows=bank_ods_rows,
        bank_dwd_rows=bank_dwd_rows,
    )
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT context.shop_identity_key,
                   NULLIF(LTRIM(BTRIM(raw."动帐流水号"), CHR(39)), '') AS flow_no
            FROM ods.ods_douyin_fund_raw raw
            JOIN common.v_ingest_batch_shop_context context
              ON context.batch_id = raw.batch_id
             AND context.platform_code = 'douyin'
             AND context.target_table = 'ods_douyin_fund_raw'
             AND context.shop_mapping_status = 'mapped'
             AND context.ingest_status = 'success'
            GROUP BY context.shop_identity_key,
                     NULLIF(LTRIM(BTRIM(raw."动帐流水号"), CHR(39)), '')
        ) latest_business_rows
        """
    )
    source_counts["douyin_dwd_rows"] = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(DISTINCT (c.shop_identity_key,NULLIF(BTRIM(r."子订单编号"), ''))),
               COUNT(DISTINCT NULLIF(NULLIF(BTRIM("订单创建时间"), ''), '-')::timestamp::date)
        FROM common.v_current_tmall_order_raw r
        JOIN common.v_ingest_batch_shop_context c ON c.batch_id=r.batch_id
        """
    )
    tmall_dwd_rows, tmall_zero_dws_rows = cursor.fetchone()
    source_counts["tmall_dwd_rows"] = tmall_dwd_rows
    source_counts["tmall_zero_dws_rows"] = tmall_zero_dws_rows
    return source_counts


def validate_comments(cursor) -> None:
    missing: list[str] = []
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            """
            SELECT obj_description(class.oid, 'pg_class')
            FROM pg_class class
            JOIN pg_namespace namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = %s AND class.relname = %s
            """,
            (schema_name, table_name),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            missing.append(f"{schema_name}.{table_name}(表注释)")
        cursor.execute(
            """
            SELECT attribute.attname
            FROM pg_attribute attribute
            JOIN pg_class class ON class.oid = attribute.attrelid
            JOIN pg_namespace namespace ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = %s
              AND class.relname = %s
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
              AND col_description(class.oid, attribute.attnum) IS NULL
            ORDER BY attribute.attnum
            """,
            (schema_name, table_name),
        )
        missing.extend(
            f"{schema_name}.{table_name}.{column[0]}" for column in cursor.fetchall()
        )
    if missing:
        raise RuntimeError(f"新增对象注释不完整：{', '.join(missing)}")


def validate_bidirectional_ads(cursor) -> int:
    cursor.execute(
        """
        WITH ecommerce_daily AS (
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount,
                   included_event_count AS included_detail_count
            FROM dws.dws_douyin_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_event_count
            FROM dws.dws_ks_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_event_count
            FROM dws.dws_wechat_channels_influencer_commission_shop_daily
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_detail_count
            FROM dws.dws_tmall_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_detail_count
            FROM dws.dws_jd_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_detail_count
            FROM dws.dws_xhs_influencer_commission_shop_daily_zero
            UNION ALL
            SELECT stat_date, platform_code, platform_name, shop_code,
                   influencer_commission_amount, included_detail_count
            FROM dws.dws_pdd_influencer_commission_shop_daily_zero
        ),
        ecommerce_expected AS (
            SELECT
                daily.stat_date,
                daily.platform_code,
                COALESCE(dim.company_code, 'unmapped') AS company_code,
                ROUND(SUM(daily.influencer_commission_amount), 2) AS amount,
                SUM(daily.included_detail_count) AS detail_count
            FROM ecommerce_daily daily
            LEFT JOIN dim.dim_platform_shop_company dim
              ON dim.platform_code = daily.platform_code
             AND dim.shop_code = daily.shop_code
             AND dim.is_active
             AND daily.stat_date >= dim.valid_from
             AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
            GROUP BY daily.stat_date, daily.platform_code,
                     COALESCE(dim.company_code, 'unmapped')
        ),
        bank_map AS (
            SELECT
                daily.stat_date,
                daily.source_account_name,
                CASE WHEN COUNT(DISTINCT dim.company_code) = 1
                     THEN MIN(dim.company_code) END AS company_code
            FROM dws.dws_bank_influencer_commission_account_daily daily
            LEFT JOIN dim.dim_platform_shop_company dim
              ON dim.company_name = daily.source_account_name
             AND dim.is_active
             AND daily.stat_date >= dim.valid_from
             AND (dim.valid_to IS NULL OR daily.stat_date <= dim.valid_to)
            GROUP BY daily.stat_date, daily.source_account_name
        ),
        bank_expected AS (
            SELECT
                daily.stat_date,
                daily.platform_code,
                COALESCE(mapping.company_code, 'unmapped') AS company_code,
                ROUND(SUM(daily.influencer_commission_amount), 2) AS amount,
                SUM(daily.included_detail_count) AS detail_count
            FROM dws.dws_bank_influencer_commission_account_daily daily
            LEFT JOIN bank_map mapping
              ON mapping.stat_date = daily.stat_date
             AND mapping.source_account_name = daily.source_account_name
            GROUP BY daily.stat_date, daily.platform_code,
                     COALESCE(mapping.company_code, 'unmapped')
        ),
        expected AS (
            SELECT * FROM ecommerce_expected
            UNION ALL
            SELECT * FROM bank_expected
        ),
        actual AS (
            SELECT stat_date, platform_code, company_code,
                   influencer_commission_amount AS amount,
                   included_detail_count AS detail_count
            FROM ads.ads_influencer_commission_company_platform_daily
        )
        SELECT COUNT(*)
        FROM (
            (SELECT * FROM expected EXCEPT SELECT * FROM actual)
            UNION ALL
            (SELECT * FROM actual EXCEPT SELECT * FROM expected)
        ) difference
        """
    )
    return cursor.fetchone()[0]


def validate_samples(cursor) -> list[tuple]:
    cursor.execute(
        """
        (SELECT '抖音正常费用', source_id, stat_date,
                creator_commission_source_amount::text,
                recruitment_service_fee_source_amount::text,
                (creator_commission_amount + recruitment_service_fee_amount)::text
         FROM dwd.dwd_douyin_influencer_commission_event_detail
         WHERE creator_commission_source_amount < 0
         ORDER BY ABS(creator_commission_source_amount) DESC
         LIMIT 1)
        UNION ALL
        (SELECT '抖音退款冲回', source_id, stat_date,
                creator_commission_source_amount::text,
                recruitment_service_fee_source_amount::text,
                (creator_commission_amount + recruitment_service_fee_amount)::text
         FROM dwd.dwd_douyin_influencer_commission_event_detail
         WHERE creator_commission_source_amount > 0
         ORDER BY source_id
         LIMIT 1)
        UNION ALL
        (SELECT '抖音零金额保留', source_id, stat_date,
                creator_commission_source_amount::text,
                recruitment_service_fee_source_amount::text,
                (creator_commission_amount + recruitment_service_fee_amount)::text
         FROM dwd.dwd_douyin_influencer_commission_event_detail
         WHERE creator_commission_source_amount = 0
           AND recruitment_service_fee_source_amount = 0
         ORDER BY source_id
         LIMIT 1)
        UNION ALL
        (SELECT '快手正常佣金', source_id, stat_date,
                talent_commission_amount::text,
                leader_commission_amount::text,
                (talent_commission_amount + leader_commission_amount + other_fee_amount)::text
         FROM dwd.dwd_ks_influencer_commission_event_detail
         WHERE order_refund_amount = 0
           AND talent_commission_amount + leader_commission_amount + other_fee_amount > 0
         ORDER BY talent_commission_amount + leader_commission_amount + other_fee_amount DESC
         LIMIT 1)
        UNION ALL
        (SELECT '快手退款仍纳入', source_id, stat_date,
                talent_commission_amount::text,
                leader_commission_amount::text,
                (talent_commission_amount + leader_commission_amount + other_fee_amount)::text
         FROM dwd.dwd_ks_influencer_commission_event_detail
         WHERE order_refund_amount > 0
           AND talent_commission_amount + leader_commission_amount + other_fee_amount > 0
         ORDER BY source_id
         LIMIT 1)
        UNION ALL
        (SELECT '视频号达人佣金', source_id, stat_date,
                movement_type,
                income_expense_direction,
                directional_expense_amount::text
         FROM dwd.dwd_wechat_channels_influencer_commission_event_detail
         WHERE movement_type = '达人佣金'
         ORDER BY source_id
         LIMIT 1)
        UNION ALL
        (SELECT '视频号机构服务费', source_id, stat_date,
                movement_type,
                income_expense_direction,
                directional_expense_amount::text
         FROM dwd.dwd_wechat_channels_influencer_commission_event_detail
         WHERE movement_type = '带货机构服务费'
         ORDER BY source_id
         LIMIT 1)
        UNION ALL
        (SELECT '银行已提交分类', source_split_id, stat_date,
                expense_type_name,
                account_entry_name,
                directional_expense_amount::text
         FROM dwd.dwd_bank_influencer_commission_statement_split_detail
         WHERE expense_type_code = 'EXP006' AND account_entry_code = 'ACC006'
         ORDER BY ABS(directional_expense_amount) DESC
         LIMIT 1)
        UNION ALL
        (SELECT '补零平台占位', 0::bigint, stat_date,
                platform_code,
                influencer_commission_amount::text,
                included_detail_count::text
         FROM dws.dws_tmall_influencer_commission_shop_daily_zero
         ORDER BY stat_date
         LIMIT 1)
        """
    )
    samples = cursor.fetchall()
    if len(samples) < 9:
        raise RuntimeError(f"达人佣金公式抽样场景不足：{samples}")
    return samples


def validate_pipeline(cursor, source_counts: dict[str, int]) -> dict[str, object]:
    table_profiles: dict[str, tuple] = {}
    for schema_name, table_name in NEW_TABLES:
        cursor.execute(
            sql.SQL("SELECT COUNT(*), MIN(stat_date), MAX(stat_date) FROM {}.{}").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
            )
        )
        table_profiles[f"{schema_name}.{table_name}"] = cursor.fetchone()

    expected_rows = {
        "dwd.dwd_douyin_influencer_commission_event_detail": source_counts["douyin_dwd_rows"],
        "dwd.dwd_ks_influencer_commission_event_detail": source_counts["ks_ods_rows"],
        "dwd.dwd_wechat_channels_influencer_commission_event_detail": source_counts["wechat_ods_rows"],
        "dwd.dwd_bank_influencer_commission_statement_split_detail": source_counts["bank_dwd_rows"],
        "dwd.dwd_tmall_influencer_commission_zero_order_detail": source_counts["tmall_dwd_rows"],
        "dws.dws_tmall_influencer_commission_shop_daily_zero": source_counts["tmall_zero_dws_rows"],
        "dwd.dwd_jd_influencer_commission_zero_order_detail": source_counts["jd_ods_rows"],
        "dwd.dwd_xhs_influencer_commission_zero_order_detail": source_counts["xhs_ods_rows"],
        "dwd.dwd_pdd_influencer_commission_zero_order_detail": source_counts["pdd_ods_rows"],
    }
    for table_name, row_count in expected_rows.items():
        if table_profiles[table_name][0] != row_count:
            raise RuntimeError(
                f"{table_name}行数变化：{table_profiles[table_name][0]}，预期{row_count}"
            )

    cursor.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_douyin_influencer_commission_event_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_ks_influencer_commission_event_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_wechat_channels_influencer_commission_event_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_split_id FROM dwd.dwd_bank_influencer_commission_statement_split_detail
             GROUP BY source_split_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_tmall_influencer_commission_zero_order_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_jd_influencer_commission_zero_order_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_xhs_influencer_commission_zero_order_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT source_id FROM dwd.dwd_pdd_influencer_commission_zero_order_detail
             GROUP BY source_id HAVING COUNT(*) > 1
           ) duplicate),
          (SELECT COUNT(*) FROM (
             SELECT stat_date, platform_code, company_code
             FROM ads.ads_influencer_commission_company_platform_daily
             GROUP BY stat_date, platform_code, company_code
             HAVING COUNT(*) > 1
           ) duplicate)
        """
    )
    duplicate_keys = cursor.fetchone()
    if any(duplicate_keys):
        raise RuntimeError(f"达人佣金DWD或ADS主键重复：{duplicate_keys}")

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(creator_commission_amount), 0),
            COALESCE(SUM(recruitment_service_fee_amount), 0),
            COALESCE(SUM(influencer_commission_amount), 0),
            COALESCE(SUM(included_event_count), 0)
        FROM dws.dws_douyin_influencer_commission_shop_daily
        """
    )
    douyin = cursor.fetchone()
    cursor.execute(
        """
        SELECT COALESCE(SUM(creator_commission_amount), 0),
               COALESCE(SUM(recruitment_service_fee_amount), 0),
               COALESCE(SUM(creator_commission_amount + recruitment_service_fee_amount), 0),
               COUNT(*) FILTER (
                   WHERE creator_commission_amount + recruitment_service_fee_amount <> 0
               )
        FROM dwd.dwd_douyin_influencer_commission_event_detail
        """
    )
    douyin_source = cursor.fetchone()
    if douyin != douyin_source:
        raise RuntimeError(f"抖音达人佣金DWD/DWS汇总不一致：{douyin_source}/{douyin}")
    if douyin[2] != douyin[0] + douyin[1]:
        raise RuntimeError(f"抖音达人佣金DWS组成公式不平：{douyin}")

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(talent_commission_amount), 0),
            COALESCE(SUM(leader_commission_amount), 0),
            COALESCE(SUM(other_fee_amount), 0),
            COALESCE(SUM(influencer_commission_amount), 0),
            COALESCE(SUM(included_event_count), 0),
            COALESCE(SUM(included_refund_event_count), 0)
        FROM dws.dws_ks_influencer_commission_shop_daily
        """
    )
    ks = cursor.fetchone()
    cursor.execute(
        """
        SELECT COALESCE(SUM(talent_commission_amount), 0),
               COALESCE(SUM(leader_commission_amount), 0),
               COALESCE(SUM(other_fee_amount), 0),
               COALESCE(SUM(
                   talent_commission_amount + leader_commission_amount + other_fee_amount
               ), 0),
               COUNT(*) FILTER (
                   WHERE talent_commission_amount + leader_commission_amount + other_fee_amount <> 0
               ),
               COUNT(*) FILTER (
                   WHERE talent_commission_amount + leader_commission_amount + other_fee_amount <> 0
                     AND order_refund_amount > 0
               )
        FROM dwd.dwd_ks_influencer_commission_event_detail
        """
    )
    ks_source = cursor.fetchone()
    if ks != ks_source:
        raise RuntimeError(f"快手达人佣金DWD/DWS汇总不一致：{ks_source}/{ks}")
    if ks[3] != ks[0] + ks[1] + ks[2]:
        raise RuntimeError(f"快手达人佣金DWS组成公式不平：{ks}")

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(creator_commission_amount), 0),
            COALESCE(SUM(agency_service_fee_amount), 0),
            COALESCE(SUM(influencer_commission_amount), 0),
            COALESCE(SUM(included_event_count), 0)
        FROM dws.dws_wechat_channels_influencer_commission_shop_daily
        """
    )
    wechat = cursor.fetchone()
    cursor.execute(
        """
        SELECT COALESCE(SUM(directional_expense_amount) FILTER (
                   WHERE movement_type = '达人佣金'
               ), 0),
               COALESCE(SUM(directional_expense_amount) FILTER (
                   WHERE movement_type = '带货机构服务费'
               ), 0),
               COALESCE(SUM(directional_expense_amount), 0),
               COUNT(*)
        FROM dwd.dwd_wechat_channels_influencer_commission_event_detail
        WHERE movement_type IN ('达人佣金', '带货机构服务费')
          AND directional_expense_amount <> 0
        """
    )
    wechat_source = cursor.fetchone()
    if wechat != wechat_source:
        raise RuntimeError(f"视频号达人佣金DWD/DWS汇总不一致：{wechat_source}/{wechat}")
    if wechat[2] != wechat[0] + wechat[1]:
        raise RuntimeError(f"视频号达人佣金DWS组成公式不平：{wechat}")

    cursor.execute(
        """
        SELECT COALESCE(SUM(influencer_commission_amount), 0),
               COALESCE(SUM(included_detail_count), 0)
        FROM dws.dws_bank_influencer_commission_account_daily
        """
    )
    bank = cursor.fetchone()
    cursor.execute(
        """
        SELECT COALESCE(SUM(directional_expense_amount), 0), COUNT(*)
        FROM dwd.dwd_bank_influencer_commission_statement_split_detail
        WHERE expense_type_code = 'EXP006'
          AND expense_type_name = '销售费用'
          AND account_entry_code = 'ACC006'
          AND account_entry_name = '入账-达人佣金费用'
          AND directional_expense_amount <> 0
        """
    )
    bank_source = cursor.fetchone()
    if bank != bank_source:
        raise RuntimeError(f"银行达人佣金DWD/DWS汇总不一致：{bank_source}/{bank}")

    zero_components: dict[str, tuple] = {}
    for platform_code, table_name in (
        ("tmall", "dws_tmall_influencer_commission_shop_daily_zero"),
        ("jd", "dws_jd_influencer_commission_shop_daily_zero"),
        ("xhs", "dws_xhs_influencer_commission_shop_daily_zero"),
        ("pdd", "dws_pdd_influencer_commission_shop_daily_zero"),
    ):
        cursor.execute(
            sql.SQL(
                """
                SELECT COALESCE(SUM(influencer_commission_amount), 0),
                       COALESCE(SUM(included_detail_count), 0)
                FROM dws.{}
                """
            ).format(sql.Identifier(table_name))
        )
        zero_components[platform_code] = cursor.fetchone()
        if zero_components[platform_code] != (Decimal("0.00"), 0):
            raise RuntimeError(
                f"{platform_code}达人佣金补零DWS出现非零值："
                f"{zero_components[platform_code]}"
            )

    cursor.execute(
        """
        SELECT platform_code,
               COALESCE(SUM(influencer_commission_amount), 0),
               COALESCE(SUM(included_detail_count), 0)
        FROM ads.ads_influencer_commission_company_platform_daily
        GROUP BY platform_code
        ORDER BY platform_code
        """
    )
    platform_totals = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    cursor.execute(
        """
        SELECT COALESCE(SUM(influencer_commission_amount), 0),
               COUNT(*) FILTER (WHERE company_code = 'unmapped'),
               MIN(stat_date),
               MAX(stat_date)
        FROM ads.ads_influencer_commission_company_platform_daily
        """
    )
    total, unmapped, date_from, date_to = cursor.fetchone()
    if unmapped:
        raise RuntimeError(f"达人佣金ADS存在{unmapped}行未匹配公司")
    bidirectional_difference = validate_bidirectional_ads(cursor)
    if bidirectional_difference:
        raise RuntimeError(f"达人佣金DWS/ADS双向逐粒度差异：{bidirectional_difference}")

    samples = validate_samples(cursor)
    validate_comments(cursor)
    return {
        "table_profiles": table_profiles,
        "components": {
            "douyin": douyin,
            "ks": ks,
            "wechat_channels": wechat,
            "bank": bank,
            "zero_platforms": zero_components,
        },
        "platform_totals": platform_totals,
        "total": total,
        "unmapped": unmapped,
        "date_range": (date_from, date_to),
        "duplicate_keys": duplicate_keys,
        "bidirectional_difference": bidirectional_difference,
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
            prepare_report_sources(cursor, ('tmall','jd','xhs','pdd'))
            source_counts = validate_source(cursor)
            execute_files(cursor, CREATE_SQL_FILES)
            execute_files(cursor, REFRESH_SQL_FILES)
            result = validate_pipeline(cursor, source_counts)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(f"数据库：{args.dbname}")
    print(f"来源行数：{source_counts}")
    print(f"各平台组成与明细数：{result['components']}")
    print(f"ADS各平台汇总：{result['platform_totals']}")
    print(f"ADS总额：{result['total']:.2f}")
    print(f"ADS日期范围：{result['date_range'][0]} 至 {result['date_range'][1]}")
    print(f"ADS未匹配公司行数：{result['unmapped']}")
    print(f"DWS/ADS双向逐粒度差异：{result['bidirectional_difference']}")
    print(f"DWD/ADS重复主键组：{result['duplicate_keys']}")
    print("各层行数与日期范围：")
    for table_name, profile in result["table_profiles"].items():
        print(f"  {table_name}: {profile[0]}行，{profile[1]} 至 {profile[2]}")
    print("公式抽样（场景,来源主键,日期,组成1,组成2/方向,指标金额）：")
    for sample in result["samples"]:
        print(f"  {sample}")


if __name__ == "__main__":
    run_pipeline(build_parser().parse_args())
