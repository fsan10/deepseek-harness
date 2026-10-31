"""Pure report contracts migrated from kuaishou_settlement_webapi_download.py; no browser implementation."""
from __future__ import annotations

import copy
import json
import math
import re
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

API_ORIGIN = "https://s.kwaixiaodian.com"

DOWNLOAD_PATH = "/rest/app/tts/financial/center/bill/download"

DOWNLOAD_URL = API_ORIGIN + DOWNLOAD_PATH

SETTLEMENT_TYPE = "SELLER_SETTLED_ORDER_V2"

BID_BIZ_TYPE = "seller_or_promoter"

CHANNELS = ("WECHAT", "ALIPAY_ZFT", "BALANCE", "PINGAN_JZB")

def build_query_payload(
    template: dict[str, Any] | None,
    start: date,
    end: date,
    *,
    page: int = 1,
    limit: int = 10,
) -> dict[str, Any]:
    payload = clone_payload(template or {})
    payload.update(
        {
            "limit": int(limit),
            "page": int(page),
            "settlementStatus": ["COMPLETED"],
            # 结算接口抓包使用整秒结束边界（.000），不能复用资金接口
            # 的 .999 边界。
            "settlementTimeGte": date_to_ms(start, end_of_day=False),
            "settlementTimeLte": date_to_ms(end, end_of_day=True, end_millisecond=0),
            "accountChannel": list(CHANNELS),
        }
    )
    return payload

def build_create_payload(query_payload: dict[str, Any]) -> dict[str, Any]:
    required = ("settlementTimeGte", "settlementTimeLte")
    if any(key not in query_payload for key in required):
        raise ValueError("结算创建任务缺少日期边界")
    channels = query_payload.get("accountChannel")
    if not isinstance(channels, list) or not channels:
        raise ValueError("结算创建任务缺少账户渠道")
    ext_params = {
        "page": as_int(query_payload.get("page"), 1),
        "limit": as_int(query_payload.get("limit"), 10),
        "settlementTimeGte": as_int(query_payload.get("settlementTimeGte"), -1),
        "settlementTimeLte": as_int(query_payload.get("settlementTimeLte"), -1),
        "accountChannel": ",".join(str(item) for item in channels),
    }
    if ext_params["settlementTimeGte"] < 0 or ext_params["settlementTimeLte"] < 0:
        raise ValueError("结算创建任务日期边界无效")
    return {
        "extParams": json.dumps(ext_params, ensure_ascii=False, separators=(",", ":")),
        "type": SETTLEMENT_TYPE,
    }

def build_list_payload(*, page: int = 1, limit: int = 20) -> dict[str, Any]:
    return {
        "page": int(page),
        "limit": int(limit),
        "type": SETTLEMENT_TYPE,
        "bidBizType": BID_BIZ_TYPE,
    }

def parse_ext_param(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return clone_payload(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None

def _task_time_ms(value: Any) -> int:
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    text = str(value or "").strip()
    if not text:
        return 0
    with suppress(ValueError):
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000
    return 0

def _same_ext_params(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    keys = ("page", "limit", "settlementTimeGte", "settlementTimeLte", "accountChannel")
    return all(str(actual.get(key)) == str(expected.get(key)) for key in keys)

def select_settlement_task(
    file_items: list[dict[str, Any]],
    query_payload: dict[str, Any],
    *,
    submitted_after_ms: int = 0,
) -> dict[str, Any] | None:
    expected = parse_ext_param(build_create_payload(query_payload)["extParams"])
    if expected is None:
        raise ValueError("结算创建任务 extParams 生成失败")
    matches: list[dict[str, Any]] = []
    for item in file_items:
        if str(item.get("bizSubType") or "") != SETTLEMENT_TYPE:
            continue
        actual = parse_ext_param(item.get("extParam"))
        if actual is None or not _same_ext_params(actual, expected):
            continue
        created = _task_time_ms(item.get("createTime"))
        if submitted_after_ms and created and created < submitted_after_ms - 120_000:
            continue
        matches.append(item)
    matches.sort(key=lambda item: _task_time_ms(item.get("createTime")), reverse=True)
    if not matches:
        return None
    newest = matches[0]
    status = as_int(newest.get("status"), -1)
    if status == 30:
        return newest
    if status in {40, 50, -1}:
        reason = str(newest.get("failedReason") or "").strip()
        if reason:
            raise ApiError(f"结算导出任务失败：{reason}")
    return None

def file_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("fileItems")
    if not isinstance(value, list):
        raise ApiError("结算导出任务返回缺少 fileItems 数组", body=body)
    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value):
        raise ApiError("结算导出任务包含非对象记录", body=body)
    return items

def build_download_url(file_id: Any) -> str:
    value = str(file_id or "").strip()
    if not re.fullmatch(r"\d+", value):
        raise ApiError("结算导出任务缺少有效 fileId")
    return f"{DOWNLOAD_URL}?{urlencode({'fileId': value})}"
