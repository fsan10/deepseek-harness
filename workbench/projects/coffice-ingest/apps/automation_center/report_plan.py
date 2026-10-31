"""Whitelisted historical download planning, shared by UI and CLI telemetry."""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from datetime import datetime

from apps.file_ingest.registry import find_report

# Keys are existing controller modules, never imports/commands supplied by HTTP.
REPORT_NAMES = {
    "douyin_order_download": ("订单",), "douyin_bill_download": ("资金", "结算"),
    "qianchuan_promotion_fee_download": ("千川推广费",),
    "jd_order_download": ("订单",), "jd_fund_download": ("资金",),
    "jd_settlement_download": ("结算",),
    "jd_promotion_fee_download": ("京东联盟推广费", "京东通推广费"),
    "pinduoduo_order_download": ("订单",), "pinduoduo_settlement_download": ("结算",),
    "pinduoduo_promotion_fee_download": ("推广费",),
    "kuaishou_order_download": ("订单",), "kuaishou_fund_download": ("资金",),
    "kuaishou_settlement_download": ("结算",), "xiaohongshu_order_download": ("订单",),
    "xiaohongshu_fund_download": ("资金",), "xiaohongshu_settlement_download": ("结算",),
    "tmall_order_download": ("订单",), "tmall_aggregate_fund_download": ("聚合账户资金",),
    "tmall_alipay_fund_download": ("支付宝账户资金",),
    "tmall_taobao_union_promotion_download": ("淘宝联盟推广费",),
    "tmall_wanxiangtai_promotion_download": ("万相台推广费",),
}
SINGLE_DAY = {"jd_settlement_download", "kuaishou_fund_download", "xiaohongshu_fund_download",
              "xiaohongshu_settlement_download", "tmall_aggregate_fund_download", "tmall_alipay_fund_download"}
DATE_FLAGS = {"--date", "--month", "--mode", "--start-date", "--end-date", "--business-date"}


def china_today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def dates_between(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


def selected_dates(payload: dict) -> list[date]:
    values = payload.get("dates")
    if values is not None:
        if not isinstance(values, list) or not values:
            raise ValueError("请选择需要补跑的业务日期")
        days = sorted({date.fromisoformat(str(value)) for value in values})
    elif payload.get("month"):
        first = date.fromisoformat(str(payload["month"]) + "-01")
        days = list(dates_between(first, first.replace(day=calendar.monthrange(first.year, first.month)[1])))
    else:
        first = date.fromisoformat(str(payload.get("start_date") or ""))
        last = date.fromisoformat(str(payload.get("end_date") or ""))
        if last < first:
            raise ValueError("开始日期不能晚于结束日期")
        if (last - first).days >= 366:
            raise ValueError("一次补跑最多选择366天")
        days = list(dates_between(first, last))
    if len(days) > 366 or days[-1] > china_today():
        raise ValueError("一次补跑最多366天，不能选择未来日期")
    return days


def consecutive_ranges(days: list[date]) -> list[tuple[date, date]]:
    ranges = []
    for day in sorted(set(days)):
        if ranges and day == ranges[-1][1] + timedelta(days=1) and day.month == ranges[-1][0].month and day.year == ranges[-1][0].year:
            ranges[-1] = (ranges[-1][0], day)
        else:
            ranges.append((day, day))
    return ranges


def step_reports(platform: str, step: dict) -> list:
    names = REPORT_NAMES.get(step.get("module"), ())
    args = step.get("args") or []
    if step.get("module") == "douyin_bill_download":
        report = args[args.index("--report") + 1] if "--report" in args else "结算"
        names = (report,)
    elif step.get("module") == "jd_promotion_fee_download" and "--report" in args:
        selection = args[args.index("--report") + 1]
        names = {"union": ("京东联盟推广费",), "tong": ("京东通推广费",)}.get(selection, names)
    return [find_report(platform_name=platform, report_name=name) for name in names]


def historical_step(step: dict, report_name: str, start: date, end: date) -> dict:
    module = step["module"]
    if module not in REPORT_NAMES:
        raise ValueError("报表模块未登记历史下载能力")
    args, raw, index = [], list(step.get("args") or []), 0
    while index < len(raw):
        if raw[index] in DATE_FLAGS or (module in {"douyin_bill_download", "jd_promotion_fee_download"} and raw[index] == "--report"):
            index += 2
        else:
            args.append(raw[index]); index += 1
    if module == "douyin_bill_download":
        args += ["--report", report_name, "--mode", "day"]
    if module == "jd_promotion_fee_download":
        args += ["--report", "union" if report_name == "京东联盟推广费" else "tong"]
    if module in SINGLE_DAY:
        if start != end:
            raise ValueError("该报表需要逐日获取")
        args += ["--mode", "day", "--date", start.isoformat()]
    else:
        args += ["--start-date", start.isoformat(), "--end-date", end.isoformat()]
    return {"name": f"{report_name} {start.isoformat()}~{end.isoformat()}", "module": module, "args": args}


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
