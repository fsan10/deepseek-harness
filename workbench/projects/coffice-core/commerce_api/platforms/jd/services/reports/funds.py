"""京东资金流水查询、导出与原任务恢复。"""
import math
from commerce_api.core.errors import ContractError
from ...backends.merchant.api.reports import funds

QUERY = "dsm.pop.taurus.shop.view.dailyBillDsmProvider.queryCapitalFlowPage"
CREATE = "dsm.pop.finance.vendor.spi.export.ExportTaskDsmProvider.createTask"
LIST = "dsm.pop.finance.vendor.spi.export.ExportTaskDsmProvider.queryForPage"


async def tasks(client):
    body = await client.sff(LIST, funds.build_task_list_payload())
    rows, data = funds.response_task_rows(body)
    pages = int(data.get("totalPages", data.get("pages")) or
        math.ceil(int(data.get("totalCount", len(rows))) / max(1, int(data.get("pageSize") or len(rows) or 1))) or 1)
    if pages > 100 or pages < 1:
        raise ContractError("资金任务分页无效或超限")
    for page in range(2, pages + 1):
        current, _ = funds.response_task_rows(await client.sff(LIST, funds.build_task_list_payload(page)))
        rows.extend(current)
    return rows


async def download(ctx, request):
    start, end = request.period.start, request.period.end
    query = funds.build_query_payload(ctx.client.template(ctx.client.sff_url(QUERY)), start, end)
    body = await ctx.client.sff(QUERY, query)
    data = body.get("data")
    if not isinstance(data, dict) or "totalCount" not in data:
        raise ContractError("资金查询缺少权威 totalCount")
    total = int(data["totalCount"])
    if total == 0:
        return ctx.result("no_data", row_count=0)
    if total < 0:
        raise ContractError("资金查询数量无效")
    create = funds.build_create_payload(query, start, end)
    condition = create["request"]["data"]["conditionBody"]
    identifier = ctx.run.reference("create_export")
    if not identifier:
        existing = funds.select_task(await tasks(ctx.client), task_id="", condition_body=condition)
        if existing and int(existing.get("taskStatus", -1)) not in {3, 4, 5, -1}:
            identifier = str(existing["id"])
            ctx.run.confirmed("create_export", task_id=identifier, reused=True)
        else:
            def reference(body):
                identifier = (body.get("data") or {}).get("id")
                if not identifier:
                    raise ContractError("资金导出没有返回任务 ID")
                return {"task_id": str(identifier)}
            await ctx.submit("create_export", lambda: ctx.client.sff(CREATE, create, effect="export"), reference=reference)
            identifier = ctx.run.reference("create_export")

    def ready(rows):
        task = funds.select_task(rows, task_id=identifier, condition_body=condition)
        if task is None:
            return None
        if str(task.get("id")) != str(identifier):
            return None
        url = task.get("downloadUrl")
        if url:
            return url
        if int(task.get("taskStatus", -1)) in {3, 4, 5, -1}:
            raise ContractError("原资金导出任务失败或取消")
        return None

    url = await ctx.poll(lambda: tasks(ctx.client), ready)
    await ctx.download(url, ".csv")
    return ctx.result(row_count=total)
