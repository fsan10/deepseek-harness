#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""达人商务归属与月度GMV目标的本地配置网页服务。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from datetime import date, datetime
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    from apps.influencer_config.influencer_master import InfluencerMasterService
    from apps.influencer_config.product_category import ProductCategoryService
    from apps.influencer_config.refresh_queue import CoalescingRefreshWorker
except ModuleNotFoundError:  # 兼容直接执行本文件。
    from influencer_master import InfluencerMasterService
    from product_category import ProductCategoryService
    from refresh_queue import CoalescingRefreshWorker

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # 允许无数据库驱动的静态与路由单元测试运行。
    psycopg2 = None
    RealDictCursor = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
SQL_DIR = PROJECT_ROOT / "sql"

PLATFORMS = {
    "douyin": "抖音",
    "ks": "快手",
    "wechat_channels": "视频号",
    "tmall": "天猫",
    "xhs": "小红书",
    "jd": "京东",
    "pdd": "拼多多",
}

ASSIGNMENT_REFRESH_FILES = [
    "ads/influencer_performance/399_refresh_ads_influencer_company_shop_daily_company_identity_postgres.sql",
    "ads/influencer_performance/400_refresh_ads_influencer_monthly_ranking_company_identity_postgres.sql",
    "ads/influencer_performance/401_refresh_ads_influencer_business_monthly_company_identity_postgres.sql",
]
TARGET_REFRESH_FILES = [
    "ads/influencer_performance/401_refresh_ads_influencer_business_monthly_company_identity_postgres.sql",
]


class BusinessNotFoundError(ValueError):
    http_status = 404


class BusinessConflictError(ValueError):
    http_status = 409


def json_default(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"无法序列化：{type(value)!r}")


def parse_month(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}(?:-01)?", value or ""):
        raise ValueError("月份格式必须为YYYY-MM")
    normalized = value[:7] + "-01"
    return datetime.strptime(normalized, "%Y-%m-%d").date()


def normalize_shop_names(value) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else re.split(r"[\n,，;；]+", str(value))
    result = []
    seen = set()
    for item in raw_items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        if len(name) > 255:
            raise ValueError("单个店铺名称不能超过255字")
        seen.add(name)
        result.append(name)
    return result


class Database:
    def __init__(self, args: argparse.Namespace):
        self.connect_kwargs = {
            "host": args.host,
            "port": args.port,
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        }
        self._metrics_refresh = CoalescingRefreshWorker(
            "influencer-metrics",
            self._refresh_metrics_now,
            debounce_seconds=0.2,
        )

    def connect(self):
        if psycopg2 is None:
            raise RuntimeError("缺少依赖psycopg2-binary，请先安装requirements.txt")
        return psycopg2.connect(**self.connect_kwargs)

    @staticmethod
    def execute_files(cursor, relative_paths: list[str]) -> None:
        for relative_path in relative_paths:
            cursor.execute((SQL_DIR / relative_path).read_text(encoding="utf-8"))

    def _refresh_metrics_now(self) -> dict:
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                self.execute_files(cursor, ASSIGNMENT_REFRESH_FILES)
                cursor.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM ads.ads_influencer_company_shop_daily) AS daily_rows,
                        (SELECT COUNT(*) FROM ads.ads_influencer_company_shop_monthly_ranking) AS ranking_rows,
                        (SELECT COUNT(*) FROM ads.ads_influencer_business_monthly) AS business_rows
                    """
                )
                result = dict(cursor.fetchone())
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _queue_metrics_refresh(self, result: dict, reason: str) -> dict:
        result["metrics_refreshed"] = False
        result["metrics_refresh"] = self._metrics_refresh.request(reason)
        return result

    def request_metrics_refresh(self, reason: str) -> dict:
        return self._metrics_refresh.request(reason)

    def refresh_status(self) -> dict:
        return self._metrics_refresh.status()

    def wait_for_refresh(self, timeout: float = 30.0) -> bool:
        return self._metrics_refresh.wait_until_idle(timeout)

    def close(self, *, drain: bool = True, timeout: float = 30.0) -> bool:
        return self._metrics_refresh.close(drain=drain, timeout=timeout)

    def health(self) -> dict:
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database() AS database_name,
                        to_regclass('dim.dim_influencer_business_assignment_monthly') IS NOT NULL AS assignment_ready,
                        to_regclass('dim.dim_business_gmv_target_monthly') IS NOT NULL AS target_ready,
                        to_regclass('ads.ads_influencer_company_shop_daily') IS NOT NULL AS ads_ready
                    """
                )
                result = cursor.fetchone()
                if all(result[key] for key in ("assignment_ready", "target_ready", "ads_ready")):
                    cursor.execute(
                        """
                        SELECT
                            (SELECT COUNT(*) FROM dim.dim_business_owner WHERE is_active) AS active_businesses,
                            (SELECT COUNT(*) FROM dim.dim_influencer_business_assignment_monthly) AS assignment_versions,
                            (SELECT COUNT(*) FROM ads.ads_influencer_company_shop_daily) AS daily_ads_rows
                        """
                    )
                    result.update(cursor.fetchone())
                response = dict(result)
                response["metrics_refresh"] = self.refresh_status()
                return response
        finally:
            connection.close()

    def list_businesses(self) -> list[dict]:
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT business_owner_id, business_owner_name, is_active
                    FROM dim.dim_business_owner
                    ORDER BY is_active DESC, business_owner_name
                    """
                )
                return [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()

    def create_business(self, business_name: str) -> dict:
        name = self.normalize_business_name(business_name)
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_business_owner (business_owner_name)
                    VALUES (%s)
                    ON CONFLICT (business_owner_name)
                    DO UPDATE SET is_active = TRUE, updated_at = NOW()
                    RETURNING business_owner_id, business_owner_name, is_active
                    """,
                    (name,),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return self._queue_metrics_refresh(row, "business.created")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def normalize_business_name(business_name: str) -> str:
        name = (business_name or "").strip()
        if not name or len(name) > 128:
            raise ValueError("商务姓名不能为空且不能超过128字")
        return name

    @staticmethod
    def update_business_name(cursor, business_owner_id: int, business_name: str) -> dict:
        cursor.execute(
            """
            SELECT business_owner_id
            FROM dim.dim_business_owner
            WHERE business_owner_name = %s
              AND business_owner_id <> %s
            """,
            (business_name, business_owner_id),
        )
        if cursor.fetchone() is not None:
            raise BusinessConflictError("商务姓名已存在，请使用其他姓名")
        cursor.execute(
            """
            UPDATE dim.dim_business_owner
            SET business_owner_name = %s,
                updated_at = NOW()
            WHERE business_owner_id = %s
              AND is_active
            RETURNING business_owner_id, business_owner_name, is_active
            """,
            (business_name, business_owner_id),
        )
        row = cursor.fetchone()
        if row is None:
            raise BusinessNotFoundError("商务不存在或已删除")
        return dict(row)

    def update_business(self, business_owner_id: int, business_name: str) -> dict:
        name = self.normalize_business_name(business_name)
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                row = self.update_business_name(cursor, business_owner_id, name)
            connection.commit()
            return self._queue_metrics_refresh(row, "business.updated")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete_business(self, business_owner_id: int) -> dict:
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE dim.dim_business_owner
                    SET is_active = FALSE,
                        updated_at = NOW()
                    WHERE business_owner_id = %s
                      AND is_active
                    RETURNING business_owner_id, business_owner_name, is_active
                    """,
                    (business_owner_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise BusinessNotFoundError("商务不存在或已删除")
            connection.commit()
            return self._queue_metrics_refresh(dict(row), "business.disabled")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_influencers(
        self,
        month: date,
        platform_code: str | None,
        business_owner_id: int | None,
        assignment_status: str | None,
        search: str | None,
        page: int,
        page_size: int,
        active_status: str | None = None,
    ) -> dict:
        if page < 1:
            raise ValueError("页码必须大于等于1")
        if page_size not in {10, 20, 50, 100}:
            raise ValueError("每页条数仅支持10、20、50或100")
        filters = []
        params: list[object] = [month]
        if platform_code:
            if platform_code not in PLATFORMS:
                raise ValueError("不支持的平台编码")
            filters.append("assignment.platform_code = %s")
            params.append(platform_code)
        if business_owner_id is not None:
            filters.append("COALESCE(assignment.business_owner_id, 0) = %s")
            params.append(business_owner_id)
        if assignment_status == "assigned":
            filters.append("assignment.business_owner_id IS NOT NULL")
        elif assignment_status == "unassigned":
            filters.append("assignment.business_owner_id IS NULL")
        if active_status == "active":
            filters.append("assignment.is_active")
        elif active_status == "disabled":
            filters.append("NOT assignment.is_active")
        if search:
            filters.append(
                "(assignment.influencer_id ILIKE %s OR assignment.influencer_name ILIKE %s "
                "OR COALESCE(owner.business_owner_name, '') ILIKE %s "
                "OR ARRAY_TO_STRING(assignment.source_shop_names, '、') ILIKE %s "
                "OR COALESCE(assignment.note, '') ILIKE %s)"
            )
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern, pattern, pattern, pattern])
        if active_status not in ("active", "disabled"):
            filters.insert(0, "assignment.is_active")
        where_clause = "WHERE " + " AND ".join(filters)

        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"""
                    WITH latest_assignment AS (
                        SELECT DISTINCT ON (platform_code, influencer_id)
                            platform_code,
                            platform_name,
                            influencer_id,
                            influencer_name,
                            effective_month,
                            business_owner_id,
                            assignment_source,
                            source_file_name,
                            source_shop_names,
                            note,
                            is_active
                        FROM dim.dim_influencer_business_assignment_monthly
                        WHERE effective_month <= %s
                        ORDER BY platform_code, influencer_id, effective_month DESC
                    )
                    SELECT
                        assignment.platform_code,
                        assignment.platform_name,
                        assignment.influencer_id,
                        CASE WHEN assignment.influencer_id = '0' THEN '其他'
                             ELSE assignment.influencer_name END AS influencer_name,
                        assignment.effective_month,
                        assignment.business_owner_id,
                        owner.business_owner_name,
                        assignment.assignment_source,
                        assignment.source_file_name,
                        assignment.source_shop_names,
                        assignment.note,
                        assignment.is_active
                    FROM latest_assignment assignment
                    LEFT JOIN dim.dim_business_owner owner
                      ON owner.business_owner_id = assignment.business_owner_id
                    {where_clause}
                    ORDER BY
                        assignment.is_active DESC,
                        assignment.platform_name,
                        assignment.influencer_name,
                        assignment.influencer_id
                    """,
                    params,
                )
                all_rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()

        total = len(all_rows)
        total_pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, total_pages)
        offset = (current_page - 1) * page_size
        rows = all_rows[offset : offset + page_size]

        return {
            "month": month,
            "rows": rows,
            "summary": {
                "total": total,
                "assigned": sum(1 for row in all_rows if row["business_owner_id"] is not None),
                "unassigned": sum(1 for row in all_rows if row["business_owner_id"] is None),
                "platforms": len({row["platform_code"] for row in all_rows}),
                "excel_seed": sum(1 for row in all_rows if row["assignment_source"] == "excel_seed"),
                "web": sum(1 for row in all_rows if row["assignment_source"] == "web"),
                "active": sum(1 for row in all_rows if row["is_active"]),
                "disabled": sum(1 for row in all_rows if not row["is_active"]),
            },
            "pagination": {
                "page": current_page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
            },
        }

    def save_assignment(self, payload: dict) -> dict:
        platform_code = str(payload.get("platform_code") or "").strip()
        influencer_id = str(payload.get("influencer_id") or "").strip()
        influencer_name = str(payload.get("influencer_name") or "").strip()
        effective_month = parse_month(str(payload.get("effective_month") or ""))
        note = str(payload.get("note") or "").strip() or None
        shop_names = normalize_shop_names(payload.get("source_shop_names"))
        raw_owner_id = payload.get("business_owner_id")
        owner_id = int(raw_owner_id) if raw_owner_id not in (None, "", 0, "0") else None
        original_platform_code = str(payload.get("original_platform_code") or platform_code).strip()
        original_influencer_id = str(payload.get("original_influencer_id") or influencer_id).strip()

        if platform_code not in PLATFORMS:
            raise ValueError("不支持的平台编码")
        if original_platform_code not in PLATFORMS:
            raise ValueError("原平台编码无效")
        if not influencer_id or len(influencer_id) > 128:
            raise ValueError("达人ID不能为空且不能超过128字")
        if not original_influencer_id or len(original_influencer_id) > 128:
            raise ValueError("原达人ID不能为空且不能超过128字")
        if influencer_id == "0":
            influencer_name = "其他"
        elif not influencer_name:
            raise ValueError("达人名称不能为空")
        if len(influencer_name) > 255:
            raise ValueError("达人名称不能超过255字")
        if note and len(note) > 2000:
            raise ValueError("备注不能超过2000字")

        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                if owner_id is not None:
                    cursor.execute(
                        "SELECT 1 FROM dim.dim_business_owner WHERE business_owner_id = %s AND is_active",
                        (owner_id,),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError("选择的商务不存在或已停用")

                identity_changed = (
                    original_platform_code != platform_code
                    or original_influencer_id != influencer_id
                )
                if identity_changed:
                    cursor.execute(
                        """
                        SELECT platform_code, platform_name, influencer_id, influencer_name,
                               business_owner_id, source_file_name, source_shop_names, note, is_active
                        FROM dim.dim_influencer_business_assignment_monthly
                        WHERE platform_code = %s
                          AND influencer_id = %s
                          AND effective_month <= %s
                        ORDER BY effective_month DESC
                        LIMIT 1
                        """,
                        (original_platform_code, original_influencer_id, effective_month),
                    )
                    original = cursor.fetchone()
                    if original is None or not original["is_active"]:
                        raise ValueError("要修改的达人已不在当前月份配置库")

                    cursor.execute(
                        """
                        SELECT is_active
                        FROM dim.dim_influencer_business_assignment_monthly
                        WHERE platform_code = %s
                          AND influencer_id = %s
                          AND effective_month <= %s
                        ORDER BY effective_month DESC
                        LIMIT 1
                        """,
                        (platform_code, influencer_id, effective_month),
                    )
                    target = cursor.fetchone()
                    if target is not None and target["is_active"]:
                        raise ValueError("修改后的平台和达人ID已存在于配置库")

                    cursor.execute(
                        """
                        INSERT INTO dim.dim_influencer_business_assignment_monthly (
                            platform_code, platform_name, influencer_id, influencer_name,
                            effective_month, business_owner_id, assignment_source,
                            source_file_name, source_shop_names, note, is_active
                        )
                        VALUES (%s, %s, %s, %s, %s, NULL, 'web', %s, %s, %s, FALSE)
                        ON CONFLICT (platform_code, influencer_id, effective_month)
                        DO UPDATE SET
                            business_owner_id = NULL,
                            assignment_source = 'web',
                            source_shop_names = EXCLUDED.source_shop_names,
                            note = EXCLUDED.note,
                            is_active = FALSE,
                            updated_at = NOW()
                        """,
                        (
                            original["platform_code"], original["platform_name"],
                            original["influencer_id"], original["influencer_name"],
                            effective_month, original["source_file_name"],
                            original["source_shop_names"], original["note"],
                        ),
                    )

                cursor.execute(
                    """
                    INSERT INTO dim.dim_influencer_business_assignment_monthly (
                        platform_code,
                        platform_name,
                        influencer_id,
                        influencer_name,
                        effective_month,
                        business_owner_id,
                        assignment_source,
                        source_shop_names,
                        note,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'web', %s, %s, TRUE)
                    ON CONFLICT (platform_code, influencer_id, effective_month)
                    DO UPDATE SET
                        platform_name = EXCLUDED.platform_name,
                        influencer_name = EXCLUDED.influencer_name,
                        business_owner_id = EXCLUDED.business_owner_id,
                        assignment_source = 'web',
                        source_shop_names = EXCLUDED.source_shop_names,
                        note = EXCLUDED.note,
                        is_active = TRUE,
                        updated_at = NOW()
                    RETURNING platform_code, platform_name, influencer_id, influencer_name,
                              effective_month, business_owner_id, assignment_source,
                              source_shop_names, note, is_active
                    """,
                    (
                        platform_code,
                        PLATFORMS[platform_code],
                        influencer_id,
                        influencer_name,
                        effective_month,
                        owner_id,
                        shop_names,
                        note,
                    ),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return self._queue_metrics_refresh(row, "assignment.saved")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def delete_influencer(self, platform_code: str, influencer_id: str, effective_month: date) -> dict:
        """删除达人：软删除，清空商务归属并标记 is_active=FALSE。"""
        if platform_code not in PLATFORMS:
            raise ValueError("不支持的平台编码")
        influencer_id = (influencer_id or "").strip()
        if not influencer_id:
            raise ValueError("达人ID不能为空")

        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT platform_code, platform_name, influencer_id, influencer_name,
                           source_file_name, source_shop_names, note, is_active
                    FROM dim.dim_influencer_business_assignment_monthly
                    WHERE platform_code = %s
                      AND influencer_id = %s
                      AND effective_month <= %s
                    ORDER BY effective_month DESC
                    LIMIT 1
                    """,
                    (platform_code, influencer_id, effective_month),
                )
                current = cursor.fetchone()
                if current is None:
                    raise ValueError("该达人不在配置库中")
                cursor.execute(
                    """
                    INSERT INTO dim.dim_influencer_business_assignment_monthly (
                        platform_code, platform_name, influencer_id, influencer_name,
                        effective_month, business_owner_id, assignment_source,
                        source_file_name, source_shop_names, note, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, NULL, 'web', %s, %s, %s, FALSE)
                    ON CONFLICT (platform_code, influencer_id, effective_month)
                    DO UPDATE SET
                        business_owner_id = NULL,
                        assignment_source = 'web',
                        source_shop_names = EXCLUDED.source_shop_names,
                        note = EXCLUDED.note,
                        is_active = FALSE,
                        updated_at = NOW()
                    RETURNING platform_code, influencer_id, influencer_name, effective_month, is_active
                    """,
                    (
                        current["platform_code"], current["platform_name"],
                        current["influencer_id"], current["influencer_name"],
                        effective_month, current["source_file_name"],
                        current["source_shop_names"], current["note"],
                    ),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return self._queue_metrics_refresh(row, "influencer.deleted")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def toggle_influencer_status(
        self, platform_code: str, influencer_id: str, effective_month: date, is_active: bool
    ) -> dict:
        """停用/启用达人：切换 is_active 状态，保留商务归属等所有字段。"""
        if platform_code not in PLATFORMS:
            raise ValueError("不支持的平台编码")
        influencer_id = (influencer_id or "").strip()
        if not influencer_id:
            raise ValueError("达人ID不能为空")
        if not isinstance(is_active, bool):
            raise ValueError("达人启用状态必须为布尔值")

        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT platform_code, platform_name, influencer_id, influencer_name,
                           business_owner_id, assignment_source, source_file_name,
                           source_shop_names, note, is_active
                    FROM dim.dim_influencer_business_assignment_monthly
                    WHERE platform_code = %s
                      AND influencer_id = %s
                      AND effective_month <= %s
                    ORDER BY effective_month DESC
                    LIMIT 1
                    """,
                    (platform_code, influencer_id, effective_month),
                )
                current = cursor.fetchone()
                if current is None:
                    raise ValueError("该达人不在配置库中")
                cursor.execute(
                    """
                    INSERT INTO dim.dim_influencer_business_assignment_monthly (
                        platform_code, platform_name, influencer_id, influencer_name,
                        effective_month, business_owner_id, assignment_source,
                        source_file_name, source_shop_names, note, is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (platform_code, influencer_id, effective_month)
                    DO UPDATE SET
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    RETURNING platform_code, influencer_id, influencer_name,
                              effective_month, is_active, business_owner_id
                    """,
                    (
                        current["platform_code"], current["platform_name"],
                        current["influencer_id"], current["influencer_name"],
                        effective_month, current["business_owner_id"],
                        current["assignment_source"], current["source_file_name"],
                        current["source_shop_names"], current["note"],
                        is_active,
                    ),
                )
                row = dict(cursor.fetchone())
            connection.commit()
            return self._queue_metrics_refresh(row, "influencer.status_changed")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_targets(self, month: date) -> dict:
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                        owner.business_owner_id,
                        owner.business_owner_name,
                        COALESCE(target.gmv_target, 0) AS gmv_target,
                        COALESCE(performance.actual_gmv_amount, 0) AS actual_gmv_amount,
                        COALESCE(performance.completion_rate, 0) AS completion_rate,
                        COALESCE(performance.assigned_influencer_count, 0) AS assigned_influencer_count,
                        COALESCE(performance.active_influencer_count, 0) AS active_influencer_count,
                        COALESCE(performance.influencer_100k_plus_count, 0) AS influencer_100k_plus_count,
                        COALESCE(performance.refund_amount, 0) AS refund_amount,
                        target.note
                    FROM dim.dim_business_owner owner
                    LEFT JOIN dim.dim_business_gmv_target_monthly target
                      ON target.business_owner_id = owner.business_owner_id
                     AND target.target_month = %s
                    LEFT JOIN ads.ads_influencer_business_monthly performance
                      ON performance.business_owner_id = owner.business_owner_id
                     AND performance.stat_month = %s
                    WHERE owner.is_active
                    ORDER BY owner.business_owner_name
                    """,
                    (month, month),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        finally:
            connection.close()
        return {"month": month, "rows": rows}

    def save_target(self, payload: dict) -> dict:
        month = parse_month(str(payload.get("target_month") or ""))
        owner_id = int(payload.get("business_owner_id"))
        business_name = (
            self.normalize_business_name(payload.get("business_owner_name"))
            if "business_owner_name" in payload
            else None
        )
        try:
            target = Decimal(str(payload.get("gmv_target", "0"))).quantize(Decimal("0.01"))
        except Exception as exc:
            raise ValueError("GMV目标必须是数字") from exc
        if target < 0:
            raise ValueError("GMV目标不能为负数")
        note = str(payload.get("note") or "").strip() or None

        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT 1 FROM dim.dim_business_owner WHERE business_owner_id = %s AND is_active",
                    (owner_id,),
                )
                if cursor.fetchone() is None:
                    raise ValueError("选择的商务不存在或已停用")
                if business_name is not None:
                    self.update_business_name(cursor, owner_id, business_name)
                cursor.execute(
                    """
                    INSERT INTO dim.dim_business_gmv_target_monthly (
                        target_month, business_owner_id, gmv_target, note
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (target_month, business_owner_id)
                    DO UPDATE SET
                        gmv_target = EXCLUDED.gmv_target,
                        note = EXCLUDED.note,
                        updated_at = NOW()
                    RETURNING target_month, business_owner_id, gmv_target, note
                    """,
                    (month, owner_id, target, note),
                )
                row = dict(cursor.fetchone())
                if business_name is not None:
                    row["business_owner_name"] = business_name
            connection.commit()
            return self._queue_metrics_refresh(row, "target.saved")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


class ApplicationHandler(BaseHTTPRequestHandler):
    server_version = "InfluencerConfig/1.0"

    @property
    def database(self) -> Database:
        return self.server.database  # type: ignore[attr-defined]

    @property
    def product_categories(self) -> ProductCategoryService:
        return self.server.product_categories  # type: ignore[attr-defined]

    @property
    def influencer_master(self) -> InfluencerMasterService:
        return self.server.influencer_master  # type: ignore[attr-defined]

    def log_message(self, format_string: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {format_string % args}")

    def send_json(self, payload, status=HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求内容为空或过大")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON请求格式错误") from exc

    def handle_api_error(self, exc: Exception) -> None:
        explicit_status = getattr(exc, "http_status", None)
        status = HTTPStatus(explicit_status) if explicit_status else (
            HTTPStatus.BAD_REQUEST if isinstance(exc, (ValueError, KeyError)) else HTTPStatus.INTERNAL_SERVER_ERROR
        )
        payload = {"ok": False, "error": str(exc)}
        details = getattr(exc, "details", None)
        if details is not None:
            payload["details"] = details
        self.send_json(payload, status=status)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/health":
                health = self.database.health()
                health.update(self.product_categories.health())
                health.update(self.influencer_master.health())
                self.send_json({"ok": True, "data": health})
                return
            if parsed.path == "/api/refresh-status":
                self.send_json({
                    "ok": True,
                    "data": {
                        "metrics": self.database.refresh_status(),
                        "product_dashboard": self.product_categories.refresh_status(),
                    },
                })
                return
            if parsed.path == "/api/businesses":
                self.send_json({"ok": True, "data": self.database.list_businesses()})
                return
            if parsed.path == "/api/company-influencers":
                query = parse_qs(parsed.query)
                result = self.influencer_master.list_company_influencers(
                    query.get("search", [""])[0],
                    query.get("status", ["all"])[0],
                    int(query.get("page", ["1"])[0]),
                    int(query.get("page_size", ["10"])[0]),
                    query.get("platform", [""])[0],
                )
                self.send_json({"ok": True, "data": result})
                return
            if parsed.path == "/api/influencer-source-accounts":
                query = parse_qs(parsed.query)
                result = self.influencer_master.list_source_accounts(
                    query.get("search", [""])[0],
                    query.get("mapping_status", ["all"])[0],
                    query.get("platform", [""])[0],
                    int(query.get("page", ["1"])[0]),
                    int(query.get("page_size", ["10"])[0]),
                    query.get("gmv_min", [""])[0],
                )
                self.send_json({"ok": True, "data": result})
                return
            if parsed.path == "/api/company-influencer-assignments":
                query = parse_qs(parsed.query)
                month = parse_month(query.get("month", [""])[0])
                owner_value = query.get("business_owner_id", [""])[0].strip()
                result = self.influencer_master.list_assignments(
                    month,
                    query.get("search", [""])[0],
                    int(owner_value) if owner_value else None,
                    int(query.get("page", ["1"])[0]),
                    int(query.get("page_size", ["10"])[0]),
                    query.get("platform", [""])[0],
                )
                self.send_json({"ok": True, "data": result})
                return
            if parsed.path == "/api/influencers":
                query = parse_qs(parsed.query)
                month = parse_month(query.get("month", [""])[0])
                platform = query.get("platform", [""])[0].strip() or None
                owner_value = query.get("business_owner_id", [""])[0].strip()
                owner_id = int(owner_value) if owner_value else None
                status = query.get("status", [""])[0].strip() or None
                active_status = query.get("active_status", [""])[0].strip() or None
                search = query.get("search", [""])[0].strip() or None
                page = int(query.get("page", ["1"])[0])
                page_size = int(query.get("page_size", ["10"])[0])
                result = self.database.list_influencers(
                    month, platform, owner_id, status, search, page, page_size, active_status
                )
                self.send_json({"ok": True, "data": result})
                return
            if parsed.path == "/api/targets":
                query = parse_qs(parsed.query)
                month = parse_month(query.get("month", [""])[0])
                self.send_json({"ok": True, "data": self.database.list_targets(month)})
                return
            if parsed.path == "/api/product-categories":
                self.send_json({"ok": True, "data": self.product_categories.list_categories()})
                return
            if parsed.path == "/api/product-catalog":
                query = parse_qs(parsed.query)
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_catalog(
                        query.get("search", [""])[0],
                        query.get("status", ["all"])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                    ),
                })
                return
            if parsed.path == "/api/product-category-list":
                query = parse_qs(parsed.query)
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_category_page(
                        int(query.get("level", ["1"])[0]),
                        query.get("search", [""])[0],
                        query.get("status", ["all"])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                    ),
                })
                return
            if parsed.path == "/api/products":
                query = parse_qs(parsed.query)
                category_value = query.get("category_id", [""])[0].strip()
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_products(
                        int(category_value) if category_value else None,
                        query.get("search", [""])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                        query.get("status", ["all"])[0],
                    ),
                })
                return
            if parsed.path == "/api/product-mappings":
                query = parse_qs(parsed.query)
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_mappings(
                        query.get("search", [""])[0],
                        query.get("status", ["all"])[0],
                        query.get("platform", [""])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                    ),
                })
                return
            if parsed.path == "/api/product-code-normalizations":
                query = parse_qs(parsed.query)
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_normalization_rules(
                        query.get("search", [""])[0],
                        query.get("status", ["all"])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                    ),
                })
                return
            if parsed.path == "/api/product-source-codes":
                query = parse_qs(parsed.query)
                self.send_json({
                    "ok": True,
                    "data": self.product_categories.list_source_codes(
                        query.get("search", [""])[0],
                        query.get("mapping_status", ["all"])[0],
                        query.get("platform", [""])[0],
                        int(query.get("page", ["1"])[0]),
                        int(query.get("page_size", ["10"])[0]),
                    ),
                })
                return
            product_match = re.fullmatch(r"/api/product-categories/(\d+)/products", parsed.path)
            if product_match:
                query = parse_qs(parsed.query)
                result = self.product_categories.list_products(
                    int(product_match.group(1)),
                    query.get("search", [""])[0],
                    int(query.get("page", ["1"])[0]),
                    int(query.get("page_size", ["10"])[0]),
                )
                self.send_json({"ok": True, "data": result})
                return
            self.serve_static(parsed.path)
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self.handle_api_error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/businesses":
                result = self.database.create_business(payload.get("business_owner_name", ""))
            elif parsed.path == "/api/company-influencers":
                result = self.influencer_master.create_company_influencer(payload)
            elif parsed.path in (
                "/api/influencer-source-mappings",
                "/api/influencer-source-mappings/batch",
            ):
                result = self.influencer_master.save_source_mappings(payload)
            elif parsed.path == "/api/company-influencer-assignments":
                result = self.influencer_master.save_assignment(
                    payload,
                    parse_month(str(payload.get("effective_month") or "")),
                )
            elif parsed.path == "/api/assignments":
                result = self.database.save_assignment(payload)
            elif parsed.path == "/api/influencers/toggle-status":
                result = self.database.toggle_influencer_status(
                    str(payload.get("platform_code") or "").strip(),
                    str(payload.get("influencer_id") or "").strip(),
                    parse_month(str(payload.get("effective_month") or "")),
                    bool(payload.get("is_active")),
                )
            elif parsed.path == "/api/targets":
                result = self.database.save_target(payload)
            elif parsed.path == "/api/product-categories":
                result = self.product_categories.create_category(payload)
            elif parsed.path == "/api/product-catalog":
                result = self.product_categories.create_catalog_row(payload)
            elif parsed.path == "/api/products":
                result = self.product_categories.create_product(payload)
            elif parsed.path == "/api/product-mappings":
                result = self.product_categories.create_mapping(payload)
            elif parsed.path == "/api/product-mappings/batch":
                result = self.product_categories.batch_map_source_codes(payload)
            elif parsed.path == "/api/product-mappings/refresh":
                result = self.product_categories.retry_refresh()
            elif parsed.path == "/api/product-code-normalizations":
                result = self.product_categories.create_normalization_rule(payload)
            else:
                self.send_json({"ok": False, "error": "接口不存在"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json({"ok": True, "data": result})
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self.handle_api_error(exc)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            business_match = re.fullmatch(r"/api/businesses/(\d+)", parsed.path)
            category_match = re.fullmatch(r"/api/product-categories/(\d+)", parsed.path)
            category_status_match = re.fullmatch(r"/api/product-categories/(\d+)/status", parsed.path)
            product_match = re.fullmatch(r"/api/products/([^/]+)", parsed.path)
            product_status_match = re.fullmatch(r"/api/products/([^/]+)/status", parsed.path)
            mapping_match = re.fullmatch(r"/api/product-mappings/(\d+)", parsed.path)
            mapping_status_match = re.fullmatch(r"/api/product-mappings/(\d+)/status", parsed.path)
            normalization_match = re.fullmatch(
                r"/api/product-code-normalizations/(\d+)", parsed.path
            )
            normalization_status_match = re.fullmatch(
                r"/api/product-code-normalizations/(\d+)/status", parsed.path
            )
            company_influencer_match = re.fullmatch(
                r"/api/company-influencers/(\d+)", parsed.path
            )
            company_influencer_status_match = re.fullmatch(
                r"/api/company-influencers/(\d+)/status", parsed.path
            )
            influencer_mapping_status_match = re.fullmatch(
                r"/api/influencer-source-mappings/(\d+)/status", parsed.path
            )
            catalog_match = re.fullmatch(r"/api/product-catalog/(\d+)", parsed.path)
            catalog_status_match = re.fullmatch(r"/api/product-catalog/(\d+)/status", parsed.path)
            if company_influencer_status_match:
                result = self.influencer_master.set_company_influencer_status(
                    int(company_influencer_status_match.group(1)),
                    payload.get("is_active"),
                )
            elif company_influencer_match:
                result = self.influencer_master.update_company_influencer(
                    int(company_influencer_match.group(1)), payload
                )
            elif influencer_mapping_status_match:
                result = self.influencer_master.set_source_mapping_status(
                    int(influencer_mapping_status_match.group(1)),
                    payload.get("is_active"),
                )
            elif business_match:
                result = self.database.update_business(
                    int(business_match.group(1)), payload.get("business_owner_name", "")
                )
            elif category_match:
                result = self.product_categories.update_category(int(category_match.group(1)), payload)
            elif category_status_match:
                result = self.product_categories.set_category_status(
                    int(category_status_match.group(1)), payload.get("is_active")
                )
            elif product_match:
                result = self.product_categories.update_product(unquote(product_match.group(1)), payload)
            elif product_status_match:
                result = self.product_categories.set_product_status(
                    unquote(product_status_match.group(1)), payload.get("is_active")
                )
            elif mapping_match:
                result = self.product_categories.update_mapping(
                    int(mapping_match.group(1)), payload
                )
            elif mapping_status_match:
                result = self.product_categories.set_mapping_status(
                    int(mapping_status_match.group(1)), payload.get("is_active")
                )
            elif normalization_status_match:
                result = self.product_categories.set_normalization_rule_status(
                    int(normalization_status_match.group(1)), payload.get("is_active")
                )
            elif normalization_match:
                result = self.product_categories.update_normalization_rule(
                    int(normalization_match.group(1)), payload
                )
            elif catalog_match:
                result = self.product_categories.update_catalog_row(
                    int(catalog_match.group(1)), payload
                )
            elif catalog_status_match:
                result = self.product_categories.set_catalog_row_status(
                    int(catalog_status_match.group(1)), payload.get("is_active")
                )
            else:
                self.send_json({"ok": False, "error": "接口不存在"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json({"ok": True, "data": result})
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self.handle_api_error(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            business_match = re.fullmatch(r"/api/businesses/(\d+)", parsed.path)
            category_match = re.fullmatch(r"/api/product-categories/(\d+)", parsed.path)
            product_match = re.fullmatch(r"/api/products/([^/]+)", parsed.path)
            mapping_match = re.fullmatch(r"/api/product-mappings/(\d+)", parsed.path)
            normalization_match = re.fullmatch(
                r"/api/product-code-normalizations/(\d+)", parsed.path
            )
            company_influencer_match = re.fullmatch(
                r"/api/company-influencers/(\d+)", parsed.path
            )
            influencer_mapping_match = re.fullmatch(
                r"/api/influencer-source-mappings/(\d+)", parsed.path
            )
            company_assignment_match = re.fullmatch(
                r"/api/company-influencer-assignments/(\d+)/(\d{4}-\d{2})",
                parsed.path,
            )
            catalog_match = re.fullmatch(r"/api/product-catalog/(\d+)", parsed.path)
            if company_influencer_match:
                result = self.influencer_master.delete_company_influencer(
                    int(company_influencer_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if influencer_mapping_match:
                result = self.influencer_master.delete_source_mapping(
                    int(influencer_mapping_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if company_assignment_match:
                result = self.influencer_master.delete_assignment(
                    int(company_assignment_match.group(1)),
                    parse_month(company_assignment_match.group(2)),
                )
                self.send_json({"ok": True, "data": result})
                return
            if business_match:
                result = self.database.delete_business(int(business_match.group(1)))
                self.send_json({"ok": True, "data": result})
                return
            if category_match:
                result = self.product_categories.delete_category(int(category_match.group(1)))
                self.send_json({"ok": True, "data": result})
                return
            if catalog_match:
                result = self.product_categories.delete_catalog_row(
                    int(catalog_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if product_match:
                result = self.product_categories.delete_product(
                    unquote(product_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if mapping_match:
                result = self.product_categories.delete_mapping(
                    int(mapping_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if normalization_match:
                result = self.product_categories.delete_normalization_rule(
                    int(normalization_match.group(1))
                )
                self.send_json({"ok": True, "data": result})
                return
            if parsed.path != "/api/influencers":
                self.send_json({"ok": False, "error": "接口不存在"}, status=HTTPStatus.NOT_FOUND)
                return
            query = parse_qs(parsed.query)
            platform = query.get("platform", [""])[0].strip()
            influencer_id = query.get("influencer_id", [""])[0].strip()
            month = parse_month(query.get("month", [""])[0])
            result = self.database.delete_influencer(platform, influencer_id, month)
            self.send_json({"ok": True, "data": result})
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self.handle_api_error(exc)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            target = STATIC_DIR / "index.html"
        body = target.read_bytes()
        mime_type, _ = mimetypes.guess_type(str(target))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动达人归属与GMV目标配置页。")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default=os.getenv("PGHOST", "192.168.77.111"))
    parser.add_argument("--pg-port", dest="pg_port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--dbname", default=os.getenv("PGDATABASE", "mock_coffice"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "postgres"))
    parser.add_argument("--password", default=os.getenv("PGPASSWORD"))
    parser.add_argument("--migrate", action="store_true", help="启动前执行商品与达人配置迁移")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.port = args.port
    database_args = argparse.Namespace(
        host=args.host,
        port=args.pg_port,
        dbname=args.dbname,
        user=args.user,
        password=args.password,
    )
    database = Database(database_args)
    product_categories = ProductCategoryService(database_args)
    influencer_master = InfluencerMasterService(
        database_args,
        refresh_request=database.request_metrics_refresh,
    )
    if args.migrate:
        print(f"已执行SQL：{product_categories.migrate()}")
        print(f"已执行SQL：{influencer_master.migrate()}")
    server = ThreadingHTTPServer((args.bind, args.port), ApplicationHandler)
    server.database = database  # type: ignore[attr-defined]
    server.product_categories = product_categories  # type: ignore[attr-defined]
    server.influencer_master = influencer_master  # type: ignore[attr-defined]
    print(f"达人配置页：http://{args.bind}:{args.port}")
    print(f"数据库：{args.dbname}@{args.host}:{args.pg_port}")
    print("安全提示：默认仅绑定127.0.0.1，不要在未增加认证时暴露到公网。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        database.close(drain=True, timeout=30)
        product_categories.close(drain=True, timeout=30)
        server.server_close()


if __name__ == "__main__":
    main()
