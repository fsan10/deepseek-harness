"""Pure report contracts migrated from kuaishou_fund_webapi_download.py; no browser implementation."""
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


def response_payload(body, *, label):
    if "data" not in body:
        raise ApiError(label + "缺少 data")
    return body["data"]

ACCOUNT_TYPE = "ACCOUNT_TYPE_WALLET_PINGAN"

ACCOUNT_ROLE = "ACCOUNT_ROLE_SELLER"

BID_BIZ_TYPE = "seller_or_promoter"

TASK_KIND = 10000

DAY_BILL_TYPE = "BY_DAY"

MONTH_BILL_TYPE = "BY_MONTH"

DAY_KEY_RE = re.compile(r"^\d{8}$")

MONTH_KEY_RE = re.compile(r"^\d{6}$")

def fund_period_key(value: date, mode: str) -> str:
    return value.strftime("%Y%m" if mode == "month" else "%Y%m%d")

def build_statistic_payload(
    template: dict[str, Any],
    mode: str,
    start: date,
    end: date,
    sub_mch_id: str,
) -> dict[str, Any]:
    payload = clone_payload(template)
    payload.update(
        {
            "accountType": ACCOUNT_TYPE,
            "accountRole": ACCOUNT_ROLE,
            "billType": DAY_BILL_TYPE if mode == "day" else MONTH_BILL_TYPE,
            "subMchId": str(sub_mch_id),
            "startTime": date_to_ms(start, end_of_day=False),
            "endTime": date_to_ms(end, end_of_day=True, end_millisecond=999),
            "bidBizType": BID_BIZ_TYPE,
        }
    )
    return payload

def fund_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = response_payload(body, label="资金统计")
    if not isinstance(value, list):
        raise ApiError("资金统计返回的 data 不是数组", body=body)
    rows = [item for item in value if isinstance(item, dict)]
    if len(rows) != len(value):
        raise ApiError("资金统计返回包含非对象账单行", body=body)
    return rows

def row_period_key(row: dict[str, Any], mode: str) -> str:
    value = str(row.get("date") or "").strip()
    pattern = MONTH_KEY_RE if mode == "month" else DAY_KEY_RE
    return value if pattern.fullmatch(value) else ""

def select_fund_row(
    rows: list[dict[str, Any]],
    mode: str,
    requested: date | None,
) -> dict[str, Any] | None:
    expected = fund_period_key(requested, mode) if requested is not None else None
    candidates = [
        row
        for row in rows
        if row_period_key(row, mode)
        and (expected is None or row_period_key(row, mode) == expected)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row_period_key(row, mode))

def select_account(
    accounts: list[dict[str, Any]],
    explicit_sub_mch_id: str | None = None,
) -> dict[str, Any]:
    candidates = [
        account
        for account in accounts
        if isinstance(account, dict) and str(account.get("subMchId") or "").strip()
    ]
    if explicit_sub_mch_id:
        expected = str(explicit_sub_mch_id).strip()
        matches = [item for item in candidates if str(item.get("subMchId")) == expected]
        if not matches:
            raise ApiError(f"资金账户中不存在指定二级商户号：{expected}")
        return matches[0]

    enabled = [
        item
        for item in candidates
        if str(item.get("bindState") or "").upper() == "ENABLE"
        and str(item.get("accountState") or "").upper() == "NORMAL"
    ]
    if len(enabled) == 1:
        return enabled[0]
    if len(enabled) > 1:
        ids = ", ".join(str(item.get("subMchId")) for item in enabled)
        raise ApiError(f"当前 Profile 有多个可用资金账户，请使用 --sub-mch-id 指定：{ids}")
    if len(candidates) == 1:
        return candidates[0]
    raise ApiError("未找到唯一可用资金账户，请检查权限或使用 --sub-mch-id 指定")

def extract_operator_name(text: str) -> str:
    match = re.search(r"(?:账号?\s*)?ID\s*[：:]\s*(\d+)", text or "", flags=re.IGNORECASE)
    if not match:
        raise ApiError("快手资金页未识别当前操作员 ID，无法安全创建导出任务")
    return match.group(1)

def build_create_task_payload(
    account: dict[str, Any],
    operator_name: str,
    period_start: date,
    period_end: date,
    mode: str,
) -> dict[str, Any]:
    sub_mch_id = str(account.get("subMchId") or "").strip()
    if not sub_mch_id:
        raise ValueError("资金账户缺少 subMchId")
    export_config = {
        "startTime": date_to_ms(period_start, end_of_day=False),
        "endTime": date_to_ms(period_end, end_of_day=True, end_millisecond=999),
        "subMchId": sub_mch_id,
        "dateType": 1 if mode == "day" else 2,
    }
    return {
        "accountType": ACCOUNT_TYPE,
        "accountRole": ACCOUNT_ROLE,
        "operatorName": str(operator_name),
        "taskKind": TASK_KIND,
        "exportConfig": json.dumps(export_config, ensure_ascii=False, separators=(",", ":")),
        "bidBizType": BID_BIZ_TYPE,
    }

def build_list_task_payload(sub_mch_id: str) -> dict[str, Any]:
    return {
        "accountType": ACCOUNT_TYPE,
        "accountRole": ACCOUNT_ROLE,
        "subMchId": str(sub_mch_id),
        "size": 10,
        "page": 1,
        "taskKind": TASK_KIND,
        "bidBizType": BID_BIZ_TYPE,
    }

def parse_export_config(value: Any) -> dict[str, Any] | None:
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
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        with suppress(ValueError):
            return int(
                datetime.strptime(text[:19], fmt)
                .replace(tzinfo=CN_TZ)
                .timestamp()
                * 1000
            )
    with suppress(ValueError):
        number = int(text)
        return number if number > 10_000_000_000 else number * 1000
    return 0

def fund_task_records(body: dict[str, Any]) -> list[dict[str, Any]]:
    value = body.get("exportTaskRecord")
    if not isinstance(value, list):
        raise ApiError("资金导出任务返回缺少 exportTaskRecord 数组", body=body)
    records = [item for item in value if isinstance(item, dict)]
    if len(records) != len(value):
        raise ApiError("资金导出任务包含非对象记录", body=body)
    return records

def select_fund_task(
    records: list[dict[str, Any]],
    expected_period: str,
    *,
    submitted_after_ms: int = 0,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for record in records:
        if as_int(record.get("taskKind"), -1) != TASK_KIND:
            continue
        config = parse_export_config(record.get("exportConfig"))
        if not config:
            continue
        if str(config.get("startTime") or "") != expected_period:
            continue
        if str(config.get("endTime") or "") != expected_period:
            continue
        created = _task_time_ms(record.get("createTime"))
        if submitted_after_ms and created and created < submitted_after_ms - 120_000:
            continue
        matches.append(record)
    matches.sort(key=lambda item: _task_time_ms(item.get("createTime")), reverse=True)
    if not matches:
        return None
    newest = matches[0]
    status = as_int(newest.get("status"), -1)
    if status == 2:
        return newest
    if status in {3, 4, 5, -1} and str(newest.get("failedReason") or "").strip():
        raise ApiError(f"资金导出任务失败：{newest.get('failedReason')}")
    return None

def fund_download_url(body: dict[str, Any]) -> str | None:
    value = body.get("downloadUrl")
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise ApiError("资金创建任务返回了无效下载地址", body=body)
    return value
