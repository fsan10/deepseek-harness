"""现金(1)、支出(2)口径；查询与导出保持同一筛选。"""
ORIGIN = "https://yingxiao.pinduoduo.com"
QUERY = ORIGIN + "/mms-gateway/reinhardt/invoice/getDailyInvoice"
EXPORT = ORIGIN + "/mms-gateway/reinhardt/invoice/exportDailyInvoice"


def payload(template, period):
    return {**template, "startDate": period.start.isoformat(), "endDate": period.end.isoformat(),
        "sortBy": 0, "flowType": 2, "fundType": 1, "pageSize": 50, "pageNumber": 1}
