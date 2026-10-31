"""Pure report contracts migrated from tmall_fund_webapi_download.py; no browser implementation."""
from __future__ import annotations

import copy
import json
import math
import re
import time
from email.utils import format_datetime
from datetime import time as day_time
from commerce_api.core.parsing import parse_date
from commerce_api.core.errors import NeedsHuman as NeedsHumanError
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

ALIPAY_DAILY_PATH = "/enterprise/dailyBillQuery.resource"

ALIPAY_SECURITY_PATH = "/enterprise/entAsyncSecurityCheck.json"

ALIPAY_SECURITY_BIZ_TYPE = "SECURITY_PRODUCT_BILL_DOWNLOAD"

def _alipay_success(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ApiError("支付宝资金查询响应结构异常")
    if str(body.get("success", "")).lower() != "true" or body.get("status") != "succeed":
        message = body.get("message") or body.get("outputMsg") or "未知错误"
        if any(x in str(message) for x in ("登录", "验证", "权限")):
            raise NeedsHumanError(f"支付宝资金接口返回人工处理状态：{str(message)[:120]}")
        raise ApiError(f"支付宝资金查询失败：{str(message)[:160]}")
    return body

def alipay_day_times(target_date: str) -> tuple[str, str]:
    """页面以 GMT 字符串传输中国自然日的闭区间。"""
    target = parse_date(target_date, option_name="支付宝目标日期")
    start = datetime.combine(target, day_time.min, tzinfo=TZ_CN)
    end = start + timedelta(days=1, seconds=-1)
    return tuple(format_datetime(value.astimezone(timezone.utc), usegmt=True) for value in (start, end))

def alipay_query_form(template: dict[str, str], target_date: str) -> dict[str, str]:
    parse_date(target_date, option_name="支付宝目标日期")
    if not template.get("billUserId"):
        raise ApiError("支付宝资金自然请求缺少 billUserId")
    result = dict(template)
    result.update(startDate=target_date, endDate=target_date, pageNum="1")
    return result

def alipay_security_request(template_url: str, target_date: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(template_url)
    csrf = dict(parse_qsl(parsed.query)).get("ctoken")
    if parsed.scheme != "https" or parsed.hostname != "mbillexprod.alipay.com" or not csrf:
        raise ApiError("支付宝当前 Target 缺少安全校验请求上下文")
    start, end = alipay_day_times(target_date)
    url = urlunsplit((parsed.scheme, parsed.netloc, ALIPAY_SECURITY_PATH,
                      urlencode({"ctoken": csrf, "_output_charset": "utf-8"}), ""))
    return url, {"securityBizType": ALIPAY_SECURITY_BIZ_TYPE, "beginDate": start,
                 "endDate": end, "_input_charset": "gbk"}

def alipay_security_id(body: Any) -> str:
    if not isinstance(body, dict):
        raise ApiError("支付宝安全校验响应结构异常")
    if body.get("securityStatus") != "succeed":
        raise NeedsHumanError("支付宝安全校验未通过，请在当前 Profile 完成人工验证")
    value = body.get("securityId")
    if not isinstance(value, str) or not value:
        raise ApiError("支付宝安全校验成功但未返回下载上下文")
    return value

def alipay_download_url(template_url: str, form: dict[str, str], target_date: str,
                        security_id: str, *, timestamp_ms: int | None = None) -> str:
    parsed = urlsplit(template_url)
    if parsed.scheme != "https" or parsed.hostname != "mbillexprod.alipay.com":
        raise ApiError("支付宝下载请求来源异常")
    if not form.get("billUserId") or not security_id:
        raise ApiError("支付宝下载请求缺少账户或安全上下文")
    start, end = alipay_day_times(target_date)
    query = {"_t": str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)),
             "billTypeList": "signcustomer", "billUserId": form["billUserId"],
             "bizDate": target_date, "endTime": end, "forceAync": "0",
             "querySettleAccount": form.get("querySettleAccount", "false"),
             "securityBizType": ALIPAY_SECURITY_BIZ_TYPE, "securityId": security_id,
             "startTime": start}
    return urlunsplit((parsed.scheme, parsed.netloc, ALIPAY_DAILY_PATH, urlencode(query), ""))

def _alipay_true(value: Any) -> bool:
    return str(value).lower() in {"true", "1"}

def alipay_target_row(body: Any, target_date: str) -> dict[str, Any] | None:
    result = _alipay_success(body).get("result")
    rows = result.get("dateDtls") if isinstance(result, dict) else None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ApiError("支付宝资金查询缺少账期列表")
    matches = [row for row in rows if row.get("bizDate") == target_date]
    if len(matches) > 1:
        raise ApiError("支付宝资金查询返回重复目标账期")
    if not matches or any(_alipay_true(matches[0].get(key)) for key in ("noData", "emptyData")):
        return None
    row = matches[0]
    if not _alipay_true(row.get("downloadable")) or _alipay_true(row.get("processing")):
        raise ApiError(f"支付宝目标日尚未生成可下载账单：{target_date}")
    return row
