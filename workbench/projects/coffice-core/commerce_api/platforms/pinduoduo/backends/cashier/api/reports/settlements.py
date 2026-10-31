"""Pure report contracts migrated from pdd_settlement_webapi_download.py; no browser implementation."""
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

def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value

def build_filter_payload(start_ts: int, end_ts: int) -> dict[str, Any]:
    # 这些字段对应 bills chunk 中页面状态 g 的默认筛选值。
    return {
        "beginTime": start_ts,
        "endTime": end_ts,
        "groupType": 0,
        "classList": [],
        "minAmount": None,
        "maxAmount": None,
        "orderSn": None,
    }

def build_list_payload(filters: dict[str, Any], page_num: int = 1, page_size: int = 20) -> dict[str, Any]:
    # pagingQueryMallBalanceBillListForMms 当前页面自然请求的字段。
    return {
        "classList": filters["classList"],
        "signTypeList": [],
        "inclusiveBeginTime": filters["beginTime"],
        "exclusiveEndTime": filters["endTime"],
        "inclusiveMinAmount": filters["minAmount"],
        "inclusiveMaxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "pageNum": page_num,
        "pageSize": page_size,
    }

def build_statistics_payload(
    filters: dict[str, Any], page_num: int = 1, page_size: int = 20
) -> dict[str, Any]:
    # queryBillStatistics 当前页面自然请求的字段。
    return {
        "classList": filters["classList"],
        "groupType": filters["groupType"],
        "beginTime": filters["beginTime"],
        "endTime": filters["endTime"],
        "minAmount": filters["minAmount"],
        "maxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "offset": (page_num - 1) * page_size,
        "limit": page_size,
    }

def build_create_task_payload(filters: dict[str, Any]) -> dict[str, Any]:
    return {
        "beginTime": filters["beginTime"],
        "endTime": filters["endTime"],
        "groupType": filters["groupType"],
        "classList": filters["classList"],
        "minAmount": filters["minAmount"],
        "maxAmount": filters["maxAmount"],
        "orderSn": filters["orderSn"],
        "isHistory": True,
    }

def find_rows(result: Any) -> list[Any]:
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    for key in ("billList", "pageItems", "items", "records", "list", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return value
    return []

def find_task_items(result: Any) -> list[dict[str, Any]]:
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if not isinstance(result, dict):
        return []
    for key in ("pageItems", "items", "records", "list", "taskList", "data"):
        value = result.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []

def as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def result_count(result: Any) -> int:
    """取得账单查询条数，用于决定是否创建导出任务。"""
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("total", "totalCount", "count"):
            if key in result:
                value = as_int(result.get(key))
                if value is not None:
                    if value < 0:
                        raise ApiError("账单查询条数不能为负数")
                    return value
        for key in ("billList", "pageItems", "items", "records", "list", "data"):
            if isinstance(result.get(key), list):
                return len(result[key])
    raise ApiError("账单查询结果缺少 total 或明细数组")

def task_query(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("queryJsonString")
    parsed = parse_json_value(raw)
    if isinstance(parsed, str):
        parsed = parse_json_value(parsed)
    return parsed if isinstance(parsed, dict) else {}

def task_range_matches(item: dict[str, Any], start_ts: int, end_ts: int) -> bool:
    query = task_query(item)
    begin = query.get("beginTime", item.get("beginTime"))
    end = query.get("endTime", item.get("endTime"))
    return as_int(begin) == start_ts and as_int(end) == end_ts
