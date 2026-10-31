"""京东结算单按明确业务日匹配并获取文件。"""
import math
from commerce_api.core.errors import ContractError, NotReady
from commerce_api.core.parsing import require_rows
from ...backends.merchant.api.reports import settlements

QUERY = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.queryDailyBillByPage"
DETAIL = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.downloadDailyBillDetail"


async def download(ctx, request):
    period = request.period
    if period.mode == "month":
        return await monthly(ctx, request)
    template = ctx.client.template(ctx.client.sff_url(QUERY))
    query = settlements.build_query_payload(template, period.start, period.end, page_size=100)
    body = await ctx.client.sff(QUERY, query)
    rows, data = settlements.response_settlement_rows(body)
    pages = int(data.get("totalPages", data.get("pages")) or
        math.ceil(int(data.get("totalElements", len(rows))) / max(1, int(data.get("pageSize") or len(rows) or 1))) or 1)
    if pages > 100:
        raise ContractError("结算分页超过上限")
    for page in range(2, pages + 1):
        current, _ = settlements.response_settlement_rows(await ctx.client.sff(QUERY,
            settlements.build_query_payload(template, period.start, period.end, page_num=page, page_size=100)))
        rows.extend(current)
    selected = [row for row in rows if period.start.isoformat() <= settlements.row_business_date(row) <= period.end.isoformat()]
    if not selected:
        raise NotReady("京东尚无请求业务日期的结算单", stage="query")
    if len({settlements.row_business_date(row) for row in selected}) != (period.end - period.start).days + 1:
        raise NotReady("京东结算单未覆盖完整请求日期，保留任务等待生成", stage="query")
    seen = set()
    for row in selected:
        day = settlements.row_business_date(row)
        identifier = int(row.get("id") or 0)
        if not identifier or day in seen:
            raise ContractError("结算单标识缺失或业务日期重复")
        seen.add(day)
        detail = await ctx.client.sff(DETAIL, settlements.build_detail_payload(query, identifier, period.start, period.end))
        data = detail.get("data")
        url = data if isinstance(data, str) else next((data.get(k) for k in ("downloadUrl", "fileUrl", "url") if isinstance(data, dict) and data.get(k)), None)
        if not url:
            raise ContractError("结算明细未返回下载地址")
        await ctx.download(url, ".zip", label="settlement_" + day,
            actual_period={"start": day, "end": day, "mode": "day"})
    return ctx.result()


async def monthly(ctx, request):
    query_api = "dsm.pop.taurus.shop.view.monthlyBillDsmProvider.queryMonthbillList"
    file_api = "dsm.pop.taurus.shop.view.monthlyBillDsmProvider.downloadMonthbillDetail"
    template = ctx.client.template(ctx.client.sff_url(query_api))
    query = dict(template.get("monthbillMo") or {})
    query.update(beginDate=request.period.timestamp(milliseconds=True),
        endDate=request.period.timestamp(end=True, milliseconds=True), isGlobalSale=False)
    rows = require_rows((await ctx.client.sff(query_api, {"monthbillMo": query})).get("data"))
    matches = [r for r in rows if str(r.get("month")) == request.period.start.strftime("%Y%m")]
    if not matches:
        raise NotReady("京东尚未生成请求月份的月结算单")
    if len(matches) != 1 or not matches[0].get("monthView"):
        raise ContractError("京东月结算账期重复或缺少 monthView")
    body = await ctx.client.sff(file_api, {"monthbillMo": {**query, "monthView": matches[0]["monthView"]}})
    url = body.get("data")
    if not isinstance(url, str):
        raise ContractError("京东月结算未返回有效文件地址")
    await ctx.download(url, ".zip")
    return ctx.result()
