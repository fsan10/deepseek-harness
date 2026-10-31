from commerce_api.core.errors import ContractError, OutcomeUnknown
from ...backends.promotion.api.reports import promotion as api


async def download(ctx, request):
    payload = api.payload(ctx.client.template(api.QUERY), request.period)
    result = (await ctx.client.post(api.QUERY, payload)).get("result")
    if not isinstance(result, dict) or "total" not in result:
        raise ContractError("拼多多推广费查询缺少权威 total")
    count = int(result["total"])
    if count < 0:
        raise ContractError("推广费查询数量无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)
    url = ctx.private("export_link")
    if not url:
        operation = ctx.run.state["operations"].get("create_export", {})
        old_error = ctx.run.state.get("error", {}).get("details", {})
        if operation.get("status") == "unknown" and old_error.get("business_code") == "54001":
            # Upgrade an older checkpoint that recorded this explicit negative
            # platform response as unknown. This is not a transport uncertainty.
            operation.update(status="rejected_business", rejection_code="54001")
            ctx.run.save()
        async def export():
            # Query and export have independent anti-content/crawler contexts.
            # Mixing a query token with the export endpoint fails validation.
            export_payload = api.payload(ctx.client.template(api.EXPORT, required=True), request.period)
            body = await ctx.client.post(api.EXPORT, export_payload, effect="export")
            value = body.get("result")
            if isinstance(value, dict):
                value = value.get("url") or value.get("downloadUrl")
            if not isinstance(value, str) or not value.startswith("https://"):
                raise ContractError("推广费导出未返回有效下载地址")
            ctx.private("export_link", value)
            return body
        await ctx.submit("create_export", export)
        url = ctx.private("export_link")
    await ctx.download(url, ".csv")
    return ctx.result(row_count=count)
