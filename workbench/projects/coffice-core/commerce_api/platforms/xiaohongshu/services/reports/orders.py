"""小红书订单查询、创建、轮询与下载，全部独立 HTTP。"""
from commerce_api.core.errors import ContractError
from ...backends.merchant.api.reports.orders import build_order_page_payload, build_start_export_payload

ORIGIN = "https://ark.xiaohongshu.com"
QUERY = ORIGIN + "/api/edith/fulfillment/order/page"
CREATE = ORIGIN + "/api/edith/fulfillment/tool/file/start_export"
WATCH = ORIGIN + "/api/edith/fulfillment/tool/file/watch_export"


async def download(ctx, request):
    period = request.period
    body = await ctx.client.post(QUERY, build_order_page_payload(period.start, period.end))
    data = body.get("data") or {}
    try:
        total = int(data["total"])
    except (KeyError, TypeError, ValueError):
        raise ContractError("订单查询缺少有效 total") from None
    if total < 0:
        raise ContractError("订单查询数量为负数")
    if total == 0:
        return ctx.result("no_data", row_count=0)
    task_id = ctx.run.reference("create_export")
    if not task_id:
        def reference(body):
            value = body.get("data") or {}
            task = value.get("task_id") or value.get("taskId")
            if not task:
                raise ContractError("订单导出缺少 task_id")
            return {"task_id": str(task)}
        await ctx.submit("create_export", lambda: ctx.client.post(CREATE,
            build_start_export_payload(period.start, period.end), effect="export"), reference=reference)
        task_id = ctx.run.reference("create_export")

    def ready(body):
        task = (body.get("data") or {}).get("task")
        if not isinstance(task, dict):
            raise ContractError("订单任务查询缺少 task")
        state = str(task.get("state") or task.get("status") or "").lower()
        if state in {"fail", "failed", "error", "cancelled", "canceled"}:
            raise ContractError("订单导出失败或取消", stage="poll")
        url = next((task.get(k) for k in ("file_url", "fileUrl", "downloadUrl", "download_url") if task.get(k)), None)
        if url and (state in {"finish", "finished", "success", "complete", "completed"} or int(task.get("progress") or 0) >= 100):
            return url
        return None

    url = await ctx.poll(lambda: ctx.client.post(WATCH, {"task_id": task_id}), ready)
    await ctx.download(url, ".xlsx")
    return ctx.result(row_count=total)
