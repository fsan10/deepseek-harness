from commerce_api.core.errors import ContextRequired, ContractError
from commerce_api.core.parsing import require_rows
from commerce_api.runtime.archives import finish_order
from commerce_api.runtime.files import valid_receipt
from ...backends.merchant.api.reports import orders as api


async def download(ctx, request):
    query = api.filters(ctx.client.template(api.QUERY).get("orderSearchParam", {}), request.period)
    data = (await ctx.client.post(api.QUERY, {"orderSearchParam": query})).get("data")
    if not isinstance(data, dict) or "total" not in data:
        raise ContractError("快手订单查询缺少有效 total")
    count = int(data["total"])
    if count < 0:
        raise ContractError("快手订单数量无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)

    async def history():
        rows = []
        for offset in range(0, 5000, 50):
            data = (await ctx.client.get(api.LIST, {"offset": offset, "limit": 50, "userType": query.get("userType", "SELLER")})).get("data")
            if not isinstance(data, dict) or "total" not in data:
                raise ContractError("快手订单导出历史缺少有效分页总数")
            current = require_rows(data.get("offlineTask"))
            rows.extend(current)
            if len(rows) >= int(data["total"]):
                return rows
            if not current:
                raise ContractError("快手订单历史分页不完整")
        raise ContractError("快手订单历史超过分页上限")
    identifier = ctx.run.reference("create_export")
    if not identifier:
        candidates = [r for r in await history() if api.matches(r, request.period) and r.get("exportStatus") in {0, 1, 2, 3}]
        if candidates:
            identifier = str(max(candidates, key=lambda r: int(r.get("id") or 0))["id"])
            ctx.run.confirmed("create_export", task_id=identifier, reused=True)
        elif ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
            template = ctx.client.template(api.CREATE).get("orderEsSearchParam", {})
            if not template.get("exportFieldKeys"):
                raise ContextRequired("快手标准订单字段尚未完成接口发现")
            payload = api.filters(template, request.period)
            payload.update(templateType=0, templateId=0)
            await ctx.submit("create_export", lambda: ctx.client.post(api.CREATE, {"orderEsSearchParam": payload}, effect="export"))

    def ready(rows):
        candidates = [r for r in rows if api.matches(r, request.period) and (not identifier or str(r.get("id")) == identifier)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: int(r.get("id") or 0))
        if row.get("exportStatus") not in {0, 1, 2, 3}:
            raise ContractError("快手订单原导出任务失败")
        return row if row.get("exportStatus") == 3 and row.get("reachable") is True else None
    row = await ctx.poll(history, ready)
    identifier = str(row["id"])
    ctx.run.confirmed("create_export", task_id=identifier)
    source = next((f for f in ctx.run.state["files"] if f.get("role") == "source" and valid_receipt(f)), None)
    if source is None:
        body = await ctx.client.get(api.FILE, {"exportId": identifier})
        url = body.get("downLoadUrl")
        if not url:
            raise ContractError("快手订单下载没有返回 downLoadUrl")
        source = await ctx.download(url, ".xlsx")
        source["role"] = "source"
        ctx.run.save()
    async def send():
        await ctx.client.post(api.BASE + "encrypt/phone", {"taskId": int(identifier)})
        return await ctx.client.get(api.PASSWORD, {"exportId": identifier}, effect="verification")
    await finish_order(ctx, source, send_password=send)
    return ctx.result(row_count=count)
