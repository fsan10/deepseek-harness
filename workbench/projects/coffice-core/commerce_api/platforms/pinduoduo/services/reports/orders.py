"""查询、创建、轮询和下载均为独立 HTTP。"""
from urllib.parse import urlsplit

from commerce_api.core.errors import ContractError, ContextRequired
from commerce_api.core.parsing import require_rows
from ...backends.merchant.api.reports import orders as api


async def download(ctx, request):
    body = await ctx.client.post(api.QUERY, api.query(request.period))
    try:
        count = int(body["result"]["totalItemNum"])
    except (KeyError, ValueError, TypeError):
        raise ContractError("拼多多订单查询缺少有效数量") from None
    if count < 0:
        raise ContractError("拼多多订单数量无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)

    async def history():
        rows = []
        for page in range(1, 101):
            result = (await ctx.client.post(api.LIST, {"pageNumber": page, "pageSize": 40, "exportType": "0"})).get("result")
            if not isinstance(result, dict) or "totalItemNum" not in result:
                raise ContractError("拼多多订单历史缺少分页总数")
            current = require_rows(result.get("pageItems"))
            rows.extend(current)
            if len(rows) >= int(result["totalItemNum"]):
                return rows
            if not current:
                raise ContractError("拼多多订单历史分页不完整")
        raise ContractError("拼多多订单历史超过分页上限")

    task_id = ctx.run.reference("create_export")
    if not task_id:
        candidates = [r for r in await history() if api.matches(r, request.period) and r.get("status") in {0, 1, 2}]
        if candidates:
            task_id = str(max(candidates, key=lambda r: int(r.get("createdTime") or 0))["id"])
            ctx.run.confirmed("create_export", task_id=task_id, reused=True)
        elif ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
            template = ctx.client.template(api.CREATE)
            if not template.get("templateName"):
                # A report contract is not guessed from UI labels. Discovery
                # supplies the current standard template name once per backend.
                raise ContextRequired("订单标准模板尚未完成接口发现，请先初始化此后台的接口契约")
            await ctx.submit("create_export", lambda: ctx.client.post(api.CREATE,
                api.create(template, request.period), effect="export"))

    def ready(rows):
        candidates = [r for r in rows if api.matches(r, request.period) and (not task_id or str(r.get("id")) == task_id)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: int(r.get("createdTime") or 0))
        if row.get("status") == 4 and any(x in str(row.get("statusStr")) for x in ("0条", "没有数据", "无数据")):
            raise ContractError("订单查询非零但导出返回零条，请核验平台筛选口径")
        if any(x in str(row.get("statusStr")) for x in ("失败", "取消", "异常")):
            raise ContractError("拼多多订单导出任务失败")
        if row.get("status") == 1:
            return row
        return None

    row = await ctx.poll(history, ready)
    ctx.run.confirmed("create_export", task_id=str(row["id"]))
    url = (await ctx.client.post(api.FILE, {"jobId": int(row["id"])})).get("result")
    if not isinstance(url, str):
        raise ContractError("拼多多订单接口未返回文件地址")
    extension = next((ext for ext in (".csv", ".zip", ".xlsx", ".xls") if urlsplit(url).path.endswith(ext)), ".csv")
    await ctx.download(url, extension)
    return ctx.result(row_count=count)
