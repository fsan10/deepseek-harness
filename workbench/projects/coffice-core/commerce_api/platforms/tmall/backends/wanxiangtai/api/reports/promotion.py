"""Pure report contracts migrated from tmall_promotion_webapi_download.py; no browser implementation."""
from __future__ import annotations

import copy
import json
import math
import re
from commerce_api.core.parsing import parse_date
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

def _wanxiang_params(template_url: str, target_date: str) -> dict[str, str]:
    values = dict(parse_qsl(urlsplit(template_url).query, keep_blank_values=True))
    values.update(
        {
            "beginTime": target_date,
            "endTime": target_date,
            "offset": "0",
            "limit": "20",
            "timeType": "acount",
            "tradeType": "DEDUCT",
        }
    )
    return values

def _wanxiang_target_url(target_date: str) -> str:
    target = parse_date(target_date, option_name="万相台目标日期")
    query = urlencode(
        {
            "spm": "",
            "costStartTime": target.replace(day=1).isoformat(),
            "costEndTime": target.isoformat(),
            "detailTab": "cash",
            "time": "acount",
            "currentPage": "1",
            "trade": "DEDUCT",
            "cashStart": target.isoformat(),
            "cashEnd": target.isoformat(),
        }
    )
    return f"https://one.alimama.com/index.html#!/account/detail?{query}"
