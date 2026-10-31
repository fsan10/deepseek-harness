"""公司统一达人、平台账号映射与月度商务归属配置服务。"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover - 静态路由测试可无数据库驱动
    psycopg2 = None
    RealDictCursor = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILES = [
    PROJECT_ROOT / "sql/dim/166_dim_influencer_business_config_postgres.sql",
    PROJECT_ROOT / "sql/dim/394_dim_company_influencer_postgres.sql",
    PROJECT_ROOT / "sql/dim/395_migrate_company_influencer_legacy_postgres.sql",
]
IDENTITY_SQL_FILE = PROJECT_ROOT / "sql/common/396_dws_influencer_identity_resolved_view_postgres.sql"
ADS_IDENTITY_SQL_FILE = PROJECT_ROOT / "sql/ads/influencer_performance/397_alter_ads_influencer_identity_postgres.sql"
PLATFORMS = {
    "douyin", "tmall", "wechat_channels", "ks", "xhs", "jd", "pdd"
}
PAGE_SIZES = (10, 20, 50, 100)


class InfluencerMasterNotFoundError(ValueError):
    http_status = 404


class InfluencerMasterConflictError(ValueError):
    http_status = 409

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details


def _text(value, label: str, max_length: int) -> str:
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
        raise ValueError(f"{label}格式错误") from exc
    if result <= 0:
        raise ValueError(f"{label}必须大于0")
    return result


class InfluencerMasterService:
    def __init__(self, args, refresh_request=None):
        self.connect_kwargs = {
            "host": args.host,
            "port": args.port,
            "dbname": args.dbname,
            "user": args.user,
            "password": args.password,
        }
        self.refresh_request = refresh_request

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

    @staticmethod
    def _validate_page(page: int, page_size: int) -> None:
        if page < 1 or page_size not in PAGE_SIZES:
            raise ValueError("分页参数无效")

    def _refresh(self, result: dict, reason: str) -> dict:
        if self.refresh_request is not None:
            result["metrics_refresh"] = self.refresh_request(reason)
            result["metrics_refreshed"] = False
        return result

    def migrate(self) -> str:
        executed = list(MIGRATION_FILES)
        with self.transaction() as cursor:
            for sql_file in MIGRATION_FILES:
                cursor.execute(sql_file.read_text(encoding="utf-8"))
            cursor.execute(
                """
                SELECT
                    TO_REGCLASS('dws.dws_douyin_influencer_sales_order_item') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_wechat_channels_influencer_sales_order_item') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_ks_influencer_sales_order_item') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_tmall_influencer_sales_order') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_jd_influencer_sales_shop_daily_zero') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_xhs_influencer_sales_shop_daily_zero') IS NOT NULL
                    AND TO_REGCLASS('dws.dws_pdd_influencer_sales_shop_daily_zero') IS NOT NULL
                        AS dws_ready,
                    TO_REGCLASS('ads.ads_influencer_company_shop_daily') IS NOT NULL
                    AND TO_REGCLASS('ads.ads_influencer_company_shop_monthly_ranking') IS NOT NULL
                        AS ads_ready
                """
            )
            readiness = cursor.fetchone()
            if readiness["dws_ready"]:
                cursor.execute(IDENTITY_SQL_FILE.read_text(encoding="utf-8"))
                executed.append(IDENTITY_SQL_FILE)
            if readiness["ads_ready"]:
                cursor.execute(ADS_IDENTITY_SQL_FILE.read_text(encoding="utf-8"))
                executed.append(ADS_IDENTITY_SQL_FILE)
        return "、".join(str(path.relative_to(PROJECT_ROOT)) for path in executed)

    def health(self) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT
                    TO_REGCLASS('dim.dim_company_influencer') IS NOT NULL
                        AS company_influencer_ready,
                    TO_REGCLASS('dim.dim_company_influencer_source_mapping') IS NOT NULL
                        AS influencer_source_mapping_ready,
                    TO_REGCLASS('dim.dim_company_influencer_business_assignment_monthly') IS NOT NULL
                        AS company_influencer_assignment_ready
                """
            )
            return dict(cursor.fetchone())

    def list_company_influencers(
        self,
        search: str | None,
        status: str | None,
        page: int,
        page_size: int,
        platform_code: str | None = None,
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        status = (status or "all").strip()
        if status not in ("all", "active", "inactive"):
            raise ValueError("状态无效")
        platform_code = (platform_code or "").strip().lower()
        if platform_code and platform_code not in PLATFORMS:
            raise ValueError("不支持的平台")
        where = ["TRUE"]
        params: list = []
        if search:
            pattern = f"%{search}%"
            where.append(
                "(i.company_influencer_name ILIKE %s "
                "OR COALESCE(i.note, '') ILIKE %s "
                "OR i.company_influencer_id::text ILIKE %s)"
            )
            params.extend([pattern] * 3)
        if platform_code:
            where.append(
                "EXISTS ("
                "SELECT 1 FROM dim.dim_company_influencer_source_mapping platform_mapping "
                "WHERE platform_mapping.company_influencer_id = i.company_influencer_id "
                "AND platform_mapping.is_active "
                "AND platform_mapping.platform_code = %s)"
            )
            params.append(platform_code)
        if status == "active":
            where.append("i.is_active")
        elif status == "inactive":
            where.append("NOT i.is_active")
        clause = " AND ".join(where)
        with self.transaction() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM dim.dim_company_influencer i WHERE {clause}",
                params,
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT
                    i.company_influencer_id,
                    i.company_influencer_name,
                    i.note,
                    i.is_active,
                    i.created_at,
                    i.updated_at,
                    COUNT(mapping.mapping_id) AS source_account_count,
                    COUNT(mapping.mapping_id) FILTER (WHERE mapping.is_active)
                        AS active_source_account_count,
                    STRING_AGG(
                        DISTINCT mapping.platform_code,
                        '、' ORDER BY mapping.platform_code
                    ) FILTER (WHERE mapping.is_active) AS platforms
                FROM dim.dim_company_influencer i
                LEFT JOIN dim.dim_company_influencer_source_mapping mapping
                  ON mapping.company_influencer_id = i.company_influencer_id
                WHERE {clause}
                GROUP BY i.company_influencer_id
                ORDER BY i.company_influencer_id ASC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "rows": rows,
            "pagination": {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def create_company_influencer(self, payload: dict) -> dict:
        name = _text(payload.get("company_influencer_name"), "公司达人名称", 255)
        note = str(payload.get("note") or "").strip() or None
        with self.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO dim.dim_company_influencer (
                    company_influencer_name, note
                ) VALUES (%s, %s)
                RETURNING *
                """,
                (name, note),
            )
            row = dict(cursor.fetchone())
        return self._refresh(row, "company_influencer.created")

    def update_company_influencer(self, influencer_id: int, payload: dict) -> dict:
        name = _text(payload.get("company_influencer_name"), "公司达人名称", 255)
        note = str(payload.get("note") or "").strip() or None
        with self.transaction() as cursor:
            cursor.execute(
                """
                UPDATE dim.dim_company_influencer
                SET company_influencer_name = %s, note = %s, updated_at = NOW()
                WHERE company_influencer_id = %s
                RETURNING *
                """,
                (name, note, influencer_id),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("公司达人不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer.updated")

    def set_company_influencer_status(self, influencer_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("启用状态必须为布尔值")
        with self.transaction() as cursor:
            cursor.execute(
                """
                UPDATE dim.dim_company_influencer
                SET is_active = %s, updated_at = NOW()
                WHERE company_influencer_id = %s
                RETURNING *
                """,
                (is_active, influencer_id),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("公司达人不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer.status_changed")

    def delete_company_influencer(self, influencer_id: int) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM dim.dim_company_influencer_source_mapping
                     WHERE company_influencer_id = %s) AS mapping_count,
                    (SELECT COUNT(*) FROM dim.dim_company_influencer_business_assignment_monthly
                     WHERE company_influencer_id = %s) AS assignment_count
                """,
                (influencer_id, influencer_id),
            )
            dependency = cursor.fetchone()
            if dependency["mapping_count"] or dependency["assignment_count"]:
                raise InfluencerMasterConflictError(
                    "该公司达人仍有平台账号映射或商务归属，请先处理依赖"
                )
            cursor.execute(
                """
                DELETE FROM dim.dim_company_influencer
                WHERE company_influencer_id = %s
                RETURNING *
                """,
                (influencer_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("公司达人不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer.deleted")

    def list_source_accounts(
        self,
        search: str | None,
        mapping_status: str | None,
        platform_code: str | None,
        page: int,
        page_size: int,
        gmv_min: str | None = None,
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        mapping_status = (mapping_status or "all").strip()
        platform_code = (platform_code or "").strip().lower()
        if mapping_status not in ("all", "mapped", "unmapped"):
            raise ValueError("映射状态无效")
        if platform_code and platform_code not in PLATFORMS:
            raise ValueError("不支持的平台")
        gmv_min_value = None
        if str(gmv_min or "").strip():
            try:
                gmv_min_value = Decimal(str(gmv_min).strip())
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("GMV筛选值格式错误") from exc
            if gmv_min_value < 0:
                raise ValueError("GMV筛选值不能小于0")
        where = ["source.source_influencer_id <> '__no_influencer__'"]
        params: list = []
        if search:
            pattern = f"%{search}%"
            where.append(
                "(source.source_influencer_id ILIKE %s "
                "OR source.source_influencer_name ILIKE %s "
                "OR COALESCE(company.company_influencer_name, '') ILIKE %s)"
            )
            params.extend([pattern] * 3)
        if platform_code:
            where.append("source.platform_code = %s")
            params.append(platform_code)
        if mapping_status == "mapped":
            where.append("mapping.mapping_id IS NOT NULL AND mapping.is_active")
        elif mapping_status == "unmapped":
            where.append("(mapping.mapping_id IS NULL OR NOT mapping.is_active)")
        if gmv_min_value is not None:
            where.append("COALESCE(source.gmv_amount, 0) >= %s")
            params.append(gmv_min_value)
        clause = " AND ".join(where)
        from_clause = """
            FROM (
                SELECT
                    platform_code,
                    source_influencer_id,
                    MAX(source_influencer_name) AS source_influencer_name,
                    STRING_AGG(DISTINCT shop_name, '、' ORDER BY shop_name) AS shop_names,
                    ROUND(SUM(gmv_amount), 2) AS gmv_amount,
                    MIN(stat_date) AS first_seen_date,
                    MAX(stat_date) AS last_seen_date
                FROM dws.v_influencer_identity_resolved
                GROUP BY platform_code, source_influencer_id
            ) source
            LEFT JOIN dim.dim_company_influencer_source_mapping mapping
              ON mapping.platform_code = source.platform_code
             AND mapping.source_influencer_id = source.source_influencer_id
            LEFT JOIN dim.dim_company_influencer company
              ON company.company_influencer_id = mapping.company_influencer_id
        """
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT TO_REGCLASS('dws.v_influencer_identity_resolved') AS view_name"
            )
            if cursor.fetchone()["view_name"] is None:
                return {
                    "rows": [],
                    "pagination": {
                        "page": page,
                        "page_size": page_size,
                        "total": 0,
                        "unmapped_total": 0,
                        "total_pages": 1,
                    },
                }
            cursor.execute(
                f"SELECT COUNT(*) AS total {from_clause} WHERE {clause}", params
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"SELECT COUNT(*) AS unmapped_total {from_clause} WHERE {clause} AND (mapping.mapping_id IS NULL OR NOT mapping.is_active)",
                params,
            )
            unmapped_total = int(cursor.fetchone()["unmapped_total"])
            cursor.execute(
                f"""
                SELECT
                    source.platform_code, source.source_influencer_id,
                    source.source_influencer_name, source.shop_names,
                    source.gmv_amount, source.first_seen_date, source.last_seen_date,
                    mapping.mapping_id, mapping.company_influencer_id,
                    company.company_influencer_name,
                    COALESCE(mapping.is_active, FALSE) AS mapping_active,
                    CASE WHEN mapping.mapping_id IS NOT NULL AND mapping.is_active
                         THEN 'mapped' ELSE 'unmapped' END AS mapping_status
                {from_clause}
                WHERE {clause}
                ORDER BY CASE WHEN mapping.mapping_id IS NULL OR NOT mapping.is_active
                              THEN 0 ELSE 1 END,
                         source.gmv_amount DESC, source.platform_code,
                         source.source_influencer_id
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "rows": rows,
            "pagination": {
                "page": page, "page_size": page_size, "total": total,
                "unmapped_total": unmapped_total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    @staticmethod
    def _normalize_source_item(item: dict) -> tuple[str, str, str]:
        platform = _text(item.get("platform_code"), "平台", 32).lower()
        if platform not in PLATFORMS:
            raise ValueError("不支持的平台")
        source_id = _text(item.get("source_influencer_id"), "平台达人ID", 128)
        source_name = str(item.get("source_influencer_name") or source_id).strip()
        if len(source_name) > 255:
            raise ValueError("平台达人昵称不能超过255字")
        return platform, source_id, source_name

    @staticmethod
    def _assignment_conflicts(cursor, source_company_id: int, target_company_id: int) -> list[dict]:
        cursor.execute(
            """
            SELECT
                source.effective_month,
                source.business_owner_id AS source_business_owner_id,
                target.business_owner_id AS target_business_owner_id
            FROM dim.dim_company_influencer_business_assignment_monthly source
            JOIN dim.dim_company_influencer_business_assignment_monthly target
              ON target.effective_month = source.effective_month
             AND target.company_influencer_id = %s
            WHERE source.company_influencer_id = %s
              AND source.is_active
              AND target.is_active
              AND source.business_owner_id IS DISTINCT FROM target.business_owner_id
            ORDER BY source.effective_month
            """,
            (target_company_id, source_company_id),
        )
        return [dict(row) for row in cursor.fetchall()]

    def save_source_mappings(self, payload: dict) -> dict:
        target_id = _positive_int(payload.get("company_influencer_id"), "公司达人")
        items = payload.get("items")
        if not isinstance(items, list):
            items = [payload]
        if not items or len(items) > 500:
            raise ValueError("映射账号数必须在1到500之间")
        normalized = [self._normalize_source_item(item) for item in items]
        confirm_move = payload.get("confirm_move") is True
        resolution = str(payload.get("assignment_resolution") or "").strip()
        if resolution and resolution not in ("keep_target", "use_source"):
            raise ValueError("商务归属冲突处理方式无效")
        moves: list[dict] = []
        assignment_conflicts: list[dict] = []
        with self.transaction() as cursor:
            cursor.execute(
                """
                SELECT is_active FROM dim.dim_company_influencer
                WHERE company_influencer_id = %s FOR UPDATE
                """,
                (target_id,),
            )
            target = cursor.fetchone()
            if not target or not target["is_active"]:
                raise InfluencerMasterNotFoundError("目标公司达人不存在或已停用")
            for platform, source_id, _ in normalized:
                cursor.execute(
                    """
                    SELECT mapping_id, company_influencer_id
                    FROM dim.dim_company_influencer_source_mapping
                    WHERE platform_code = %s AND source_influencer_id = %s
                    FOR UPDATE
                    """,
                    (platform, source_id),
                )
                current = cursor.fetchone()
                if current and current["company_influencer_id"] != target_id:
                    source_company_id = int(current["company_influencer_id"])
                    conflicts = self._assignment_conflicts(cursor, source_company_id, target_id)
                    moves.append(
                        {
                            "platform_code": platform,
                            "source_influencer_id": source_id,
                            "source_company_influencer_id": source_company_id,
                        }
                    )
                    assignment_conflicts.extend(
                        [
                            {
                                **conflict,
                                "source_company_influencer_id": source_company_id,
                                "target_company_influencer_id": target_id,
                            }
                            for conflict in conflicts
                        ]
                    )
            if moves and not confirm_move:
                raise InfluencerMasterConflictError(
                    "部分平台账号已映射到其他公司达人，请明确确认合并",
                    {"moves": moves, "assignment_conflicts": assignment_conflicts},
                )
            if assignment_conflicts and not resolution:
                raise InfluencerMasterConflictError(
                    "合并的公司达人存在同月不同商务归属，请选择保留目标达人或使用来源达人归属",
                    {"moves": moves, "assignment_conflicts": assignment_conflicts},
                )
            source_company_ids = sorted(
                {item["source_company_influencer_id"] for item in moves}
            )
            for source_company_id in source_company_ids:
                cursor.execute(
                    """
                    INSERT INTO dim.dim_company_influencer_business_assignment_monthly AS target (
                        company_influencer_id, effective_month, business_owner_id,
                        assignment_source, note, is_active
                    )
                    SELECT %s, source.effective_month, source.business_owner_id,
                           'merge_resolution',
                           '平台账号合并时迁移的商务归属', source.is_active
                    FROM dim.dim_company_influencer_business_assignment_monthly source
                    WHERE source.company_influencer_id = %s
                    ON CONFLICT (company_influencer_id, effective_month)
                    DO UPDATE SET
                        business_owner_id = CASE WHEN %s = 'use_source'
                            THEN EXCLUDED.business_owner_id
                            ELSE target.business_owner_id
                        END,
                        assignment_source = 'merge_resolution',
                        note = '公司达人合并冲突已人工确认',
                        is_active = CASE WHEN %s = 'use_source'
                            THEN EXCLUDED.is_active
                            ELSE target.is_active
                        END,
                        updated_at = NOW()
                    """,
                    (target_id, source_company_id, resolution, resolution),
                )
            created = updated = 0
            for platform, source_id, source_name in normalized:
                cursor.execute(
                    """
                    SELECT mapping_id
                    FROM dim.dim_company_influencer_source_mapping
                    WHERE platform_code = %s AND source_influencer_id = %s
                    """,
                    (platform, source_id),
                )
                current = cursor.fetchone()
                if current:
                    cursor.execute(
                        """
                        UPDATE dim.dim_company_influencer_source_mapping
                        SET company_influencer_id = %s,
                            source_influencer_name_snapshot = %s,
                            is_active = TRUE, updated_at = NOW()
                        WHERE mapping_id = %s
                        """,
                        (target_id, source_name, current["mapping_id"]),
                    )
                    updated += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO dim.dim_company_influencer_source_mapping (
                            company_influencer_id, platform_code,
                            source_influencer_id, source_influencer_name_snapshot,
                            is_active
                        ) VALUES (%s, %s, %s, %s, TRUE)
                        """,
                        (target_id, platform, source_id, source_name),
                    )
                    created += 1
            if source_company_ids:
                cursor.execute(
                    """
                    UPDATE dim.dim_company_influencer source
                    SET is_active = FALSE,
                        note = CONCAT_WS(E'\n', NULLIF(source.note, ''),
                            '平台账号已合并到其他公司达人'),
                        updated_at = NOW()
                    WHERE source.company_influencer_id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM dim.dim_company_influencer_source_mapping mapping
                          WHERE mapping.company_influencer_id = source.company_influencer_id
                            AND mapping.is_active
                      )
                    """,
                    (source_company_ids,),
                )
        return self._refresh(
            {
                "created": created,
                "updated": updated,
                "moved": len(moves),
                "assignment_conflicts_resolved": len(assignment_conflicts),
            },
            "company_influencer_mapping.saved",
        )

    def set_source_mapping_status(self, mapping_id: int, is_active: bool) -> dict:
        if not isinstance(is_active, bool):
            raise ValueError("启用状态必须为布尔值")
        with self.transaction() as cursor:
            cursor.execute(
                """
                UPDATE dim.dim_company_influencer_source_mapping
                SET is_active = %s, updated_at = NOW()
                WHERE mapping_id = %s
                RETURNING *
                """,
                (is_active, mapping_id),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("平台达人映射不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer_mapping.status_changed")

    def delete_source_mapping(self, mapping_id: int) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM dim.dim_company_influencer_source_mapping
                WHERE mapping_id = %s RETURNING *
                """,
                (mapping_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("平台达人映射不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer_mapping.deleted")

    def list_assignments(
        self,
        month: date,
        search: str | None,
        owner_id: int | None,
        page: int,
        page_size: int,
        platform_code: str | None = None,
    ) -> dict:
        self._validate_page(page, page_size)
        search = (search or "").strip()
        platform_code = (platform_code or "").strip().lower()
        if platform_code and platform_code not in PLATFORMS:
            raise ValueError("不支持的平台")
        where = ["influencer.is_active"]
        params: list = [month]
        if search:
            pattern = f"%{search}%"
            where.append(
                "(influencer.company_influencer_name ILIKE %s "
                "OR COALESCE(owner.business_owner_name, '') ILIKE %s "
                "OR influencer.company_influencer_id::text ILIKE %s)"
            )
            params.extend([pattern] * 3)
        if owner_id is not None:
            where.append("COALESCE(assignment.business_owner_id, 0) = %s")
            params.append(owner_id)
        if platform_code:
            where.append(
                "EXISTS ("
                "SELECT 1 FROM dim.dim_company_influencer_source_mapping platform_mapping "
                "WHERE platform_mapping.company_influencer_id = influencer.company_influencer_id "
                "AND platform_mapping.is_active "
                "AND platform_mapping.platform_code = %s)"
            )
            params.append(platform_code)
        clause = " AND ".join(where)
        from_clause = """
            FROM dim.dim_company_influencer influencer
            LEFT JOIN LATERAL (
                SELECT version.*
                FROM dim.dim_company_influencer_business_assignment_monthly version
                WHERE version.company_influencer_id = influencer.company_influencer_id
                  AND version.effective_month <= %s
                ORDER BY version.effective_month DESC
                LIMIT 1
            ) assignment ON TRUE
            LEFT JOIN dim.dim_business_owner owner
              ON owner.business_owner_id = assignment.business_owner_id
        """
        with self.transaction() as cursor:
            cursor.execute(
                f"SELECT COUNT(*) AS total {from_clause} WHERE {clause}", params
            )
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""
                SELECT
                    influencer.company_influencer_id,
                    influencer.company_influencer_name,
                    assignment.effective_month,
                    CASE WHEN assignment.is_active THEN assignment.business_owner_id END
                        AS business_owner_id,
                    CASE WHEN assignment.is_active THEN owner.business_owner_name END
                        AS business_owner_name,
                    COALESCE(assignment.is_active, FALSE) AS assignment_active,
                    assignment.assignment_source,
                    assignment.note,
                    (SELECT COUNT(*)
                     FROM dim.dim_company_influencer_source_mapping mapping
                     WHERE mapping.company_influencer_id = influencer.company_influencer_id
                       AND mapping.is_active) AS source_account_count
                {from_clause}
                WHERE {clause}
                ORDER BY influencer.company_influencer_id ASC
                LIMIT %s OFFSET %s
                """,
                [*params, page_size, (page - 1) * page_size],
            )
            rows = [dict(row) for row in cursor.fetchall()]
        return {
            "month": month,
            "rows": rows,
            "pagination": {
                "page": page, "page_size": page_size, "total": total,
                "total_pages": max(1, (total + page_size - 1) // page_size),
            },
        }

    def save_assignment(self, payload: dict, effective_month: date) -> dict:
        influencer_id = _positive_int(payload.get("company_influencer_id"), "公司达人")
        owner_value = payload.get("business_owner_id")
        owner_id = int(owner_value) if owner_value not in (None, "", 0, "0") else None
        is_active = payload.get("is_active", True) is True
        note = str(payload.get("note") or "").strip() or None
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT 1 FROM dim.dim_company_influencer WHERE company_influencer_id = %s",
                (influencer_id,),
            )
            if cursor.fetchone() is None:
                raise InfluencerMasterNotFoundError("公司达人不存在")
            if owner_id is not None:
                cursor.execute(
                    "SELECT 1 FROM dim.dim_business_owner WHERE business_owner_id = %s AND is_active",
                    (owner_id,),
                )
                if cursor.fetchone() is None:
                    raise InfluencerMasterNotFoundError("商务不存在或已停用")
            cursor.execute(
                """
                INSERT INTO dim.dim_company_influencer_business_assignment_monthly (
                    company_influencer_id, effective_month, business_owner_id,
                    assignment_source, note, is_active
                ) VALUES (%s, %s, %s, 'web', %s, %s)
                ON CONFLICT (company_influencer_id, effective_month)
                DO UPDATE SET business_owner_id = EXCLUDED.business_owner_id,
                              assignment_source = 'web', note = EXCLUDED.note,
                              is_active = EXCLUDED.is_active, updated_at = NOW()
                RETURNING *
                """,
                (influencer_id, effective_month, owner_id, note, is_active),
            )
            result = dict(cursor.fetchone())
        return self._refresh(result, "company_influencer_assignment.saved")

    def delete_assignment(self, influencer_id: int, effective_month: date) -> dict:
        with self.transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM dim.dim_company_influencer_business_assignment_monthly
                WHERE company_influencer_id = %s AND effective_month = %s
                RETURNING *
                """,
                (influencer_id, effective_month),
            )
            row = cursor.fetchone()
            if not row:
                raise InfluencerMasterNotFoundError("该月商务归属版本不存在")
            result = dict(row)
        return self._refresh(result, "company_influencer_assignment.deleted")
