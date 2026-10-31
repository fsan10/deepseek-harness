"""Pure report contracts migrated from douyin_settlement_webapi_download.py; no browser implementation."""
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

DOWNLOAD_TYPE = "SHOP_SETTLE_ORDERS"

TIME_TYPE = "SETTLE"

def build_query_payload(
    start_time: str,
    end_time: str,
    *,
    page: int = 0,
    size: int = 50,
) -> dict[str, Any]:
    """构造结算汇总查询 payload。"""

    return {
        "start_time": start_time,
        "end_time": end_time,
        "request_type": 1,
        "page": page,
        "size": size,
        "query_type": "SHOP_SETTLE_BILLS",
    }

def build_export_payload(start_time: str, end_time: str) -> dict[str, Any]:
    return {
        "start_time": start_time,
        "end_time": end_time,
        "download_type": DOWNLOAD_TYPE,
        "time_type": TIME_TYPE,
    }
