"""京麦标准加密订单导出契约。"""
import json

PREFIX = "dsm.order.export.exportCenterService."
LIST = PREFIX + "queryExportTaskInfo"
CREATE = PREFIX + "createdExportTask"
PASSWORD = PREFIX + "exportTaskPwdSend"


def conditions(row):
    value = row.get("taskData")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def matches(row, period):
    query = conditions(row)
    start, end = period.times()
    return (int(row.get("taskType", -1)) == 0 and row.get("encryptFlag") is True
        and str(query.get("startTime", query.get("startDate", "")))[:19] == start
        and str(query.get("endTime", query.get("endDate", "")))[:19] == end)
