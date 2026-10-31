"""Resolve Cloak profile metadata to one dim.dim_platform_shop_company row.

The previous implementation matched three free-text fields with exact equality and
reported every failure as “未唯一匹配DIM标准店铺”. In practice a half-width
parenthesis in the profile note (``(南京)`` vs ``（南京）``) was enough to hide an
otherwise correct mapping, and the UI then disabled the whole shop.

This module keeps matching deterministic and explainable:

1. stable identifiers first (``shop_code`` / ``account_id``);
2. otherwise normalized platform + shop name (NFKC folds full-width to half-width,
   whitespace and case are ignored);
3. company name is a *soft* check — a mismatch is reported but still maps the shop,
   because the shop code is what downstream ingest keys on.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any, Iterable

MAPPING_MATCHED = "matched"
MAPPING_COMPANY_MISMATCH = "company_mismatch"
MAPPING_NOT_FOUND = "not_found"
MAPPING_AMBIGUOUS = "ambiguous"
MAPPING_INACTIVE = "inactive"
MAPPING_EXPIRED = "expired"
MAPPING_MISSING_METADATA = "missing_metadata"

MAPPING_LABELS = {
    MAPPING_MATCHED: "已匹配",
    MAPPING_COMPANY_MISMATCH: "已匹配（公司名待确认）",
    MAPPING_NOT_FOUND: "DIM 无此店铺",
    MAPPING_AMBIGUOUS: "同名多行，需指定",
    MAPPING_INACTIVE: "DIM 已停用",
    MAPPING_EXPIRED: "映射已过期",
    MAPPING_MISSING_METADATA: "缺少店铺信息",
}

MAPPING_HINTS = {
    MAPPING_NOT_FOUND: "DIM 中没有同名店铺；请确认 Profile note 的 platform/shop 与映射表一致",
    MAPPING_AMBIGUOUS: "同一平台存在多个同名店铺，请按店铺编码指定",
    MAPPING_INACTIVE: "DIM 中该店铺已停用，启用后才能上传",
    MAPPING_EXPIRED: "DIM 映射有效期已结束，请维护新的有效期",
    MAPPING_MISSING_METADATA: "Profile note 需包含 platform=<平台>;company=<公司>;shop=<店铺>",
}

MAPPED_STATUSES = frozenset({MAPPING_MATCHED, MAPPING_COMPANY_MISMATCH})

_SPACE = re.compile(r"\s+")


def normalize_text(value: Any) -> str:
    """Fold width/case/spacing so full- and half-width punctuation compare equal."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    return _SPACE.sub("", text).casefold()


def load_dim_rows(cursor) -> list[dict]:
    cursor.execute(
        """SELECT platform_code,platform_name,company_code,company_name,shop_code,shop_name,
                  account_id,is_active,valid_from,valid_to
           FROM dim.dim_platform_shop_company"""
    )
    return [dict(row) for row in cursor.fetchall()]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _candidate(row: dict) -> dict:
    return {
        "shop_code": row.get("shop_code"),
        "shop_name": row.get("shop_name"),
        "company_name": row.get("company_name"),
        "platform_name": row.get("platform_name"),
        "is_active": bool(row.get("is_active")),
        "valid_from": _iso(row.get("valid_from")),
        "valid_to": _iso(row.get("valid_to")),
    }


def _result(status: str, *, row: dict | None = None, candidates: Iterable[dict] = (), reason: str = "") -> dict:
    payload = {
        "mapping_status": status,
        "mapping_ok": status in MAPPED_STATUSES,
        "mapping_label": MAPPING_LABELS.get(status, status),
        "mapping_reason": reason or MAPPING_HINTS.get(status, ""),
        "mapping_candidates": [_candidate(item) for item in list(candidates)[:5]],
    }
    if row:
        payload.update(
            platform_code=row.get("platform_code"),
            company_code=row.get("company_code"),
            shop_code=row.get("shop_code"),
            dim_shop_name=row.get("shop_name"),
            dim_company_name=row.get("company_name"),
        )
    return payload


def resolve_dim(rows: list[dict], metadata: dict, today: date | None = None) -> dict:
    """Return a mapping decision for one profile's metadata."""

    today = today or date.today()
    platform = normalize_text(metadata.get("platform"))
    shop = normalize_text(metadata.get("shop"))
    company = normalize_text(metadata.get("company"))
    if not platform or not shop:
        return _result(MAPPING_MISSING_METADATA)

    # 1) stable identifiers win over display names
    for key in ("shop_code", "account_id"):
        code = str(metadata.get(key) or "").strip()
        if not code:
            continue
        by_code = [row for row in rows if str(row.get("shop_code") or "") == code or str(row.get("account_id") or "") == code]
        if len(by_code) == 1:
            return _result(MAPPING_MATCHED, row=by_code[0])

    pool = [row for row in rows if normalize_text(row.get("platform_name")) == platform]
    by_name = [row for row in pool if normalize_text(row.get("shop_name")) == shop]
    if not by_name:
        return _result(MAPPING_NOT_FOUND)

    def valid(row: dict) -> bool:
        if not row.get("is_active"):
            return False
        start = row.get("valid_from")
        end = row.get("valid_to")
        if start and start > today:
            return False
        return not (end and end < today)

    current = [row for row in by_name if valid(row)]
    if not current:
        inactive = not any(row.get("is_active") for row in by_name)
        return _result(MAPPING_INACTIVE if inactive else MAPPING_EXPIRED, candidates=by_name)

    if len(current) == 1:
        row = current[0]
        if company and normalize_text(row.get("company_name")) != company:
            return _result(
                MAPPING_COMPANY_MISMATCH,
                row=row,
                candidates=current,
                reason="公司名与 DIM 不一致（不影响下载与上传），请确认归属",
            )
        return _result(MAPPING_MATCHED, row=row, candidates=current)

    by_company = [row for row in current if normalize_text(row.get("company_name")) == company] if company else []
    if len(by_company) == 1:
        return _result(MAPPING_MATCHED, row=by_company[0], candidates=current)
    same_shop = {str(row.get("shop_code") or "") for row in current}
    if len(same_shop) == 1:
        return _result(MAPPING_MATCHED, row=current[0], candidates=current)
    return _result(MAPPING_AMBIGUOUS, candidates=current)
