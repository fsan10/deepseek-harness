"""Pure report contracts migrated from tmall_promotion_webapi_download.py; no browser implementation."""
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

UNION_BIZ_TYPE = "96"

UNION_EXT = ('{"type":"cps","split":1,"period":"1d","level4Type":"day_level3",'
    '"headerKeys":"theDateTime,dimField,alipayAmt,alipayNum,preCommissionFee,'
    'preTotalFee,preCommissionRate,preServiceRate,enterShopPvTk,cartAddItmCnt,'
    'cltAddItmCnt,cmCommissionFee,cmServiceFee,cmTotalFee,cmCommissionRate,'
    'cmServiceRate,cpsSettleAmt,cpsSettleNum,preCommissionFee,preServiceFee,'
    'preTotalFee,preCommissionRate,preServiceRate,preGPP,cmCommissionFee,'
    'cmServiceFee,cmTotalFee,cmCommissionRate,cmServiceRate,depPreCommissionFee,'
    'depPreCommissionRate,enterShopPvTk,enterShopUvTk,tkPvItemCnt,cartAddItmCnt,'
    'cltAddItmCnt,alipayNumDepositPresale,alipayAmtDepositPresale,depPreRestAmt,'
    'depPreAlipayAmt,tkCouponGetCnt,alipayByrCnt,alipayAmt,alipayNum,alipayQuantity,'
    'cvr,tkSuccByrCnt,tkSuccAmt,tkSuccCnt,cpsSettleByrCnt,cpsSettleAmt,cpsSettleNum"}')

def union_record(body: Any, target_date: str) -> dict[str, Any] | None:
    data = body.get("data", {}) if isinstance(body, dict) else {}
    rows = data.get("result", []) if isinstance(data, dict) else []
    prefix = f"{target_date} 00:00:00~{target_date} 23:59:59"
    for row in rows:
        if not isinstance(row, dict):
            continue
        if int(row.get("bizType", 0) or 0) != int(UNION_BIZ_TYPE):
            continue
        if str(row.get("fileName") or "").startswith(prefix) and int(row.get("status", 0) or 0) == 1:
            return row
    return None
