"""Pure report contracts migrated from tmall_order_webapi_download.py; no browser implementation."""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from commerce_api.core.parsing import parse_date
from commerce_api.core.errors import NeedsHuman as NeedsHumanError
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit, urlparse

from commerce_api.core.parsing import (ApiError, CN_TZ, TZ_CN, as_int, clone_payload,
    date_to_ms, parse_period_key, parse_json_value, sff_utc_bounds)

ORDER_EXPORT_PATH = "/trade/itemlist/export_by_tfs.do"

TZ_CN = timezone(timedelta(hours=8))

def _timestamp_ms(value: str, *, end_of_day: bool) -> str:
    parsed = parse_date(value, option_name="订单日期")
    moment = datetime.combine(
        parsed,
        dt_time(23, 59, 59) if end_of_day else dt_time(0, 0, 0),
        tzinfo=TZ_CN,
    )
    return str(int(moment.timestamp() * 1000))

def _fallback_query_form(start_date: str, end_date: str) -> dict[str, str]:
    """自然请求暂未出现时的最小稳定表单；正常运行优先使用自然表单。"""

    return {
        "isQnNew": "true",
        "isHideNick": "true",
        "prePageNo": "1",
        "sifg": "0",
        "action": "itemlist/SoldQueryAction",
        "close": "0",
        "pageNum": "1",
        "tabCode": "latest3Months",
        "useCheckcode": "false",
        "errorCheckcode": "false",
        "payDateBegin": "0",
        "payDateEnd": "0",
        "rateStatus": "ALL",
        "orderStatus": "ALL",
        "pageSize": "15",
        "dateBegin": _timestamp_ms(start_date, end_of_day=False),
        "dateEnd": _timestamp_ms(end_date, end_of_day=True),
        "queryMore": "true",
        "refund": "ALL",
        "queryOrder": "desc",
        "deliveryTimeType": "ALL",
        "payMethodType": "ALL",
        "orderType": "ALL",
        "notifySendGoodsType": "ALL",
        "o2oDeliveryType": "ALL",
        "logisticsService": "ALL",
        "auctionType": "0",
        "holdStatus": "0",
        "tradeTag": "0",
        "unionSearchPageNum": "0",
        "unionSearchTotalNum": "0",
    }

def _with_order_dates(form: dict[str, str], start_date: str, end_date: str) -> dict[str, str]:
    result = dict(form)
    result["dateBegin"] = _timestamp_ms(start_date, end_of_day=False)
    result["dateEnd"] = _timestamp_ms(end_date, end_of_day=True)
    result.setdefault("pageNum", "1")
    result.setdefault("pageSize", "15")
    return result

def order_count(body: Any) -> int:
    if not isinstance(body, dict):
        raise ApiError("订单查询响应结构异常")
    if body.get("error"):
        message = str(body.get("error"))
        if any(x in message for x in ("登录", "验证", "权限")):
            raise NeedsHumanError(message[:160])
        raise ApiError(f"订单查询失败：{message[:160]}")
    page = body.get("page")
    if isinstance(page, dict):
        if "totalNumber" not in page:
            raise ApiError("订单查询缺少权威 totalNumber")
        try:
            count = int(page["totalNumber"])
        except (TypeError, ValueError) as exc:
            raise ApiError("订单查询 totalNumber 不是整数") from exc
        if count < 0:
            raise ApiError("订单查询 totalNumber 为负数")
        return count
    orders = body.get("mainOrders")
    if not isinstance(orders, list):
        raise ApiError("订单查询缺少权威数量和明细数组")
    return len(orders)

def _record_range(record: dict[str, Any]) -> tuple[str | None, str | None]:
    return record.get("startTimeStr"), record.get("endTimeStr")

def matching_export_record(
    body: Any,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    data = body.get("data", {}) if isinstance(body, dict) else {}
    records = data.get("detailList", []) if isinstance(data, dict) else []
    expected_start = f"{start_date} 00:00:00"
    expected_end = f"{end_date} 23:59:59"
    for record in records:
        if not isinstance(record, dict):
            continue
        start, end = _record_range(record)
        if start != expected_start or end != expected_end:
            continue
        path = str(record.get("itemEncrypterStr") or "")
        export_type = str(record.get("exportType") or "").lower()
        if export_type:
            # 宝贝销售明细为 exportType=2。处理中尚无文件路径，
            # 仍须复用原任务，不能再次创建。
            if export_type != "2":
                continue
        elif not path:
            continue
        return record
    return None

def ready_export_record(
    body: Any,
    start_date: str,
    end_date: str,
) -> dict[str, Any] | None:
    record = matching_export_record(body, start_date, end_date)
    if record is None:
        return None
    status = str(record.get("exportStatus") or "").lower()
    return record if status in {"exportsuccess", "success", "done", "complete"} else None

def export_download_url(record: dict[str, Any]) -> str:
    if str(record.get("exportType")) != "2":
        raise ApiError("当前能力只下载宝贝销售明细报表")
    encrypted_path = str(record.get("itemEncrypterStr") or "")
    export_id = str(record.get("exportId") or "")
    if not encrypted_path or not export_id:
        error = ApiError("订单导出成功记录缺少文件路径或 exportId")
        error.details = {"available_fields": list(record)}
        raise error
    params = {
        "f_p": encrypted_path,
        "apply_time": str(record.get("applyTime") or ""),
        "start_time": str(record.get("startTimeStr") or ""),
        "end_time": str(record.get("endTimeStr") or ""),
        "order_status": str(record.get("orderStatus") or "全部"),
        "export_id": export_id,
        "isQnNew": "true",
    }
    return f"https://trade.taobao.com{ORDER_EXPORT_PATH}?{urlencode(params)}"
