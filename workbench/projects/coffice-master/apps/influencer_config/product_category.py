"""达播运营商品分类、统一产品和商家编码映射配置服务。"""
from __future__ import annotations

import re
import uuid
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    from .refresh_queue import CoalescingRefreshWorker
except ImportError:  # 兼容直接执行独立达播服务。
    from refresh_queue import CoalescingRefreshWorker

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # 允许无数据库驱动的路由单元测试。
    psycopg2 = None
    RealDictCursor = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:  # Preserve the standalone script entry point.
    sys.path.insert(0, str(PROJECT_ROOT))
from etl.common.product_mapping_workbench import (
    STATE_SQL, CREATE_SQL, lock_product_refresh, publish_workbench,
)

LOGGER = logging.getLogger(__name__)
MIGRATION_FILES = [
    PROJECT_ROOT / "sql/dim/183_dim_influencer_product_category_postgres.sql",
    PROJECT_ROOT / "sql/dim/200_dim_company_product_code_mapping_postgres.sql",
    PROJECT_ROOT / "sql/dim/203_normalize_influencer_product_catalog_postgres.sql",
    PROJECT_ROOT / "sql/dim/204_enforce_product_code_one_to_one_postgres.sql",
    PROJECT_ROOT / "sql/dim/393_dim_product_source_mapping_postgres.sql",
    PROJECT_ROOT / "sql/dim/427_refactor_company_product_identity_postgres.sql",
    PROJECT_ROOT / "sql/dim/304_seed_tmall_shopping_fund_product_postgres.sql",
    PROJECT_ROOT / "sql/dim/306_seed_tmall_preorder_voucher_product_postgres.sql",
    PROJECT_ROOT / "sql/dim/305_seed_red_envelope_product_postgres.sql",
    PROJECT_ROOT / "sql/dim/428_seed_company_product_alias_rules_postgres.sql",
    PROJECT_ROOT / "sql/dim/429_company_product_code_normalization_rules_postgres.sql",
    STATE_SQL,
    CREATE_SQL,
]
DASHBOARD_CREATE_SQL_FILES = [
    PROJECT_ROOT / "sql/douyin/operating_sales/201_dws_douyin_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/wechat_channels/operating_sales/248_dws_wechat_channels_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/jd/operating_sales/251_dws_jd_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/ks/operating_sales/254_dws_ks_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/xhs/operating_sales/257_dws_xhs_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/pdd/operating_sales/260_dws_pdd_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/tmall/operating_sales/300_dws_tmall_operating_sales_product_allocation_postgres.sql",
    PROJECT_ROOT / "sql/common/276_operating_sales_product_allocation_refresh_helper_postgres.sql",
    PROJECT_ROOT / "sql/common/398_operating_sales_product_code_observation_view_postgres.sql",
    PROJECT_ROOT / "sql/ads/operating_sales/160_ads_operating_sales_product_company_shop_daily_postgres.sql",
]
DASHBOARD_PLATFORM_REFRESH = [
    (
        "dwd.dwd_douyin_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/douyin/operating_sales/202_refresh_dws_douyin_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_wechat_channels_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/wechat_channels/operating_sales/263_refresh_dws_wechat_channels_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_jd_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/jd/operating_sales/266_refresh_dws_jd_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_ks_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/ks/operating_sales/269_refresh_dws_ks_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_xhs_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/xhs/operating_sales/272_refresh_dws_xhs_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_pdd_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/pdd/operating_sales/275_refresh_dws_pdd_operating_sales_product_allocation_postgres.sql",
    ),
    (
        "dwd.dwd_tmall_operating_sales_order_item_detail",
        PROJECT_ROOT / "sql/tmall/operating_sales/303_refresh_dws_tmall_operating_sales_product_allocation_postgres.sql",
    ),
]
DASHBOARD_FINAL_REFRESH_SQL_FILES = [
    PROJECT_ROOT / "sql/ads/operating_sales/165_refresh_ads_operating_sales_product_company_shop_daily_postgres.sql",
]
PAGE_SIZES = (10, 20, 50, 100)


class ProductCategoryNotFoundError(ValueError):
    http_status = 404


class ProductCategoryConflictError(ValueError):
    http_status = 409

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details


def _clean_text(value, label: str, max_length: int) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{label}不能为空")
    if len(result) > max_length:
        raise ValueError(f"{label}不能超过{max_length}字")
    return result


def _positive_int(value, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}格式不正确") from exc
    if result <= 0:
        raise ValueError(f"{label}必须大于0")
    return result


class ProductCategoryService:
    """维护一级分类、二级分类、统一产品与商家编码，并同步产品GMV ADS。"""

    def __init__(self, args):
        self.connect_kwargs = {
            "host": args.host,
            "port": args.port,
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        }
        self._dashboard_refresh = CoalescingRefreshWorker(
            "product-dashboard",
            self._refresh_dashboard_now,
            debounce_seconds=0.25,
            pending_check=self._has_pending_refresh,
        )

    def connect(self):
        if psycopg2 is None:
            raise RuntimeError("缺少依赖psycopg2-binary，请先安装requirements.txt")
        return psycopg2.connect(**self.connect_kwargs)

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def configuration_transaction(self):
        # Acquire the domain lock before SELECT FOR UPDATE or dependency reads.
        # Acquiring it only in the write trigger would invert the ETL lock order.
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('mock_coffice_product_mapping_refresh'))")
            yield cursor

    @staticmethod
    def _translate_integrity_error(exc):
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", "")
        messages = {
            "uq_influencer_product_category_l1_name": "一级分类名称已存在",
            "uq_influencer_product_category_l2_parent_name": "该一级分类下已存在同名二级分类",
            "uq_influencer_product_category_name_pair": "该二级分类下已存在同名产品",
            "dim_influencer_product_pkey": "产品ID已存在",
            "uq_company_product_code_pattern": "商家编码已存在",
            "uq_company_product_mapping_platform_code": "该编码表达已存在",
            "uq_company_product_mapping_shop_code": "该编码表达已存在",
            "uq_influencer_product_company_code": "公司商品编码已存在",
            "uq_company_product_alias_rule": "该公司级编码表达规则已存在",
            "uq_company_product_code_normalization_source": "该原始编码组件已存在修正规则",
        }
        raise ProductCategoryConflictError(messages.get(constraint, "配置与现有数据冲突")) from exc

    @staticmethod
    def _new_code(prefix: str) -> str:
        return f"{prefix}{uuid.uuid4().hex.upper()}"

    @staticmethod
    def _new_product_id() -> str:
        return f"PRD-CODE-{uuid.uuid4().hex[:16].upper()}"

    def migrate(self) -> str:
        with self.configuration_transaction() as cursor:
            for sql_file in MIGRATION_FILES:
                cursor.execute(sql_file.read_text(encoding="utf-8"))
        return "、".join(str(path.relative_to(PROJECT_ROOT)) for path in MIGRATION_FILES)

    def health(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT
                    TO_REGCLASS('dim.dim_influencer_product_category') IS NOT NULL
                        AS product_category_ready,
                    TO_REGCLASS('dim.dim_influencer_product') IS NOT NULL AS product_ready,
                    TO_REGCLASS('dim.dim_company_product_code_mapping') IS NOT NULL
                        AS product_mapping_ready
                """
            )
            result = dict(cursor.fetchone())
        result["dashboard_refresh"] = self.refresh_status()
        return result

    def _refresh_dashboard_now(self) -> dict:
        try:
            return self._refresh_dashboard_transaction()
        except Exception as exc:
            # Keep the durable request pending across failure/restart. Do not put
            # connection diagnostics or credentials into a browser-visible error.
            try:
                with self.transaction() as cursor:
                    cursor.execute(
                        "UPDATE ops.product_mapping_refresh_state SET last_error = %s "
                        "WHERE state_key = 'product_mapping' AND requested_revision > completed_revision",
                        (f"商品统计更新失败（{type(exc).__name__}），请重试或检查服务日志",),
                    )
            except Exception:
                LOGGER.warning("Could not persist product refresh failure", exc_info=True)
            raise

    def _has_pending_refresh(self) -> bool:
        with self.transaction() as cursor:
            cursor.execute("SELECT TO_REGCLASS('ops.product_mapping_refresh_state') IS NOT NULL "
                           "AND TO_REGCLASS('ops.refresh_watermark') IS NOT NULL "
                           "AND TO_REGCLASS('ads.ads_product_code_mapping_workbench') IS NOT NULL AS ready")
            if not cursor.fetchone()["ready"]:
                return False
            cursor.execute("SELECT requested_revision > completed_revision AND last_error IS NULL AS pending "
                           "FROM ops.product_mapping_refresh_state WHERE state_key = 'product_mapping'")
            row = cursor.fetchone()
            return bool(row and row["pending"])

    def _refresh_dashboard_transaction(self) -> dict:
        """Refresh the full product dashboard chain in a separate background transaction."""
        refreshed_platforms: list[str] = []
        with self.transaction() as cursor:
            lock_product_refresh(cursor)
            cursor.execute("SELECT requested_revision > completed_revision AS pending "
                           "FROM ops.product_mapping_refresh_state WHERE state_key = 'product_mapping'")
            request = cursor.fetchone()
            if request and not request["pending"]:
                return {"refreshed": False, "reason": "already_published", "platforms": []}
            cursor.execute(
                """
                SELECT
                    TO_REGCLASS('dwd.dwd_douyin_operating_sales_order_item_detail') IS NOT NULL
                        AS source_ready,
                    TO_REGCLASS('dim.dim_platform_shop_company') IS NOT NULL AS shop_dim_ready
                """
            )
            readiness = cursor.fetchone()
            if not readiness["source_ready"] or not readiness["shop_dim_ready"]:
                raise RuntimeError("商品刷新来源尚未就绪")
            # 天猫产品DWS建表脚本会重建目标表；观察视图是可派生对象，必须先移除，
            # 随后由398号SQL在同一事务内恢复，避免后台配置保存后的刷新被依赖阻断。
            cursor.execute(
                "DROP VIEW IF EXISTS common.v_operating_sales_product_code_observation"
            )
            for sql_file in DASHBOARD_CREATE_SQL_FILES:
                cursor.execute(sql_file.read_text(encoding="utf-8"))
            for source_table, sql_file in DASHBOARD_PLATFORM_REFRESH:
                cursor.execute("SELECT TO_REGCLASS(%s) IS NOT NULL AS source_ready", (source_table,))
                if cursor.fetchone()["source_ready"]:
                    cursor.execute(sql_file.read_text(encoding="utf-8"))
                    refreshed_platforms.append(source_table.split(".")[-1])
            for sql_file in DASHBOARD_FINAL_REFRESH_SQL_FILES:
                cursor.execute(sql_file.read_text(encoding="utf-8"))
            cursor.execute(
                "SELECT COUNT(*) AS ads_rows FROM ads.ads_operating_sales_product_company_shop_daily"
            )
            ads_rows = int(cursor.fetchone()["ads_rows"])
            workbench = publish_workbench(cursor)
        return {"refreshed": True, "platforms": refreshed_platforms, "ads_rows": ads_rows,
                "workbench": workbench}

    def _queue_dashboard_refresh(self, result: dict, reason: str) -> dict:
        result["dashboard_refreshed"] = False
        result["dashboard_refresh"] = self._dashboard_refresh.request(reason)
        return result

    def refresh_status(self) -> dict:
        status = self._dashboard_refresh.status()
        with self.transaction() as cursor:
            cursor.execute("SELECT TO_REGCLASS('ops.product_mapping_refresh_state') AS relation")
            if cursor.fetchone()["relation"]:
                cursor.execute("SELECT * FROM ops.product_mapping_refresh_state WHERE state_key = 'product_mapping'")
                row = cursor.fetchone()
                if row:
                    status.update(dict(row))
                    status["pending"] = row["requested_revision"] > row["completed_revision"]
                    status["status"] = ("failed" if row["last_error"] else
                                        "running" if status["running"] else "queued") if status["pending"] else "succeeded"
        return status

    def retry_refresh(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute("UPDATE ops.product_mapping_refresh_state SET last_error = NULL "
                           "WHERE state_key = 'product_mapping'")
        self._dashboard_refresh.request("manual_retry")
        return self.refresh_status()

    def wait_for_refresh(self, timeout: float = 30.0) -> bool:
        return self._dashboard_refresh.wait_until_idle(timeout)

    def close(self, *, drain: bool = True, timeout: float = 30.0) -> bool:
        return self._dashboard_refresh.close(drain=drain, timeout=timeout)

    @staticmethod
    def _validate_page(page: int, page_size: int) -> None:
        if page < 1:
            raise ValueError("页码必须大于0")
        if page_size not in PAGE_SIZES:
            raise ValueError("每页条数仅支持10、20、50或100")

    @staticmethod
    def _category_for_update(cursor, category_id: int) -> dict:
        cursor.execute(
            """
            SELECT category_id, category_name, category_level, parent_category_id,
                   category_code, maintenance_source, is_active, created_at, updated_at
            FROM dim.dim_influencer_product_category
            WHERE category_id = %s
            FOR UPDATE
            """,
            (category_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ProductCategoryNotFoundError("商品分类不存在")
        return dict(row)

    @staticmethod
    def _active_l1(cursor, category_id: int) -> dict:
        cursor.execute(
            """
            SELECT category_id, category_name, is_active
            FROM dim.dim_influencer_product_category
            WHERE category_id = %s AND category_level = 1
            FOR UPDATE
            """,
            (category_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ProductCategoryNotFoundError("一级分类不存在")
        if not row["is_active"]:
            raise ValueError("停用的一级分类不能承接二级分类")
        return dict(row)

    @staticmethod
    def _active_l2(cursor, category_id: int) -> dict:
        cursor.execute(
            """
            SELECT child.category_id, child.category_name, child.is_active,
                   parent.category_id AS parent_category_id,
                   parent.is_active AS parent_is_active
            FROM dim.dim_influencer_product_category child
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_id = child.parent_category_id
             AND parent.category_level = 1
            WHERE child.category_id = %s
              AND child.category_level = 2
            FOR UPDATE OF child, parent
            """,
            (category_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise ProductCategoryNotFoundError("二级分类不存在")
        if not row["is_active"] or not row["parent_is_active"]:
            raise ValueError("停用的分类不能承接产品")
        return dict(row)

    def list_categories(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT
                    c.category_id,
                    c.category_name,
                    c.category_level,
                    c.parent_category_id,
                    parent.category_name AS parent_category_name,
                    c.category_code,
                    c.maintenance_source,
                    c.is_active,
                    c.created_at,
                    c.updated_at,
                    COUNT(child.category_id) FILTER (WHERE c.category_level = 1)
                        AS child_category_count,
                    COUNT(p.product_id) FILTER (WHERE c.category_level = 2)
                        AS product_count
                FROM dim.dim_influencer_product_category c
                LEFT JOIN dim.dim_influencer_product_category parent
                  ON parent.category_id = c.parent_category_id
                LEFT JOIN dim.dim_influencer_product_category child
                  ON child.parent_category_id = c.category_id
                LEFT JOIN dim.dim_influencer_product p
                  ON p.category_id = c.category_id
                GROUP BY c.category_id, parent.category_name
                ORDER BY
                    CASE WHEN c.category_level = 1 THEN c.category_id ELSE c.parent_category_id END,
                    c.category_level,
                    c.category_id
                """
            )
            categories = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE category_level = 1) AS category_l1_total,
                    COUNT(*) FILTER (WHERE category_level = 2) AS category_l2_total,
                    (SELECT COUNT(*) FROM dim.dim_influencer_product) AS product_total,
                    (SELECT COUNT(*) FROM dim.dim_company_product_code_mapping) AS mapping_total,
                    (SELECT COUNT(*) FROM dim.dim_company_product_code_mapping
                     WHERE is_active) AS active_mapping_total
                FROM dim.dim_influencer_product_category
                """
            )
            return {"categories": categories, "summary": dict(cursor.fetchone())}

    def list_products(
        self,
        category_id: int | None,
        search: str | None,
        page: int,
        page_size: int,
        status: str | None = "all",
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        status = (status or "all").strip()
        if status not in ("all", "active", "inactive"):
            raise ValueError("状态仅支持all、active或inactive")
        with self.transaction() as cursor:
            where = ["TRUE"]
            params: list = []
            category = None
            if category_id:
                cursor.execute(
                    """
                    SELECT category_id, category_name, category_level, parent_category_id, is_active
                    FROM dim.dim_influencer_product_category
                    WHERE category_id = %s
                    """,
                    (category_id,),
                )
                category = cursor.fetchone()
                if not category:
                    raise ProductCategoryNotFoundError("商品分类不存在")
                if int(category["category_level"]) == 1:
                    where.append("child.parent_category_id = %s")
                else:
                    where.append("p.category_id = %s")
                params.append(category_id)
            if search:
                where.append(
                    "(p.product_id ILIKE %s OR p.company_product_code ILIKE %s "
                    "OR p.product_name ILIKE %s OR child.category_name ILIKE %s "
                    "OR parent.category_name ILIKE %s)"
                )
                pattern = f"%{search}%"
                params.extend([pattern] * 5)
            if status == "active":
                where.append("p.is_active")
            elif status == "inactive":
                where.append("NOT p.is_active")
            clause = " AND ".join(where)
            from_clause = """
                FROM dim.dim_influencer_product p
                JOIN dim.dim_influencer_product_category child
                  ON child.category_id = p.category_id
                 AND child.category_level = 2
                JOIN dim.dim_influencer_product_category parent
                  ON parent.category_id = child.parent_category_id
                 AND parent.category_level = 1
            """
            cursor.execute(
                f"SELECT COUNT(*) AS total {from_clause} WHERE {clause}", params
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT p.product_id, p.category_id, p.company_product_code,
                       p.product_name, p.product_type, p.maintenance_source,
                       p.is_active, p.created_at, p.updated_at,
                       child.category_name AS category_l2_name,
                       parent.category_id AS category_l1_id,
                       parent.category_name AS category_l1_name,
                       (SELECT COUNT(*)
                        FROM dim.dim_company_product_code_mapping mapping
                        WHERE mapping.product_id = p.product_id) AS mapping_count,
                       (SELECT COUNT(*)
                        FROM dim.dim_company_product_code_mapping mapping
                        WHERE mapping.product_id = p.product_id AND mapping.is_active)
                           AS active_mapping_count,
                       COALESCE(stats.platform_names, '') AS observed_platform_names,
                       COALESCE(stats.shop_count, 0) AS observed_shop_count,
                       COALESCE(stats.paid_unit_count, 0) AS paid_unit_count,
                       COALESCE(stats.gmv_amount, 0) AS gmv_amount
                {from_clause}
                LEFT JOIN LATERAL (
                    SELECT
                        STRING_AGG(DISTINCT platform_name, '、' ORDER BY platform_name)
                            AS platform_names,
                        COUNT(DISTINCT (platform_code, shop_code)) AS shop_count,
                        ROUND(SUM(paid_unit_count), 2) AS paid_unit_count,
                        ROUND(SUM(gmv_amount), 2) AS gmv_amount
                    FROM ads.ads_operating_sales_product_company_shop_daily product_ads
                    WHERE product_ads.product_id = p.product_id
                ) stats ON TRUE
                WHERE {clause}
                ORDER BY p.is_active DESC, p.product_name, p.product_id
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            return {
                "category": dict(category) if category else None,
                "rows": [dict(row) for row in cursor.fetchall()],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": max(1, (total + page_size - 1) // page_size),
                },
            }

    def list_catalog(
        self,
        search: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        status = (status or "all").strip()
        if status not in ("all", "active", "inactive"):
            raise ValueError("状态仅支持all、active或inactive")
        where = ["TRUE"]
        params: list = []
        if search:
            pattern = f"%{search}%"
            where.append(
                """(
                    parent.category_name ILIKE %s
                    OR child.category_name ILIKE %s
                    OR p.product_name ILIKE %s
                    OR p.product_id ILIKE %s
                    OR m.code_pattern ILIKE %s
                )"""
            )
            params.extend([pattern] * 5)
        active_expression = (
            "parent.is_active AND child.is_active AND p.is_active "
            "AND m.is_active"
        )
        if status == "active":
            where.append(active_expression)
        elif status == "inactive":
            where.append(f"NOT ({active_expression})")
        clause = " AND ".join(where)
        from_clause = """
            FROM dim.dim_influencer_product p
            JOIN dim.dim_influencer_product_category child
              ON child.category_id = p.category_id
             AND child.category_level = 2
            JOIN dim.dim_influencer_product_category parent
              ON parent.category_id = child.parent_category_id
             AND parent.category_level = 1
            JOIN dim.dim_company_product_code_mapping m
              ON m.product_id = p.product_id
        """
        with self.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total {from_clause} WHERE {clause}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT
                    parent.category_id AS category_l1_id,
                    parent.category_name AS category_l1_name,
                    child.category_id AS category_l2_id,
                    child.category_name AS category_l2_name,
                    p.product_id,
                    p.product_name,
                    m.mapping_id,
                    m.code_pattern AS merchant_code,
                    m.match_rule,
                    m.code_role,
                    m.mapping_source,
                    parent.is_active AS category_l1_active,
                    child.is_active AS category_l2_active,
                    p.is_active AS product_active,
                    m.is_active AS mapping_active,
                    ({active_expression}) AS row_active,
                    GREATEST(parent.updated_at, child.updated_at, p.updated_at, m.updated_at)
                        AS updated_at
                {from_clause}
                WHERE {clause}
                ORDER BY parent.category_name, child.category_name, p.product_name,
                         m.code_pattern NULLS LAST
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "rows": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def list_category_page(
        self,
        level: int,
        search: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        self._validate_page(page, page_size)
        if level not in (1, 2):
            raise ValueError("分类层级仅支持1或2")
        search = (search or "").strip()
        status = (status or "all").strip()
        if status not in ("all", "active", "inactive"):
            raise ValueError("状态仅支持all、active或inactive")
        where = ["c.category_level = %s"]
        params: list = [level]
        if search:
            pattern = f"%{search}%"
            where.append(
                "(c.category_name ILIKE %s OR COALESCE(parent.category_name, '') ILIKE %s)"
            )
            params.extend([pattern, pattern])
        if status == "active":
            where.append("c.is_active")
        elif status == "inactive":
            where.append("NOT c.is_active")
        clause = " AND ".join(where)
        from_clause = """
            FROM dim.dim_influencer_product_category c
            LEFT JOIN dim.dim_influencer_product_category parent
              ON parent.category_id = c.parent_category_id
        """
        with self.transaction() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS total {from_clause} WHERE {clause}",
                params,
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT
                    c.category_id,
                    c.category_name,
                    c.category_level,
                    c.parent_category_id,
                    parent.category_name AS parent_category_name,
                    c.is_active,
                    CASE
                        WHEN c.category_level = 1 THEN (
                            SELECT COUNT(*)
                            FROM dim.dim_influencer_product_category child
                            WHERE child.parent_category_id = c.category_id
                        )
                        ELSE (
                            SELECT COUNT(*)
                            FROM dim.dim_influencer_product product
                            WHERE product.category_id = c.category_id
                        )
                    END AS related_count,
                    c.updated_at
                {from_clause}
                WHERE {clause}
                ORDER BY c.is_active DESC, c.category_name, c.category_id
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "rows": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    @staticmethod
    def _unclassified_l2(cursor) -> int:
        cursor.execute(
            """
            INSERT INTO dim.dim_influencer_product_category (
                category_name, category_level, category_code,
                maintenance_source, is_active
            )
            VALUES ('未分类', 1, 'CAT-SYSTEM-UNCLASSIFIED-L1', 'manual', TRUE)
            ON CONFLICT (category_code) DO UPDATE
            SET is_active = TRUE, updated_at = NOW()
            RETURNING category_id
            """
        )
        l1_id = int(cursor.fetchone()["category_id"])
        cursor.execute(
            """
            INSERT INTO dim.dim_influencer_product_category (
                category_name, category_level, parent_category_id,
                category_code, maintenance_source, is_active
            )
            VALUES ('未分类', 2, %s, 'CAT-SYSTEM-UNCLASSIFIED-L2', 'manual', TRUE)
            ON CONFLICT (category_code) DO UPDATE
            SET parent_category_id = EXCLUDED.parent_category_id,
                is_active = TRUE,
                updated_at = NOW()
            RETURNING category_id
            """,
            (l1_id,),
        )
        return int(cursor.fetchone()["category_id"])

    def create_catalog_row(self, payload: dict) -> dict:
        product_name = _clean_text(payload.get("product_name"), "产品名称", 255)
        alias_code, _, _, _, _, _ = self._mapping_values(payload)
        category_value = payload.get("category_l2_id") or payload.get("category_id")
        if category_value:
            category_id = _positive_int(category_value, "所属二级分类")
        else:
            with self.configuration_transaction() as cursor:
                category_id = self._unclassified_l2(cursor)
        product = self.create_product({
            "category_id": category_id,
            "company_product_code": alias_code,
            "product_name": product_name,
            "product_type": "merchandise",
        })
        with self.configuration_transaction() as cursor:
            cursor.execute(
                """
                SELECT * FROM dim.dim_company_product_code_mapping
                WHERE product_id = %s AND mapping_kind = 'company_code'
                """,
                (product["product_id"],),
            )
            return dict(cursor.fetchone())

    def update_catalog_row(self, mapping_id: int, payload: dict) -> dict:
        product_name = _clean_text(payload.get("product_name"), "产品名称", 255)
        category_l1_id = _positive_int(payload.get("category_l1_id"), "一级分类")
        category_l2_id = _positive_int(payload.get("category_l2_id"), "二级分类")
        alias_code, _, _, _, _, _ = self._mapping_values(payload)
        with self.configuration_transaction() as cursor:
            l2 = self._active_l2(cursor, category_l2_id)
            if int(l2["parent_category_id"]) != category_l1_id:
                raise ValueError("二级分类不属于所选一级分类")
            cursor.execute(
                """
                SELECT mapping.product_id, product.product_type
                FROM dim.dim_company_product_code_mapping mapping
                JOIN dim.dim_influencer_product product
                  ON product.product_id = mapping.product_id
                WHERE mapping.mapping_id = %s
                """,
                (mapping_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise ProductCategoryNotFoundError("商品配置不存在")
        self.update_product(current["product_id"], {
            "category_id": category_l2_id,
            "company_product_code": alias_code,
            "product_name": product_name,
            "product_type": current["product_type"],
        })
        with self.configuration_transaction() as cursor:
            cursor.execute(
                """
                SELECT * FROM dim.dim_company_product_code_mapping
                WHERE product_id = %s AND mapping_kind = 'company_code'
                """,
                (current["product_id"],),
            )
            return dict(cursor.fetchone())

    def set_catalog_row_status(self, mapping_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("商品状态必须为布尔值")
        with self.configuration_transaction() as cursor:
            cursor.execute(
                """
                SELECT m.product_id, p.category_id
                FROM dim.dim_company_product_code_mapping m
                JOIN dim.dim_influencer_product p ON p.product_id = m.product_id
                WHERE m.mapping_id = %s
                FOR UPDATE OF m, p
                """,
                (mapping_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise ProductCategoryNotFoundError("商品配置不存在")
        self.set_product_status(current["product_id"], is_active)
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT * FROM dim.dim_company_product_code_mapping WHERE mapping_id = %s",
                (mapping_id,),
            )
            return dict(cursor.fetchone())

    def delete_catalog_row(self, mapping_id: int) -> dict:
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT product_id, code_pattern FROM dim.dim_company_product_code_mapping WHERE mapping_id = %s",
                (mapping_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("商品配置不存在")
            result = dict(row)
        self.delete_product(result["product_id"])
        return result

    def create_category(self, payload: dict) -> dict:
        name = _clean_text(payload.get("category_name"), "分类名称", 128)
        level = _positive_int(payload.get("category_level"), "分类层级")
        if level not in (1, 2):
            raise ValueError("分类层级仅支持1或2")
        parent_id = None
        try:
            with self.configuration_transaction() as cursor:
                if level == 2:
                    parent_id = _positive_int(payload.get("parent_category_id"), "所属一级分类")
                    self._active_l1(cursor, parent_id)
                cursor.execute(
                    """
                    INSERT INTO dim.dim_influencer_product_category (
                        category_name, category_level, parent_category_id,
                        category_code, maintenance_source
                    )
                    VALUES (%s, %s, %s, %s, 'manual')
                    RETURNING *
                    """,
                    (name, level, parent_id, self._new_code(f"CAT-MANUAL-L{level}-")),
                )
                row = dict(cursor.fetchone())
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(row, "category.created")

    def update_category(self, category_id: int, payload: dict) -> dict:
        name = _clean_text(payload.get("category_name"), "分类名称", 128)
        try:
            with self.configuration_transaction() as cursor:
                current = self._category_for_update(cursor, category_id)
                parent_id = current["parent_category_id"]
                if current["category_level"] == 2 and payload.get("parent_category_id") is not None:
                    parent_id = _positive_int(payload.get("parent_category_id"), "所属一级分类")
                    self._active_l1(cursor, parent_id)
                cursor.execute(
                    """
                    UPDATE dim.dim_influencer_product_category
                    SET category_name = %s,
                        parent_category_id = %s,
                        maintenance_source = 'manual',
                        updated_at = NOW()
                    WHERE category_id = %s
                    RETURNING *
                    """,
                    (name, parent_id, category_id),
                )
                row = dict(cursor.fetchone())
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(row, "category.updated")

    def set_category_status(self, category_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("分类状态必须为布尔值")
        with self.configuration_transaction() as cursor:
            current = self._category_for_update(cursor, category_id)
            if not is_active:
                if current["category_level"] == 1:
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM dim.dim_influencer_product_category
                        WHERE parent_category_id = %s AND is_active
                        """,
                        (category_id,),
                    )
                    dependencies = int(cursor.fetchone()["total"])
                    if dependencies:
                        raise ProductCategoryConflictError(
                            f"该一级分类下还有{dependencies}个启用的二级分类，请先停用它们"
                        )
                else:
                    cursor.execute(
                        "SELECT COUNT(*) AS total FROM dim.dim_influencer_product WHERE category_id = %s AND is_active",
                        (category_id,),
                    )
                    dependencies = int(cursor.fetchone()["total"])
                    if dependencies:
                        raise ProductCategoryConflictError(
                            f"该二级分类下还有{dependencies}个启用产品，请先停用它们"
                        )
            elif current["category_level"] == 2:
                self._active_l1(cursor, int(current["parent_category_id"]))
            cursor.execute(
                """
                UPDATE dim.dim_influencer_product_category
                SET is_active = %s, maintenance_source = 'manual', updated_at = NOW()
                WHERE category_id = %s
                RETURNING *
                """,
                (is_active, category_id),
            )
            row = dict(cursor.fetchone())
        return self._queue_dashboard_refresh(row, "category.status_changed")

    def delete_category(self, category_id: int) -> dict:
        with self.configuration_transaction() as cursor:
            current = self._category_for_update(cursor, category_id)
            if current["category_level"] == 1:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM dim.dim_influencer_product_category
                    WHERE parent_category_id = %s
                    """,
                    (category_id,),
                )
                dependency_label = "二级分类"
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM dim.dim_influencer_product
                    WHERE category_id = %s
                    """,
                    (category_id,),
                )
                dependency_label = "产品"
            dependencies = int(cursor.fetchone()["total"])
            if dependencies:
                raise ProductCategoryConflictError(
                    f"该分类下还有{dependencies}个{dependency_label}，不能删除"
                )
            cursor.execute(
                """
                DELETE FROM dim.dim_influencer_product_category
                WHERE category_id = %s
                RETURNING *
                """,
                (category_id,),
            )
            row = dict(cursor.fetchone())
        return self._queue_dashboard_refresh(row, "category.deleted")

    @staticmethod
    def _insert_primary_product_rule(
        cursor, product_id: str, company_product_code: str, quantity_position: str
    ) -> None:
        cursor.execute(
            """
            INSERT INTO dim.dim_company_product_code_mapping (
                product_id, platform_code, shop_code, source_product_code,
                code_pattern, code_prefix, match_rule, code_role,
                mapping_source, is_active, alias_code,
                quantity_position, mapping_kind
            ) VALUES (
                %s, '*', NULL, %s,
                CASE
                    WHEN %s = 'suffix' THEN %s || '-X'
                    WHEN %s = 'prefix' THEN 'X' || %s
                    ELSE %s
                END,
                CASE WHEN %s = 'suffix' THEN %s || '-' ELSE NULL END,
                CASE
                    WHEN %s = 'suffix' THEN 'suffix_quantity'
                    WHEN %s = 'prefix' THEN 'prefix_quantity'
                    ELSE 'exact'
                END,
                'box', 'manual', TRUE, %s, %s, 'company_code'
            )
            """,
            (
                product_id, company_product_code,
                quantity_position, company_product_code,
                quantity_position, company_product_code, company_product_code,
                quantity_position, company_product_code,
                quantity_position, quantity_position,
                company_product_code, quantity_position,
            ),
        )

    def create_product(self, payload: dict) -> dict:
        product_name = _clean_text(payload.get("product_name"), "产品名称", 255)
        company_product_code = _clean_text(
            payload.get("company_product_code"), "公司商品编码", 128
        ).upper()
        category_id = _positive_int(payload.get("category_id"), "所属二级分类")
        product_type = str(payload.get("product_type") or "merchandise").strip()
        if product_type not in ("merchandise", "non_product", "promotion"):
            raise ValueError("商品类型无效")
        product_id = self._new_product_id()
        quantity_position = "none" if product_type == "non_product" else "suffix"
        try:
            with self.configuration_transaction() as cursor:
                self._active_l2(cursor, category_id)
                cursor.execute(
                    """
                    INSERT INTO dim.dim_influencer_product (
                        product_id, category_id, company_product_code,
                        product_name, product_type, maintenance_source
                    )
                    VALUES (%s, %s, %s, %s, %s, 'manual')
                    RETURNING *
                    """,
                    (
                        product_id, category_id, company_product_code,
                        product_name, product_type,
                    ),
                )
                row = dict(cursor.fetchone())
                self._insert_primary_product_rule(
                    cursor, product_id, company_product_code, quantity_position
                )
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(row, "product.created")

    def update_product(self, product_id: str, payload: dict) -> dict:
        product_id = _clean_text(product_id, "产品ID", 128)
        product_name = _clean_text(payload.get("product_name"), "产品名称", 255)
        company_product_code = _clean_text(
            payload.get("company_product_code"), "公司商品编码", 128
        ).upper()
        category_id = _positive_int(payload.get("category_id"), "所属二级分类")
        product_type = str(payload.get("product_type") or "merchandise").strip()
        if product_type not in ("merchandise", "non_product", "promotion"):
            raise ValueError("商品类型无效")
        quantity_position = "none" if product_type == "non_product" else "suffix"
        try:
            with self.configuration_transaction() as cursor:
                self._active_l2(cursor, category_id)
                cursor.execute(
                    """
                    SELECT company_product_code, product_type
                    FROM dim.dim_influencer_product
                    WHERE product_id = %s
                    FOR UPDATE
                    """,
                    (product_id,),
                )
                current = cursor.fetchone()
                if not current:
                    raise ProductCategoryNotFoundError("产品不存在")
                previous_company_product_code = current["company_product_code"]
                previous_quantity_position = (
                    "none" if current["product_type"] == "non_product" else "suffix"
                )
                cursor.execute(
                    """
                    UPDATE dim.dim_influencer_product
                    SET category_id = %s,
                        company_product_code = %s,
                        product_name = %s,
                        product_type = %s,
                        maintenance_source = 'manual',
                        updated_at = NOW()
                    WHERE product_id = %s
                    RETURNING *
                    """,
                    (
                        category_id, company_product_code, product_name,
                        product_type, product_id,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    raise ProductCategoryNotFoundError("产品不存在")
                result = dict(row)
                if (
                    previous_company_product_code != company_product_code
                    or previous_quantity_position != quantity_position
                ):
                    cursor.execute(
                        """
                        UPDATE dim.dim_company_product_code_mapping
                        SET mapping_kind = 'alias', mapping_source = 'manual',
                            updated_at = NOW()
                        WHERE product_id = %s AND mapping_kind = 'company_code'
                        """,
                        (product_id,),
                    )
                    cursor.execute(
                        """
                        SELECT mapping_id, product_id
                        FROM dim.dim_company_product_code_mapping
                        WHERE UPPER(BTRIM(alias_code)) = UPPER(BTRIM(%s))
                          AND quantity_position = %s
                        FOR UPDATE
                        """,
                        (company_product_code, quantity_position),
                    )
                    primary_rule = cursor.fetchone()
                    if primary_rule and primary_rule["product_id"] != product_id:
                        raise ProductCategoryConflictError(
                            "公司商品编码已被其他商品作为编码表达使用"
                        )
                    if primary_rule:
                        cursor.execute(
                            """
                            UPDATE dim.dim_company_product_code_mapping
                            SET mapping_kind = 'company_code', is_active = TRUE,
                                mapping_source = 'manual', updated_at = NOW()
                            WHERE mapping_id = %s
                            """,
                            (primary_rule["mapping_id"],),
                        )
                    else:
                        self._insert_primary_product_rule(
                            cursor, product_id, company_product_code, quantity_position
                        )
                else:
                    cursor.execute(
                        """
                        UPDATE dim.dim_company_product_code_mapping
                        SET is_active = TRUE, mapping_source = 'manual', updated_at = NOW()
                        WHERE product_id = %s AND mapping_kind = 'company_code'
                        """,
                        (product_id,),
                    )
                    if cursor.rowcount == 0:
                        self._insert_primary_product_rule(
                            cursor, product_id, company_product_code, quantity_position
                        )
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(result, "product.updated")

    def set_product_status(self, product_id: str, is_active: bool) -> dict:
        product_id = _clean_text(product_id, "产品ID", 128)
        if not isinstance(is_active, bool):
            raise ValueError("产品状态必须为布尔值")
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT category_id FROM dim.dim_influencer_product WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise ProductCategoryNotFoundError("产品不存在")
            if is_active:
                self._active_l2(cursor, int(current["category_id"]))
            cursor.execute(
                """
                UPDATE dim.dim_influencer_product
                SET is_active = %s, maintenance_source = 'manual', updated_at = NOW()
                WHERE product_id = %s
                RETURNING *
                """,
                (is_active, product_id),
            )
            row = dict(cursor.fetchone())
        return self._queue_dashboard_refresh(row, "product.status_changed")

    @staticmethod
    def _mapping_values(payload: dict) -> tuple[str, str, str | None, str, str, str]:
        alias_code = _clean_text(
            payload.get("source_product_code") or payload.get("code_pattern"),
            "编码表达",
            128,
        ).upper()
        quantity_position = str(payload.get("quantity_position") or "").strip()
        legacy_rule = str(payload.get("match_rule") or "").strip()
        if not quantity_position:
            quantity_position = {
                "suffix_quantity": "suffix",
                "prefix_quantity": "prefix",
                "exact": "none",
            }.get(legacy_rule, "suffix")
        if quantity_position not in ("suffix", "prefix", "none"):
            raise ValueError("数量位置仅支持suffix、prefix或none")
        if alias_code.endswith("-X"):
            alias_code = alias_code[:-2]
            quantity_position = "suffix"
        elif quantity_position == "prefix" and alias_code.startswith("X"):
            alias_code = alias_code[1:]
        elif re.fullmatch(r"[1-9][0-9]*[A-Z][A-Z0-9-]*", alias_code):
            alias_code = re.sub(r"^[1-9][0-9]*", "", alias_code)
            quantity_position = "prefix"
        elif re.fullmatch(r".+-[1-9][0-9]*", alias_code):
            alias_code = re.sub(r"-[1-9][0-9]*$", "", alias_code)
            quantity_position = "suffix"
        if not alias_code:
            raise ValueError("编码表达不能为空")
        code_pattern = (
            f"{alias_code}-X" if quantity_position == "suffix"
            else f"X{alias_code}" if quantity_position == "prefix"
            else alias_code
        )
        code_prefix = f"{alias_code}-" if quantity_position == "suffix" else None
        match_rule = {
            "suffix": "suffix_quantity",
            "prefix": "prefix_quantity",
            "none": "exact",
        }[quantity_position]
        code_role = str(payload.get("code_role") or "box").strip()
        if code_role not in ("box", "sachet"):
            raise ValueError("包装角色仅支持box或sachet")
        return alias_code, code_pattern, code_prefix, match_rule, code_role, quantity_position

    def create_mapping(self, payload: dict) -> dict:
        product_id = _clean_text(payload.get("product_id"), "产品", 128)
        (
            alias_code, code_pattern, code_prefix, match_rule,
            code_role, quantity_position,
        ) = self._mapping_values(payload)
        try:
            with self.configuration_transaction() as cursor:
                cursor.execute(
                    "SELECT is_active FROM dim.dim_influencer_product WHERE product_id = %s FOR UPDATE",
                    (product_id,),
                )
                product = cursor.fetchone()
                if not product:
                    raise ProductCategoryNotFoundError("产品不存在")
                if not product["is_active"]:
                    raise ValueError("停用产品不能新增商家编码")
                cursor.execute(
                    """
                    INSERT INTO dim.dim_company_product_code_mapping (
                        product_id, platform_code, shop_code, source_product_code,
                        code_pattern, code_prefix, match_rule,
                        code_role, mapping_source, alias_code,
                        quantity_position, mapping_kind
                    )
                    VALUES (%s, '*', NULL, %s, %s, %s, %s, %s, 'manual',
                            %s, %s, 'alias')
                    RETURNING *
                    """,
                    (
                        product_id, alias_code, code_pattern,
                        code_prefix, match_rule, code_role,
                        alias_code, quantity_position,
                    ),
                )
                row = dict(cursor.fetchone())
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(row, "mapping.created")

    def update_mapping(self, mapping_id: int, payload: dict) -> dict:
        product_id = _clean_text(payload.get("product_id"), "产品", 128)
        (
            alias_code, code_pattern, code_prefix, match_rule,
            code_role, quantity_position,
        ) = self._mapping_values(payload)
        try:
            with self.configuration_transaction() as cursor:
                cursor.execute(
                    "SELECT mapping_kind FROM dim.dim_company_product_code_mapping WHERE mapping_id = %s FOR UPDATE",
                    (mapping_id,),
                )
                existing = cursor.fetchone()
                if existing and existing["mapping_kind"] == "company_code":
                    raise ProductCategoryConflictError(
                        "公司商品编码规则请在公司商品页面修改"
                    )
                cursor.execute(
                    "SELECT product_id FROM dim.dim_influencer_product WHERE product_id = %s",
                    (product_id,),
                )
                if not cursor.fetchone():
                    raise ProductCategoryNotFoundError("产品不存在")
                cursor.execute(
                    """
                    UPDATE dim.dim_company_product_code_mapping
                    SET product_id = %s,
                        source_product_code = %s,
                        alias_code = %s,
                        quantity_position = %s,
                        code_pattern = %s,
                        code_prefix = %s,
                        match_rule = %s,
                        code_role = %s,
                        mapping_source = 'manual',
                        updated_at = NOW()
                    WHERE mapping_id = %s
                    RETURNING *
                    """,
                    (
                        product_id, alias_code, alias_code, quantity_position,
                        code_pattern, code_prefix, match_rule, code_role, mapping_id,
                    ),
                )
                row = cursor.fetchone()
                if not row:
                    raise ProductCategoryNotFoundError("商家编码映射不存在")
                result = dict(row)
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(result, "mapping.updated")

    def _list_mapping_workbench(
        self,
        search: str | None,
        mapping_status: str | None,
        platform_code: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        mapping_status = (mapping_status or "all").strip()
        mapping_status = {"active": "mapped"}.get(mapping_status, mapping_status)
        if mapping_status not in ("all", "mapped", "unmapped", "inactive"):
            raise ValueError("映射状态仅支持all、mapped、unmapped或inactive")
        platform_code = (platform_code or "").strip().lower()
        where = ["TRUE"]
        params: list = []
        if search:
            pattern = f"%{search}%"
            where.append(
                "(workbench.source_product_code ILIKE %s "
                "OR COALESCE(workbench.company_product_code, '') ILIKE %s "
                "OR COALESCE(workbench.product_name, '') ILIKE %s "
                "OR COALESCE(ARRAY_TO_STRING(workbench.observed_source_codes, ','), '') ILIKE %s)"
            )
            params.extend([pattern] * 4)
        if platform_code:
            where.append(
                "%s = ANY(COALESCE(workbench.observed_platform_codes, ARRAY[]::TEXT[]))"
            )
            params.append(platform_code)
        if mapping_status != "all":
            where.append("workbench.mapping_status = %s")
            params.append(mapping_status)
        clause = " AND ".join(where)
        with self.transaction() as cursor:
            cursor.execute(
                f"""
                WITH workbench AS MATERIALIZED (
                    SELECT
                        observation.*,
                        observation.current_product_id AS product_id,
                        observation.product_category_l2 AS category_l2_name,
                        observation.large_product_category AS category_l1_name,
                        (observation.mapping_status = 'mapped') AS is_active
                    FROM ads.ads_product_code_mapping_workbench observation
                    WHERE observation.snapshot_id = (
                        SELECT (summary->>'snapshot_id')::UUID
                        FROM ops.refresh_watermark WHERE watermark_key = 'product_code_mapping'
                    )
                ), filtered AS MATERIALIZED (
                    SELECT * FROM workbench WHERE {clause}
                ), page_rows AS (
                    SELECT
                        filtered.*,
                        ROW_NUMBER() OVER (
                            ORDER BY
                                CASE filtered.mapping_status
                                    WHEN 'unmapped' THEN 0
                                    WHEN 'inactive' THEN 1
                                    ELSE 2
                                END,
                                filtered.gmv_amount DESC,
                                filtered.source_product_code,
                                filtered.quantity_position
                        ) AS page_order
                    FROM filtered
                    ORDER BY
                        CASE filtered.mapping_status
                            WHEN 'unmapped' THEN 0
                            WHEN 'inactive' THEN 1
                            ELSE 2
                        END,
                        filtered.gmv_amount DESC,
                        filtered.source_product_code,
                        filtered.quantity_position
                    LIMIT %s OFFSET %s
                ), counts AS (
                    SELECT
                        (SELECT COUNT(*) FROM filtered) AS total,
                        (SELECT COUNT(*) FROM workbench WHERE mapping_status = 'unmapped')
                            AS unmapped_total
                )
                SELECT
                    counts.total,
                    counts.unmapped_total,
                    COALESCE(
                        JSONB_AGG(TO_JSONB(page_rows) - 'page_order' - 'snapshot_id' - 'row_key' - 'generated_at'
                                  ORDER BY page_rows.page_order)
                            FILTER (WHERE page_rows.page_order IS NOT NULL),
                        '[]'::JSONB
                    ) AS rows,
                    (SELECT JSONB_BUILD_OBJECT(
                        'snapshot_id', watermark.summary->>'snapshot_id',
                        'generated_at', watermark.last_success_at,
                        'pending', state.requested_revision > state.completed_revision,
                        'error', state.last_error)
                     FROM ops.product_mapping_refresh_state state
                     LEFT JOIN ops.refresh_watermark watermark ON watermark.watermark_key = 'product_code_mapping'
                     WHERE state.state_key = 'product_mapping') AS snapshot
                FROM counts
                LEFT JOIN page_rows ON TRUE
                GROUP BY counts.total, counts.unmapped_total
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            result = cursor.fetchone()
            total = int(result["total"])
            unmapped_total = int(result["unmapped_total"])
            rows = list(result["rows"])
            snapshot = result["snapshot"]
        return {
            "rows": rows,
            "snapshot": snapshot,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "unmapped_total": unmapped_total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def list_mappings(
        self,
        search: str | None,
        status: str | None,
        platform_code: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        return self._list_mapping_workbench(
            search, status, platform_code, page, page_size
        )

    def list_source_codes(
        self,
        search: str | None,
        mapping_status: str | None,
        platform_code: str | None,
        page: int,
        page_size: int,
    ) -> dict:
        return self._list_mapping_workbench(
            search, mapping_status, platform_code, page, page_size
        )

    def batch_map_source_codes(self, payload: dict) -> dict:
        product_id = _clean_text(payload.get("product_id"), "公司商品", 128)
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise ValueError("请选择至少一条编码表达")
        if len(items) > 500:
            raise ValueError("单次最多映射500条编码")
        confirm_replace = payload.get("confirm_replace") is True
        normalized = [self._mapping_values(item) for item in items]
        conflicts: list[dict] = []
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT is_active FROM dim.dim_influencer_product WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            product = cursor.fetchone()
            if not product or not product["is_active"]:
                raise ProductCategoryNotFoundError("公司商品不存在或已停用")
            for alias_code, _, _, _, _, quantity_position in normalized:
                cursor.execute(
                    """
                    SELECT mapping_id, product_id, mapping_kind
                    FROM dim.dim_company_product_code_mapping
                    WHERE UPPER(BTRIM(alias_code)) = UPPER(BTRIM(%s))
                      AND quantity_position = %s
                    FOR UPDATE
                    """,
                    (alias_code, quantity_position),
                )
                current = cursor.fetchone()
                if current and current["mapping_kind"] == "company_code" and current["product_id"] != product_id:
                    raise ProductCategoryConflictError(
                        "公司商品编码规则不能改配到其他商品"
                    )
                if current and current["product_id"] != product_id:
                    conflicts.append({
                        "source_product_code": alias_code,
                        "quantity_position": quantity_position,
                        "current_product_id": current["product_id"],
                    })
            if conflicts and not confirm_replace:
                raise ProductCategoryConflictError(
                    "部分编码表达已归属其他公司商品，请确认后再替换",
                    {"conflicts": conflicts},
                )
            created = updated = 0
            for (
                alias_code, code_pattern, code_prefix, match_rule,
                code_role, quantity_position,
            ) in normalized:
                cursor.execute(
                    """
                    SELECT mapping_id, mapping_kind
                    FROM dim.dim_company_product_code_mapping
                    WHERE UPPER(BTRIM(alias_code)) = UPPER(BTRIM(%s))
                      AND quantity_position = %s
                    FOR UPDATE
                    """,
                    (alias_code, quantity_position),
                )
                current = cursor.fetchone()
                if current:
                    cursor.execute(
                        """
                        UPDATE dim.dim_company_product_code_mapping
                        SET product_id = %s, source_product_code = %s,
                            code_pattern = %s, code_prefix = %s,
                            match_rule = %s, code_role = %s,
                            mapping_source = 'manual', is_active = TRUE,
                            updated_at = NOW()
                        WHERE mapping_id = %s
                        """,
                        (
                            product_id, alias_code, code_pattern, code_prefix,
                            match_rule, code_role, current["mapping_id"],
                        ),
                    )
                    updated += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO dim.dim_company_product_code_mapping (
                            product_id, platform_code, shop_code,
                            source_product_code, code_pattern, code_prefix,
                            match_rule, code_role, mapping_source, is_active,
                            alias_code, quantity_position, mapping_kind
                        ) VALUES (
                            %s, '*', NULL, %s, %s, %s, %s, %s,
                            'manual', TRUE, %s, %s, 'alias'
                        )
                        """,
                        (
                            product_id, alias_code, code_pattern, code_prefix,
                            match_rule, code_role, alias_code, quantity_position,
                        ),
                    )
                    created += 1
        return self._queue_dashboard_refresh(
            {"created": created, "updated": updated,
             "conflicts_replaced": len(conflicts)},
            "mapping.batch_saved",
        )

    def delete_mapping(self, mapping_id: int) -> dict:
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT mapping_kind FROM dim.dim_company_product_code_mapping WHERE mapping_id = %s FOR UPDATE",
                (mapping_id,),
            )
            current = cursor.fetchone()
            if current and current["mapping_kind"] == "company_code":
                raise ProductCategoryConflictError(
                    "公司商品编码规则不能删除，请在公司商品页面修改编码"
                )
            cursor.execute(
                """
                DELETE FROM dim.dim_company_product_code_mapping
                WHERE mapping_id = %s
                RETURNING mapping_id, platform_code, shop_code,
                          source_product_code, product_id
                """,
                (mapping_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("商品编码映射不存在")
            result = dict(row)
        return self._queue_dashboard_refresh(result, "mapping.deleted")

    def delete_product(self, product_id: str) -> dict:
        product_id = _clean_text(product_id, "产品ID", 128)
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT TO_REGCLASS('common.v_operating_sales_product_code_observation') AS view_name"
            )
            observed_components = 0
            if cursor.fetchone()["view_name"] is not None:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(component_row_count), 0) AS total
                    FROM common.v_operating_sales_product_code_observation
                    WHERE current_product_id = %s
                    """,
                    (product_id,),
                )
                observed_components = int(cursor.fetchone()["total"])
            if observed_components:
                raise ProductCategoryConflictError(
                    f"该公司商品已有{observed_components}条订单组件引用，请停用而不要删除"
                )
            cursor.execute(
                "DELETE FROM dim.dim_company_product_code_mapping WHERE product_id = %s",
                (product_id,),
            )
            cursor.execute(
                "DELETE FROM dim.dim_influencer_product WHERE product_id = %s RETURNING *",
                (product_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("公司商品不存在")
            result = dict(row)
        return self._queue_dashboard_refresh(result, "product.deleted")

    def set_mapping_status(self, mapping_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("商家编码状态必须为布尔值")
        with self.configuration_transaction() as cursor:
            cursor.execute(
                "SELECT mapping_kind FROM dim.dim_company_product_code_mapping WHERE mapping_id = %s FOR UPDATE",
                (mapping_id,),
            )
            current = cursor.fetchone()
            if current and current["mapping_kind"] == "company_code" and not is_active:
                raise ProductCategoryConflictError(
                    "公司商品编码规则不能单独停用，请停用公司商品"
                )
            cursor.execute(
                """
                UPDATE dim.dim_company_product_code_mapping
                SET is_active = %s, mapping_source = 'manual', updated_at = NOW()
                WHERE mapping_id = %s
                RETURNING *
                """,
                (is_active, mapping_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("商家编码映射不存在")
            result = dict(row)
        return self._queue_dashboard_refresh(result, "mapping.status_changed")

    @staticmethod
    def _normalization_values(payload: dict) -> tuple[str, str, str | None]:
        source = _clean_text(
            payload.get("source_code_component"), "原始编码组件", 512
        ).upper().replace("＋", "+")
        if "+" in source:
            raise ValueError("原始编码组件不能包含加号，请只填写漏分隔的单个组件")
        normalized = _clean_text(
            payload.get("normalized_code_expression"), "修正后编码", 1024
        ).upper().replace("＋", "+")
        parts = [part.strip() for part in normalized.split("+")]
        if any(not part for part in parts):
            raise ValueError("修正后编码的加号两侧都必须有商品组件")
        if any(len(part) > 128 for part in parts):
            raise ValueError("修正后的单个商品组件不能超过128字")
        note = str(payload.get("note") or "").strip() or None
        if note and len(note) > 500:
            raise ValueError("规则说明不能超过500字")
        return source, "+".join(parts), note

    def list_normalization_rules(
        self, search: str | None, status: str | None, page: int, page_size: int
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        status = (status or "all").strip()
        if status not in ("all", "active", "inactive"):
            raise ValueError("修正规则状态仅支持all、active或inactive")
        where = ["TRUE"]
        params: list = []
        if search:
            pattern = f"%{search}%"
            where.append(
                "(source_code_component ILIKE %s "
                "OR normalized_code_expression ILIKE %s "
                "OR COALESCE(note, '') ILIKE %s)"
            )
            params.extend([pattern, pattern, pattern])
        if status != "all":
            where.append("is_active = %s")
            params.append(status == "active")
        clause = " AND ".join(where)
        with self.transaction() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM dim.dim_company_product_code_normalization_rule
                WHERE {clause}
                """,
                params,
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT *
                FROM dim.dim_company_product_code_normalization_rule
                WHERE {clause}
                ORDER BY is_active DESC, updated_at DESC, normalization_rule_id DESC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "rows": rows,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def create_normalization_rule(self, payload: dict) -> dict:
        source, normalized, note = self._normalization_values(payload)
        try:
            with self.configuration_transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_company_product_code_normalization_rule (
                        source_code_component, normalized_code_expression, note
                    ) VALUES (%s, %s, %s)
                    RETURNING *
                    """,
                    (source, normalized, note),
                )
                row = dict(cursor.fetchone())
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(row, "normalization.created")

    def update_normalization_rule(self, rule_id: int, payload: dict) -> dict:
        source, normalized, note = self._normalization_values(payload)
        try:
            with self.configuration_transaction() as cursor:
                cursor.execute(
                    """
                    UPDATE dim.dim_company_product_code_normalization_rule
                    SET source_code_component = %s,
                        normalized_code_expression = %s,
                        note = %s,
                        updated_at = NOW()
                    WHERE normalization_rule_id = %s
                    RETURNING *
                    """,
                    (source, normalized, note, rule_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise ProductCategoryNotFoundError("编码修正规则不存在")
                result = dict(row)
        except Exception as exc:
            if getattr(exc, "pgcode", None) == "23505":
                self._translate_integrity_error(exc)
            raise
        return self._queue_dashboard_refresh(result, "normalization.updated")

    def set_normalization_rule_status(self, rule_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("修正规则状态必须为布尔值")
        with self.configuration_transaction() as cursor:
            cursor.execute(
                """
                UPDATE dim.dim_company_product_code_normalization_rule
                SET is_active = %s, updated_at = NOW()
                WHERE normalization_rule_id = %s
                RETURNING *
                """,
                (is_active, rule_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("编码修正规则不存在")
            result = dict(row)
        return self._queue_dashboard_refresh(result, "normalization.status_changed")

    def delete_normalization_rule(self, rule_id: int) -> dict:
        with self.configuration_transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM dim.dim_company_product_code_normalization_rule
                WHERE normalization_rule_id = %s
                RETURNING *
                """,
                (rule_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ProductCategoryNotFoundError("编码修正规则不存在")
            result = dict(row)
        return self._queue_dashboard_refresh(result, "normalization.deleted")
