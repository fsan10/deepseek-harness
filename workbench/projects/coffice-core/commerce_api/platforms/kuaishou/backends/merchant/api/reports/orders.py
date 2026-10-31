"""快手订单：统一所有日期字段，避免 timeValue 与 startTime 不一致。"""
import json

BASE = "https://s.kwaixiaodian.com/gateway/app/tts/ks/seller/order/"
QUERY = BASE + "query/v3"
CREATE = BASE + "export/submit/v3"
LIST = BASE + "export/list"
FILE = BASE + "export/download/id"
PASSWORD = BASE + "export/decry/code"


def filters(template, period):
    result = dict(template)
    start, end = period.timestamps(milliseconds=True, end_millisecond=999)
    result.update(startTime=start, endTime=end, time=[start, end], timeValue=[start, end], current=1, pageSize=10)
    return result


def matches(row, period):
    start, end = period.timestamps(milliseconds=True, end_millisecond=999)
    return (int(row.get("startTime", -1)) == start and int(row.get("endTime", -1)) == end
        and int(row.get("templateType", -1)) == 0 and int(row.get("reportType", -1)) == 0)
