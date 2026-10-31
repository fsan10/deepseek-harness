"""Pure report contracts migrated from jd_fund_webapi_download.py; no browser implementation."""
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

TASK_TYPE = 13

def build_query_payload(template: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    """保留页面自然请求中的店铺上下文，只替换日期和分页。"""

    payload = clone_payload(template)
    query = payload.setdefault("capitalFlowQueryMo", {})
    query.update(
        {
            "pageNo": 1,
            "pageSize": 10,
            "startDate": f"{start.isoformat()} 00:00:00",
            "endDate": f"{end.isoformat()} 23:59:59",
            "beginEndDate": sff_utc_bounds(start, end),
        }
    )
    payload.setdefault("accessContext", {"source": "web"})
    return payload

def build_create_payload(query_payload: dict[str, Any], start: date, end: date) -> dict[str, Any]:
    query = query_payload.get("capitalFlowQueryMo")
    if not isinstance(query, dict):
        raise ValueError("资金流水查询模板缺少 capitalFlowQueryMo")
    condition = {
        "exportType": str(TASK_TYPE),
        "orgCode": query.get("orgCode"),
        "outTradeNo": None,
        "startDate": None,
        "tradeNo": None,
        "endDate": None,
        "beginEndDate": sff_utc_bounds(start, end, with_milliseconds=True),
        "startTime": f"{start.isoformat()} 00:00:00",
        "endTime": f"{end.isoformat()} 23:59:59",
    }
    return {
        "request": {
            "data": {
                "conditionBody": json.dumps(
                    condition,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                "taskType": TASK_TYPE,
                "terminal": 1,
            }
        },
        "accessContext": {"source": "web"},
    }

def build_task_list_payload(page_num: int = 1) -> dict[str, Any]:
    return {
        "request": {
            "data": {
                "pageNum": page_num,
                "pageSize": 10,
                "taskType": TASK_TYPE,
            }
        },
        "accessContext": {"source": "web"},
    }

def response_task_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("资金导出任务列表缺少 data 对象", body=body)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ApiError("资金导出任务列表缺少 data.data", body=body)
    return [row for row in rows if isinstance(row, dict)], data

def select_task(
    rows: list[dict[str, Any]],
    *,
    task_id: str,
    condition_body: str,
) -> dict[str, Any] | None:
    exact = [row for row in rows if str(row.get("id") or "") == task_id]
    if exact:
        return exact[0]
    candidates = [
        row
        for row in rows
        if int(row.get("taskType") or 0) == TASK_TYPE
        and str(row.get("conditionBody") or "") == condition_body
    ]
    return candidates[0] if candidates else None
