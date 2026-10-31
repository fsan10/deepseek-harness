"""抖店标准订单导出契约，不复用动态签名。"""
import json

ORIGIN = "https://fxg.jinritemai.com"
QUERY = ORIGIN + "/api/order/searchlist"
CREATE = ORIGIN + "/order/torder/export"
HISTORY = ORIGIN + "/order/torder/exportHistory"
FILE = ORIGIN + "/order/torder/exportHistory/downloadfile"
SEND = ORIGIN + "/api/order/sendcode"


def query_params(period):
    start, end = period.timestamps()
    return {"page": 0, "pageSize": 10, "create_time_start": start, "create_time_end": end,
        "order_by": "create_time", "order": "desc", "tab": "all", "source": "shop_order_view_upgrade"}


def export_payload(period, template=None):
    start, end = period.timestamps()
    return {**(template or {}), "come_from": "pc", "aid": 4272, "create_time_start": start, "create_time_end": end,
        "report_type": "STANDARD", "file_type": "csv", "appid": 1}


def matches(row, period):
    raw = row.get("query_condition")
    try:
        query = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return False
    if not isinstance(query, dict):
        return False
    start, end = period.timestamps()
    return (int(query.get("create_time_start") or 0) == start and int(query.get("create_time_end") or 0) == end
        and str(row.get("report_type", query.get("report_type"))) == "STANDARD")
