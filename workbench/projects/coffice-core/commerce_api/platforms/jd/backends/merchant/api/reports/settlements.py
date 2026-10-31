"""Pure report contracts migrated from jd_settlement_webapi_download.py; no browser implementation."""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

def build_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page_num: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    payload = clone_payload(template)
    query = payload.setdefault("daybillMo", {})
    query.update(
        {
            "setDateBegin": f"{start.isoformat()} 00:00:00",
            "setDateEnd": f"{end.isoformat()} 23:59:59",
            "pageNum": page_num,
            "pageSize": page_size,
        }
    )
    return payload

def build_detail_payload(
    query_payload: dict[str, Any],
    row_id: int,
    start: date,
    end: date,
) -> dict[str, Any]:
    query = query_payload.get("daybillMo")
    if not isinstance(query, dict):
        raise ValueError("结算账单查询模板缺少 daybillMo")
    detail = clone_payload(query_payload)
    detail_query = detail.setdefault("daybillMo", {})
    detail_query.update(
        {
            "setDateBegin": date_to_ms(start, end_of_day=False),
            "setDateEnd": date_to_ms(end, end_of_day=True),
            "pageNum": 1,
            "pageSize": 10,
            "ids": [int(row_id)],
        }
    )
    return detail

def row_business_date(row: dict[str, Any]) -> str:
    # The existing DOM flow labels/archives [col-id=setDate]. accDate is the
    # following accounting day and must never replace the bill's business day.
    for key in ("setDate", "businessDate", "accountDate"):
        value = str(row.get(key) or "")
        if len(value) == 8 and value.isdigit():
            return f"{value[:4]}-{value[4:6]}-{value[6:]}"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T].*)?", value):
            return value[:10]
    return ""

def select_settlement_row(
    rows: list[dict[str, Any]], requested: date | None
) -> dict[str, Any] | None:
    expected = requested.isoformat() if requested is not None else None
    candidates = [
        row
        for row in rows
        if row_business_date(row)
        and (expected is None or row_business_date(row) == expected)
        and row.get("id") not in (None, "")
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (row_business_date(row), str(row.get("accDate") or "")),
    )

def response_settlement_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("结算账单查询缺少 data 对象", body=body)
    rows = data.get("content")
    if not isinstance(rows, list):
        raise ApiError("结算账单查询缺少 data.content", body=body)
    return [row for row in rows if isinstance(row, dict)], data
