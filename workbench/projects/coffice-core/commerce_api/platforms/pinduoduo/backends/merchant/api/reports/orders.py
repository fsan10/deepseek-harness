"""拼多多订单：秒级闭区间、标准模板及精确任务匹配。"""
from commerce_api.core.parsing import parse_json_value

ORIGIN = "https://mms.pinduoduo.com"
QUERY = ORIGIN + "/mangkhut/mms/recentOrderList"
CREATE = ORIGIN + "/mars/shop/recentOrders/export/task/add"
LIST = ORIGIN + "/mars/shop/orders/export/task/list"
FILE = ORIGIN + "/mars/shop/orders/export/task/getUrl"


def query(period):
    start, end = period.timestamps()
    return {"orderType": 0, "afterSaleType": 0, "remarkStatus": -1, "urgeShippingStatus": -1,
        "groupStartTime": start, "groupEndTime": end, "pageNumber": 1, "pageSize": 20,
        "hideRegionBlackDelayShipping": False}


def create(template, period):
    start, end = period.timestamps()
    return {**template, "orderType": 0, "afterSaleType": 0, "groupStartTime": start,
        "groupEndTime": end, "pageNumber": 1, "pageSize": 20, "titles": [],
        "rememberTemplate": False, "hideRegionBlackDelayShipping": False}


def matches(row, period):
    start, end = period.timestamps()
    return (row.get("groupStartTime") == start and row.get("groupEndTime") == end
        and int(row.get("orderType", -1)) == 0 and int(row.get("afterSaleType", -1)) == 0)
