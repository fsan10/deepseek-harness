"""Pure report contracts migrated from jd_promotion_fee_webapi_download.py; no browser implementation."""
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

UNION_REPORT_NAME = "结算信息"

UNION_MODULE_TYPE = 2

TONG_REPORT_NAME = "财务记录_消费记录_现金"

TONG_REPORT_TYPE = 24

def build_union_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page_index: int = 1,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "dateType": 2,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "endDateForSubmit": end.isoformat(),
            "billStatus": 2,
            "pageIndex": page_index,
            "pageSize": 10,
            "withDailyData": 0,
        }
    )
    return payload

def build_union_generate_payload(start: date, end: date) -> dict[str, Any]:
    return {
        "moduleType": UNION_MODULE_TYPE,
        "reportName": UNION_REPORT_NAME,
        "payStatus": 2,
        "withDailyData": 0,
        "finishStartTime": start.isoformat(),
        "finishEndTime": end.isoformat(),
    }

def build_union_task_payload(page_index: int = 1) -> dict[str, Any]:
    return {"pageIndex": page_index, "pageSize": 10}

def build_union_download_payload(pk: int) -> dict[str, Any]:
    return {"pk": int(pk)}

def union_query_total(body: dict[str, Any]) -> int:
    content = body.get("content")
    if not isinstance(content, dict):
        content = body.get("data")
    if not isinstance(content, dict):
        raise ApiError("京东联盟推广费查询缺少 content/data 对象", body=body)
    return as_int(content.get("total"), 0)

def union_task_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content = body.get("content")
    if not isinstance(content, dict):
        content = body.get("data")
    if not isinstance(content, dict):
        raise ApiError("京东联盟任务列表缺少 content/data 对象", body=body)
    rows = content.get("data")
    if not isinstance(rows, list):
        raise ApiError("京东联盟任务列表缺少 data 数组", body=body)
    return [row for row in rows if isinstance(row, dict)], content

def select_union_task(
    rows: list[dict[str, Any]],
    *,
    submitted_after_ms: int,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("reportName") or "") == UNION_REPORT_NAME
        and as_int(row.get("moduleType"), -1) == UNION_MODULE_TYPE
        and as_int(row.get("insertTime"), 0) >= submitted_after_ms - 60_000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: as_int(row.get("insertTime"), 0))

def build_tong_query_payload(
    template: dict[str, Any],
    start: date,
    end: date,
    *,
    page: int = 1,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "beginDate": start.isoformat(),
            "endDate": end.isoformat(),
            "page": page,
            "pageSize": 10,
            "timeFilterType": 1,
            "invoiceApplyType": 0,
        }
    )
    return payload

def build_tong_export_payload(query_payload: dict[str, Any]) -> dict[str, Any]:
    payload = clone_payload(query_payload)
    payload["downloadName"] = TONG_REPORT_NAME
    return payload

def build_tong_report_payload(end: date) -> dict[str, Any]:
    # 报表历史页只需覆盖最近半年即可找到刚创建的任务；最终仍按精确
    # 报表名称、类型、起止日期和创建时间匹配。
    start = end - timedelta(days=184)
    return {
        "page": 1,
        "pageSize": 10,
        "startDay": start.isoformat(),
        "endDay": end.isoformat(),
        "nameLike": "",
        "type": TONG_REPORT_TYPE,
    }

def tong_report_rows(body: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise ApiError("京东通报表列表缺少 data 对象", body=body)
    rows = data.get("datas")
    if not isinstance(rows, list):
        raise ApiError("京东通报表列表缺少 datas 数组", body=body)
    return [row for row in rows if isinstance(row, dict)], data

def _created_ms(value: Any) -> int:
    text = str(value or "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN_TZ)
    except ValueError:
        return 0
    return int(parsed.timestamp() * 1000)

def select_tong_report(
    rows: list[dict[str, Any]],
    *,
    start: date,
    end: date,
    submitted_after_ms: int,
) -> dict[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("reportName") or "") == TONG_REPORT_NAME
        and as_int(row.get("type"), -1) == TONG_REPORT_TYPE
        and str(row.get("startDay") or "") == start.isoformat()
        and str(row.get("endDay") or "") == end.isoformat()
        and _created_ms(row.get("createdTime")) >= submitted_after_ms - 60_000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: _created_ms(row.get("createdTime")))
