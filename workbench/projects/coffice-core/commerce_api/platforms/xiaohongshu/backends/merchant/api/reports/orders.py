"""Pure report contracts migrated from xiaohongshu_order_webapi_download.py; no browser implementation."""
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

SOURCE_DATA_BEAN = "OrderQueryPackageFileBuilder"

def build_order_page_payload(start: date, end: date, *, page_size: int = 20) -> dict[str, Any]:
    """生成当前订单页使用的查询 Payload，只替换日期范围。"""

    return {
        "page_no": 1,
        "page_size": page_size,
        "multi_search_field": "",
        "order_tag_list": [],
        "order_type_list": [],
        "promise_ship_time_type_list": [],
        "after_sale_status_list": [],
        "status": [],
        "time_range_list": [
            {
                "time_type": 3,
                "start_time": date_to_ms(start, end_of_day=False),
                "end_time": date_to_ms(end, end_of_day=True),
            }
        ],
        "seller_mark_priority_list": [],
        "seller_mark_note_status_list": [],
        "overdue_status": -2,
        "sort_by": {"sort_field": "ordered_at", "desc": True},
        "need_declare_info": True,
        "need_declare_times": True,
        "allow_es_fallback": True,
    }

def build_export_condition(start: date, end: date) -> dict[str, Any]:
    """生成 start_export 的 data_condition 对象。"""

    return {
        "multi_search_field": "",
        "order_tag_list": [],
        "order_type_list": [],
        "promise_ship_time_type_list": [],
        "after_sale_status_list": [],
        "time_range_list": [
            {
                "timeType": "ordered",
                "startTime": date_to_ms(start, end_of_day=False),
                "endTime": date_to_ms(end, end_of_day=True),
            }
        ],
        "seller_mark_priority_list": [],
        "seller_mark_note_status_list": [],
        "overdue_status": -2,
        "status_list": [],
        "sort_by": {"sortField": "ordered_at", "desc": True},
        "package_ids": [],
        "need_declare_info": True,
        "need_declare_times": True,
    }

def build_start_export_payload(start: date, end: date) -> dict[str, str]:
    condition = json.dumps(
        build_export_condition(start, end),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "data_condition": condition,
        "source_data_bean": SOURCE_DATA_BEAN,
    }
