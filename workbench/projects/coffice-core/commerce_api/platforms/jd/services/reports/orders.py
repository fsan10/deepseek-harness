import json

from commerce_api.core.errors import ContextRequired, ContractError
from commerce_api.core.parsing import require_rows
from commerce_api.runtime.archives import finish_order
from commerce_api.runtime.files import valid_receipt
from ...backends.merchant.api.reports import orders as api


async def download(ctx, request):
    async def history():
        rows = []
        for page in range(1, 101):
            data = (await ctx.client.sff(api.LIST, {"exportParam": {"exportTaskType": 0, "page": page, "pageSize": 50}})).get("data")
            if not isinstance(data, dict) or "totalItem" not in data:
                raise ContractError("京东订单导出历史缺少有效总数")
            current = require_rows(data.get("itemList"))
            rows.extend(current)
            if len(rows) >= int(data["totalItem"]):
                return rows
            if not current:
                raise ContractError("京东订单历史分页不完整")
        raise ContractError("京东订单历史超过分页上限")

    identifier = ctx.run.reference("create_export")
    if not identifier:
        candidates = [r for r in await history() if api.matches(r, request.period) and r.get("taskStatus") in {0, 1, 2}]
        if candidates:
            identifier = str(max(candidates, key=lambda r: str(r.get("createDate", "")))["id"])
            ctx.run.confirmed("create_export", task_id=identifier, reused=True)
        elif ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
            template = ctx.client.template(ctx.client.sff_url(api.CREATE))
            raw = (template.get("exportParam") or {}).get("taskDataParam")
            try:
                query = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except ValueError:
                raise ContextRequired("京东标准加密导出模板无效") from None
            if "sensitiveInfoSign" not in query or not query.get("orderStatusList"):
                raise ContextRequired("京东订单标准加密模板尚未完成接口发现")
            start, end = request.period.times()
            query.update(startDate=start, endDate=end, exportTaskType=0, skuId=None, warningType=None, locSkuId=None)
            payload = {"exportParam": {"exportTaskType": 0, "taskDataParam": json.dumps(query, ensure_ascii=False, separators=(",", ":"))}}
            await ctx.submit("create_export", lambda: ctx.client.sff(api.CREATE, payload, effect="export"))

    def ready(rows):
        candidates = [r for r in rows if api.matches(r, request.period) and (not identifier or str(r.get("id")) == identifier)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: str(r.get("createDate", "")))
        if row.get("taskStatus") not in {0, 1, 2}:
            raise ContractError("京东订单原导出任务失败")
        return row if row.get("taskStatus") == 2 else None
    row = await ctx.poll(history, ready)
    identifier = str(row["id"])
    ctx.run.confirmed("create_export", task_id=identifier)
    source = next((f for f in ctx.run.state["files"] if f.get("role") == "source" and valid_receipt(f)), None)
    if source is None:
        source = await ctx.download("https://export.shop.jd.com/exportCenter/export.action?taskId=" + identifier, ".zip")
        source["role"] = "source"
        ctx.run.save()
    async def send():
        return await ctx.client.sff(api.PASSWORD, {"exportParam": {"exportTaskType": 0, "taskId": int(identifier)}}, effect="verification")
    await finish_order(ctx, source, send_password=send)
    return ctx.result()
