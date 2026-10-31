"""Pure report contracts migrated from xiaohongshu_fund_webapi_download.py; no browser implementation."""
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

def build_period_payload(
    mode: str,
    start_time: str,
    end_time: str,
    *,
    page_num: int = 1,
    page_size: int = 100,
) -> dict[str, Any]:
    return {
        "periodType": mode.upper(),
        "timeType": "COMPLETE_TIME",
        "startTime": start_time,
        "endTime": end_time,
        "pageNum": page_num,
        "pageSize": page_size,
    }

def row_period_key(row: dict[str, Any], mode: str) -> str:
    start_key = parse_period_key(row.get("startTime"))
    bill_key = parse_period_key(row.get("billDate"))
    if mode == "month":
        return (start_key or bill_key)[:7]
    return start_key or bill_key

def select_period_row(
    rows: list[dict[str, Any]], mode: str, requested: date | None
) -> dict[str, Any] | None:
    expected = (
        requested.isoformat()
        if requested is not None and mode == "day"
        else requested.strftime("%Y-%m") if requested is not None else None
    )
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("periodType") or "").upper() != mode.upper():
            continue
        status = str(row.get("processStatus") or "").upper()
        if status and status not in {"SUCCESS", "SUCCEED", "FINISH", "FINISHED"}:
            continue
        if expected is not None and row_period_key(row, mode) != expected:
            continue
        if row.get("periodFundNo"):
            candidates.append(row)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            row_period_key(row, mode),
            str(row.get("processFinishTime") or row.get("updateTime") or ""),
        ),
    )
