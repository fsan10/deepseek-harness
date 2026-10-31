"""快手结算完成口径，历史任务按完整 extParams 匹配。"""
from commerce_api.core.errors import ContractError
from ...backends.finance.api.reports import settlements as api

BASE = "https://s.kwaixiaodian.com/rest/app/tts/"
QUERY = BASE + "business/api/funds/financial/bill/pcpageorder/list"
CREATE = BASE + "financial/center/create/bill/download"
LIST = BASE + "financial/center/list/bill/download"


async def download(ctx, request):
    query = api.build_query_payload({}, request.period.start, request.period.end)
    data = (await ctx.client.post(QUERY, query)).get("data")
    if not isinstance(data, dict) or "total" not in data:
        raise ContractError("快手结算查询缺少权威 total")
    total = int(data["total"])
    if total < 0:
        raise ContractError("快手结算数量无效")
    if total == 0:
        return ctx.result("no_data", row_count=0)

    async def tasks():
        rows = []
        for page in range(1, 101):
            body = await ctx.client.post(LIST, api.build_list_payload(page=page, limit=50))
            current = api.file_items(body)
            rows.extend(current)
            if "total" in body and len(rows) >= int(body["total"]) or len(current) < 50:
                return rows
        raise ContractError("快手结算历史超过分页上限")

    task = api.select_settlement_task(await tasks(), query)
    if task is None and ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
        await ctx.submit("create_export", lambda: ctx.client.post(CREATE, api.build_create_payload(query), effect="export"))
    task = task or await ctx.poll(tasks, lambda rows: api.select_settlement_task(rows, query))
    if "id" not in task:
        raise ContractError("快手结算任务缺少文件记录 id")
    ctx.run.confirmed("create_export", task_id=str(task["id"]))
    await ctx.download(api.build_download_url(task["id"]), ".zip")
    return ctx.result(row_count=total)
