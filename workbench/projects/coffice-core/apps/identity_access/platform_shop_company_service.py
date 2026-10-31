from __future__ import annotations

import re
from datetime import date, timedelta

from .audit import write_audit
from .authorization import AuthorizationError
from .validation import paging, text


VIEW_PERMISSION = "system.platform_shop_company.view"
MANAGE_PERMISSION = "system.platform_shop_company.manage"
TARGET_TYPE = "platform_shop_company"


class PlatformShopCompanyNotFoundError(ValueError):
    http_status = 404


class PlatformShopCompanyConflictError(ValueError):
    http_status = 409


def _date(value: object, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是YYYY-MM-DD格式") from exc


def _platform_code(value: object) -> str:
    code = text(value, "平台编码", maximum=32).lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", code):
        raise ValueError("平台编码须以小写字母开头，且只能包含小写字母、数字、点、横线或下划线")
    return code


class PlatformShopCompanyService:
    def __init__(self, database):
        self.database = database

    @staticmethod
    def require_view(context) -> None:
        if not context.can(VIEW_PERMISSION):
            raise AuthorizationError("无权查看平台店铺公司映射")

    @staticmethod
    def require_manage(context) -> None:
        if not context.can(MANAGE_PERMISSION):
            raise AuthorizationError("无权维护平台店铺公司映射")

    @staticmethod
    def _status(row: dict, today: date | None = None) -> str:
        today = today or date.today()
        if not row["is_active"]:
            return "inactive"
        if row["valid_from"] > today:
            return "future"
        if row["valid_to"] is not None and row["valid_to"] < today:
            return "expired"
        return "current"

    @classmethod
    def _public(cls, row, today: date | None = None) -> dict:
        result = dict(row)
        result["mapping_status"] = cls._status(result, today)
        return result

    @staticmethod
    def _identity(data: dict) -> str:
        return f'{data["platform_code"]}|{data["shop_code"]}'

    @staticmethod
    def _lock_identity(cursor, identity: str) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (identity,))

    @staticmethod
    def _select_row(cursor, shop_company_sk: int, *, for_update: bool = False):
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            """SELECT shop_company_sk,platform_code,platform_name,company_code,company_name,
                      shop_code,shop_name,shop_type,account_id,is_default,is_active,
                      valid_from,valid_to,created_at,updated_at,shop_identity_key
               FROM dim.dim_platform_shop_company
               WHERE shop_company_sk=%s""" + suffix,
            (shop_company_sk,),
        )
        row = cursor.fetchone()
        if not row:
            raise PlatformShopCompanyNotFoundError("平台店铺公司映射不存在")
        return row

    @staticmethod
    def _payload(payload: dict, defaults: dict | None = None) -> dict:
        defaults = defaults or {}
        platform_code = _platform_code(payload.get("platform_code", defaults.get("platform_code")))
        shop_code = text(payload.get("shop_code", defaults.get("shop_code")), "店铺编码", maximum=128)
        if shop_code.lower() == "default":
            raise ValueError("正式店铺映射不能使用default店铺编码")
        return {
            "platform_code": platform_code,
            "platform_name": text(payload.get("platform_name", defaults.get("platform_name")), "平台名称", maximum=64),
            "company_code": text(payload.get("company_code", defaults.get("company_code")), "公司编码", maximum=32),
            "company_name": text(payload.get("company_name", defaults.get("company_name")), "公司名称", maximum=255),
            "shop_code": shop_code,
            "shop_name": text(payload.get("shop_name", defaults.get("shop_name")), "店铺名称", maximum=255),
            "shop_type": text(payload.get("shop_type", defaults.get("shop_type")), "店铺类型", maximum=64),
            "account_id": text(payload.get("account_id", defaults.get("account_id")), "账号ID", maximum=128),
            "valid_from": _date(payload.get("valid_from", defaults.get("valid_from") or date.today()), "生效日期"),
        }

    @staticmethod
    def _metadata_payload(payload: dict, current: dict) -> dict:
        return {
            "platform_name": text(payload.get("platform_name", current["platform_name"]), "平台名称", maximum=64),
            "company_name": text(payload.get("company_name", current["company_name"]), "公司名称", maximum=255),
            "shop_name": text(payload.get("shop_name", current["shop_name"]), "店铺名称", maximum=255),
            "shop_type": text(payload.get("shop_type", current["shop_type"]), "店铺类型", maximum=64),
            "account_id": text(payload.get("account_id", current["account_id"]), "账号ID", maximum=128),
        }

    @staticmethod
    def _assert_no_existing_overlap(rows: list[dict]) -> None:
        active = sorted((dict(row) for row in rows if row["is_active"]), key=lambda item: item["valid_from"])
        for previous, current in zip(active, active[1:]):
            if previous["valid_to"] is None or previous["valid_to"] >= current["valid_from"]:
                raise PlatformShopCompanyConflictError("该平台店铺已有重叠的有效版本，请先修正现有数据")

    def list(self, context, query: dict[str, str]) -> dict:
        self.require_view(context)
        page, size, offset = paging(query)
        keyword = query.get("keyword", "").strip()
        platform = query.get("platform", "").strip()
        company = query.get("company", "").strip()
        shop = query.get("shop", "").strip()
        status = query.get("status", "current").strip() or "current"
        if status not in {"current", "future", "expired", "inactive", "all"}:
            raise ValueError("映射状态筛选无效")

        conditions: list[str] = []
        params: list[object] = []
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                """(platform_code ILIKE %s OR platform_name ILIKE %s OR
                     company_code ILIKE %s OR company_name ILIKE %s OR
                     shop_code ILIKE %s OR shop_name ILIKE %s OR
                     shop_type ILIKE %s OR account_id ILIKE %s)"""
            )
            params.extend([pattern] * 8)
        for value, columns in (
            (platform, ("platform_code", "platform_name")),
            (company, ("company_code", "company_name")),
            (shop, ("shop_code", "shop_name", "account_id")),
        ):
            if value:
                pattern = f"%{value}%"
                conditions.append("(" + " OR ".join(f"{column} ILIKE %s" for column in columns) + ")")
                params.extend([pattern] * len(columns))

        for key, column in (
            ("platform_codes", "platform_code"),
            ("company_codes", "company_code"),
            ("shop_codes", "shop_code"),
        ):
            codes = list(dict.fromkeys(value.strip() for value in query.get(key, "").split(",") if value.strip()))
            if codes:
                conditions.append(f"{column}=ANY(%s)")
                params.append(codes)

        status_conditions = {
            "current": "is_active AND CURRENT_DATE>=valid_from AND (valid_to IS NULL OR CURRENT_DATE<=valid_to)",
            "future": "is_active AND valid_from>CURRENT_DATE",
            "expired": "is_active AND valid_to IS NOT NULL AND valid_to<CURRENT_DATE",
            "inactive": "NOT is_active",
        }
        if status != "all":
            conditions.append(status_conditions[status])
        where = " AND ".join(conditions) if conditions else "TRUE"

        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM dim.dim_platform_shop_company WHERE {where}", params)
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                f"""SELECT shop_company_sk,platform_code,platform_name,company_code,company_name,
                           shop_code,shop_name,shop_type,account_id,is_default,is_active,
                           valid_from,valid_to,created_at,updated_at,shop_identity_key
                    FROM dim.dim_platform_shop_company
                    WHERE {where}
                    ORDER BY platform_name,shop_name,valid_from DESC,shop_company_sk DESC
                    LIMIT %s OFFSET %s""",
                [*params, size, offset],
            )
            items = [self._public(row) for row in cursor.fetchall()]
            cursor.execute(
                """SELECT DISTINCT platform_code,platform_name,company_code,company_name,shop_code,shop_name,account_id
                   FROM dim.dim_platform_shop_company
                   ORDER BY platform_name,company_name,shop_name"""
            )
            filter_options = [dict(row) for row in cursor.fetchall()]
        return {"items": items, "total": total, "page": page, "page_size": size, "filter_options": filter_options}

    def _insert_version(
        self,
        cursor,
        data: dict,
        *,
        actor,
        ip_address: str,
        user_agent: str,
        source_shop_company_sk: int | None = None,
    ) -> dict:
        identity = self._identity(data)
        cursor.execute(
            """SELECT shop_company_sk,platform_code,platform_name,company_code,company_name,
                      shop_code,shop_name,shop_type,account_id,is_default,is_active,
                      valid_from,valid_to,created_at,updated_at,shop_identity_key
               FROM dim.dim_platform_shop_company
               WHERE shop_identity_key=%s
               ORDER BY valid_from,shop_company_sk
               FOR UPDATE""",
            (identity,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        self._assert_no_existing_overlap(rows)
        if any(row["valid_from"] == data["valid_from"] for row in rows):
            raise PlatformShopCompanyConflictError("该平台店铺在此生效日期已经存在版本")
        active_rows = [row for row in rows if row["is_active"]]
        if active_rows:
            latest = max(active_rows, key=lambda item: (item["valid_from"], item["shop_company_sk"]))
            if data["valid_from"] <= latest["valid_from"]:
                raise PlatformShopCompanyConflictError(
                    f'新版本生效日期必须晚于现有最新有效版本{latest["valid_from"].isoformat()}'
                )
            if source_shop_company_sk is not None and source_shop_company_sk != latest["shop_company_sk"]:
                raise PlatformShopCompanyConflictError("只能从该店铺的最新版本创建新版本")

        predecessor = next(
            (
                row for row in reversed(rows)
                if row["is_active"]
                and row["valid_from"] < data["valid_from"]
                and (row["valid_to"] is None or row["valid_to"] >= data["valid_from"])
            ),
            None,
        )
        if predecessor is not None:
            before = dict(predecessor)
            cursor.execute(
                """UPDATE dim.dim_platform_shop_company
                   SET valid_to=%s,updated_at=NOW()
                   WHERE shop_company_sk=%s
                   RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                             shop_code,shop_name,shop_type,account_id,is_default,is_active,
                             valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                (data["valid_from"] - timedelta(days=1), predecessor["shop_company_sk"]),
            )
            closed = dict(cursor.fetchone())
            write_audit(
                cursor,
                action="platform_shop_company.version_close",
                target_type=TARGET_TYPE,
                target_id=closed["shop_company_sk"],
                actor=actor,
                before=before,
                after=closed,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        cursor.execute(
            """INSERT INTO dim.dim_platform_shop_company(
                       platform_code,platform_name,company_code,company_name,
                       shop_code,shop_name,shop_type,account_id,
                       is_default,is_active,valid_from,valid_to
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE,TRUE,%s,NULL)
                   RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                             shop_code,shop_name,shop_type,account_id,is_default,is_active,
                             valid_from,valid_to,created_at,updated_at,shop_identity_key""",
            (
                data["platform_code"], data["platform_name"], data["company_code"], data["company_name"],
                data["shop_code"], data["shop_name"], data["shop_type"], data["account_id"],
                data["valid_from"],
            ),
        )
        created = dict(cursor.fetchone())
        audit_after = dict(created)
        if source_shop_company_sk is not None:
            audit_after["source_shop_company_sk"] = source_shop_company_sk
        write_audit(
            cursor,
            action="platform_shop_company.create",
            target_type=TARGET_TYPE,
            target_id=created["shop_company_sk"],
            actor=actor,
            after=audit_after,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        result = self._public(created)
        result["version_created"] = bool(rows)
        result["closed_shop_company_sk"] = predecessor["shop_company_sk"] if predecessor else None
        return result

    def create(self, context, payload: dict, *, ip_address: str, user_agent: str) -> dict:
        self.require_manage(context)
        data = self._payload(payload)
        with self.database.transaction() as cursor:
            self._lock_identity(cursor, self._identity(data))
            return self._insert_version(
                cursor,
                data,
                actor=context,
                ip_address=ip_address,
                user_agent=user_agent,
            )

    def update(
        self,
        context,
        shop_company_sk: int,
        payload: dict,
        *,
        ip_address: str,
        user_agent: str,
    ) -> dict:
        self.require_manage(context)
        create_version = payload.get("create_version") in (True, 1, "1", "true", "True", "on")
        with self.database.transaction() as cursor:
            snapshot = dict(self._select_row(cursor, shop_company_sk))
            if create_version:
                data = self._payload(payload, snapshot)
                target_identity = self._identity(data)
                for identity in sorted({snapshot["shop_identity_key"], target_identity}):
                    self._lock_identity(cursor, identity)
                current = dict(self._select_row(cursor, shop_company_sk, for_update=True))
                source_identity = current["shop_identity_key"]
                source_closed = None
                if target_identity != source_identity:
                    if not current["is_active"] or current["valid_to"] is not None:
                        raise PlatformShopCompanyConflictError("只能从该店铺的最新有效版本变更平台或店铺编码")
                    if data["valid_from"] <= current["valid_from"]:
                        raise PlatformShopCompanyConflictError(
                            f'新版本生效日期必须晚于原版本{current["valid_from"].isoformat()}'
                        )
                    cursor.execute(
                        "SELECT 1 FROM dim.dim_platform_shop_company WHERE shop_identity_key=%s LIMIT 1",
                        (target_identity,),
                    )
                    if cursor.fetchone():
                        raise PlatformShopCompanyConflictError("目标平台和店铺编码已经存在，不能合并两条版本链")
                    cursor.execute(
                        """UPDATE dim.dim_platform_shop_company
                           SET valid_to=%s,updated_at=NOW()
                           WHERE shop_company_sk=%s
                           RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                                     shop_code,shop_name,shop_type,account_id,is_default,is_active,
                                     valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                        (data["valid_from"] - timedelta(days=1), shop_company_sk),
                    )
                    source_closed = dict(cursor.fetchone())
                    write_audit(
                        cursor,
                        action="platform_shop_company.version_close",
                        target_type=TARGET_TYPE,
                        target_id=shop_company_sk,
                        actor=context,
                        before=current,
                        after=source_closed,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                result = self._insert_version(
                    cursor,
                    data,
                    actor=context,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    source_shop_company_sk=shop_company_sk,
                )
                if source_closed is not None:
                    result["version_created"] = True
                    result["closed_shop_company_sk"] = shop_company_sk
                return result

            immutable = {
                "platform_code": _platform_code,
                "company_code": lambda value: text(value, "公司编码", maximum=32),
                "shop_code": lambda value: text(value, "店铺编码", maximum=128),
                "valid_from": lambda value: _date(value, "生效日期"),
            }
            for field, normalize in immutable.items():
                if field in payload and normalize(payload[field]) != snapshot[field]:
                    raise ValueError("关键编码或生效日期变更必须使用新增版本操作")

            current = dict(self._select_row(cursor, shop_company_sk, for_update=True))
            metadata = self._metadata_payload(payload, current)
            cursor.execute(
                """UPDATE dim.dim_platform_shop_company
                   SET platform_name=%s,company_name=%s,shop_name=%s,shop_type=%s,account_id=%s,updated_at=NOW()
                   WHERE shop_company_sk=%s
                   RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                             shop_code,shop_name,shop_type,account_id,is_default,is_active,
                             valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                (
                    metadata["platform_name"], metadata["company_name"], metadata["shop_name"],
                    metadata["shop_type"], metadata["account_id"], shop_company_sk,
                ),
            )
            updated = dict(cursor.fetchone())
            write_audit(
                cursor,
                action="platform_shop_company.update",
                target_type=TARGET_TYPE,
                target_id=shop_company_sk,
                actor=context,
                before=current,
                after=updated,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            return self._public(updated)

    def expire(
        self,
        context,
        shop_company_sk: int,
        *,
        ip_address: str,
        user_agent: str,
    ) -> dict:
        self.require_manage(context)
        with self.database.transaction() as cursor:
            snapshot = dict(self._select_row(cursor, shop_company_sk))
            self._lock_identity(cursor, snapshot["shop_identity_key"])
            current = dict(self._select_row(cursor, shop_company_sk, for_update=True))
            cursor.execute("SELECT CURRENT_DATE AS today")
            today = cursor.fetchone()["today"]
            status = self._status(current, today)
            if status in {"expired", "inactive"}:
                raise PlatformShopCompanyConflictError("该映射已经失效")

            reopened = None
            if current["valid_from"] < today:
                cursor.execute(
                    """UPDATE dim.dim_platform_shop_company
                       SET valid_to=%s,is_active=TRUE,updated_at=NOW()
                       WHERE shop_company_sk=%s
                       RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                                 shop_code,shop_name,shop_type,account_id,is_default,is_active,
                                 valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                    (today - timedelta(days=1), shop_company_sk),
                )
            else:
                cursor.execute(
                    """UPDATE dim.dim_platform_shop_company
                       SET is_active=FALSE,updated_at=NOW()
                       WHERE shop_company_sk=%s
                       RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                                 shop_code,shop_name,shop_type,account_id,is_default,is_active,
                                 valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                    (shop_company_sk,),
                )
            expired = dict(cursor.fetchone())

            if current["valid_from"] > today:
                cursor.execute(
                    """SELECT valid_from
                       FROM dim.dim_platform_shop_company
                       WHERE shop_identity_key=%s AND is_active
                         AND valid_from>%s
                       ORDER BY valid_from,shop_company_sk LIMIT 1
                       FOR UPDATE""",
                    (current["shop_identity_key"], current["valid_from"]),
                )
                successor = cursor.fetchone()
                predecessor_valid_to = successor["valid_from"] - timedelta(days=1) if successor else None
                cursor.execute(
                    """SELECT shop_company_sk,platform_code,platform_name,company_code,company_name,
                              shop_code,shop_name,shop_type,account_id,is_default,is_active,
                              valid_from,valid_to,created_at,updated_at,shop_identity_key
                       FROM dim.dim_platform_shop_company
                       WHERE shop_identity_key=%s AND is_active
                         AND valid_to=%s AND shop_company_sk<>%s
                       ORDER BY valid_from DESC,shop_company_sk DESC LIMIT 1
                       FOR UPDATE""",
                    (current["shop_identity_key"], current["valid_from"] - timedelta(days=1), shop_company_sk),
                )
                predecessor = cursor.fetchone()
                if predecessor:
                    predecessor_before = dict(predecessor)
                    cursor.execute(
                        """UPDATE dim.dim_platform_shop_company
                           SET valid_to=%s,updated_at=NOW()
                           WHERE shop_company_sk=%s
                           RETURNING shop_company_sk,platform_code,platform_name,company_code,company_name,
                                     shop_code,shop_name,shop_type,account_id,is_default,is_active,
                                     valid_from,valid_to,created_at,updated_at,shop_identity_key""",
                        (predecessor_valid_to, predecessor["shop_company_sk"]),
                    )
                    reopened = dict(cursor.fetchone())
                    write_audit(
                        cursor,
                        action=(
                            "platform_shop_company.version_reopen"
                            if predecessor_valid_to is None
                            else "platform_shop_company.version_relink"
                        ),
                        target_type=TARGET_TYPE,
                        target_id=reopened["shop_company_sk"],
                        actor=context,
                        before=predecessor_before,
                        after=reopened,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )

            write_audit(
                cursor,
                action="platform_shop_company.expire",
                target_type=TARGET_TYPE,
                target_id=shop_company_sk,
                actor=context,
                before=current,
                after=expired,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            result = self._public(expired, today)
            result["reopened_shop_company_sk"] = reopened["shop_company_sk"] if reopened else None
            return result
