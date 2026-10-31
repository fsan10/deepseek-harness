"""Small pure parsing primitives shared by platform-specific contracts."""
from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime, time, timedelta, timezone

from .contracts import CN
from .errors import ContractError

CN_TZ = TZ_CN = CN


class ApiError(ContractError):
    def __init__(self, message, *, body=None, path="", status=None):
        super().__init__(message, stage="response", details={"path": path, "http_status": status} if path or status else {})


def clone_payload(value):
    return copy.deepcopy(value)


def as_int(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def date_to_ms(value: date, *, end_of_day=False, end_millisecond=0):
    target = datetime.combine(value, time(23, 59, 59) if end_of_day else time.min, CN)
    return int(target.timestamp() * 1000) + (end_millisecond if end_of_day else 0)


def sff_utc_bounds(start: date, end: date, *, with_milliseconds=False):
    first = datetime.combine(start, time.min, CN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    last = datetime.combine(end, time(23, 59, 59, 999000), CN).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.999Z")
    return [first + (".000Z" if with_milliseconds else "Z"), last]


def parse_period_key(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)) or str(value).isdigit() and len(str(value)) >= 10:
        numeric = float(value)
        return datetime.fromtimestamp(numeric / 1000 if numeric > 100000000000 else numeric, CN).date().isoformat()
    text = str(value)
    match = re.search(r"(20\d{2})[-/年]?(\d{2})(?:[-/月]?(\d{2}))?", text)
    return "-".join(x for x in match.groups() if x) if match else ""


def parse_json_value(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return None


def require_dict(value, label="响应数据"):
    if not isinstance(value, dict):
        raise ContractError(label + "缺少对象结构", stage="response")
    return value


def require_rows(value, label="响应数据"):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ContractError(label + "缺少有效明细数组", stage="response")
    return value


def parse_date(value, *, option_name="日期"):
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
        raise ValueError(option_name + "须为 YYYY-MM-DD")
    return date.fromisoformat(value)
