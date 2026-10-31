"""一个推广费能力串行下载京东联盟和京东通，分别保留任务状态。"""
import time
from datetime import datetime
from commerce_api.core.contracts import CN

from commerce_api.core.errors import ContractError, OutcomeUnknown
from ...backends.promotion.api.reports import promotion as api

UNION = "https://jzt-api.jd.com/union/pop/"
UQUERY = UNION + "account/list/billList?requestFrom=0"
ULIST = UNION + "asyncDownload/getTaskList?requestFrom=0"
UCREATE = UNION + "asyncDownload/generateTask?requestFrom=0"
UFILE = UNION + "asyncDownload/downloadReport?requestFrom=0"
TONG = "https://atoms-api.jd.com"
TQUERY = TONG + "/financecore/subaccount/cashconsume/list"
TCREATE = TONG + "/financecore/subaccount/cashconsume/export/async"
TLIST = TONG + "/api/download/common/asyn/download/reportInfo/list"


async def union_tasks(client):
    rows = []
    for page in range(1, 101):
        current, meta = api.union_task_rows(await client.post(ULIST, api.build_union_task_payload(page)))
        rows.extend(current)
        if "total" not in meta:
            raise ContractError("联盟任务列表缺少有效 total")
        if len(rows) >= int(meta["total"]):
            return rows
        if not current:
            raise ContractError("联盟任务历史分页不完整")
    raise ContractError("联盟任务历史超过分页上限")


async def download(ctx, request):
    start, end = request.period.start, request.period.end
    components = {}
    body = await ctx.client.post(UQUERY, api.build_union_query_payload(ctx.client.template(UQUERY), start, end))
    data = body.get("content", body.get("data"))
    if not isinstance(data, dict) or "total" not in data:
        raise ContractError("京东联盟查询缺少权威 total")
    count = int(data["total"])
    if count < 0:
        raise ContractError("联盟查询总数无效")
    components["union"] = {"row_count": count, "status": "no_data" if count == 0 else "downloaded"}
    if count:
        identifier = ctx.run.reference("union_export")
        operation = ctx.run.state["operations"].get("union_export", {})
        if not identifier and not operation:
            baseline = [str(r.get("pk")) for r in await union_tasks(ctx.client)]
            ctx.run.update(union_baseline=baseline)
            await ctx.submit("union_export", lambda: ctx.client.post(UCREATE,
                api.build_union_generate_payload(start, end), effect="export"))

        def ready(rows):
            pinned = ctx.run.reference("union_export") or identifier
            if pinned:
                candidates = [r for r in rows if str(r.get("pk")) == pinned]
            else:
                baseline = set(ctx.run.state.get("union_baseline", []))
                candidates = [r for r in rows if str(r.get("pk")) not in baseline
                    and r.get("reportName") == api.UNION_REPORT_NAME and int(r.get("moduleType", -1)) == api.UNION_MODULE_TYPE]
            if len(candidates) > 1:
                raise OutcomeUnknown("联盟出现多个新任务，无法唯一归属，禁止自动选取或重复导出")
            if not candidates:
                return None
            row = candidates[0]
            status = int(row.get("generateStatus", -1))
            if status in {4, 5, -1}:
                raise ContractError("京东联盟原导出任务失败")
            ctx.run.confirmed("union_export", task_id=str(row["pk"]))
            return row if status == 2 else None
        task = await ctx.poll(lambda: union_tasks(ctx.client), ready, stage="union_poll")
        body = await ctx.client.post(UFILE, api.build_union_download_payload(task["pk"]))
        url = body.get("content", body.get("data"))
        if not isinstance(url, str):
            raise ContractError("京东联盟没有返回下载地址")
        await ctx.download(url, ".xlsx", label="promotion_union")

    query = api.build_tong_query_payload(ctx.client.template(TQUERY), start, end)
    body = await ctx.client.post(TQUERY, query)
    data = body.get("data") or {}
    paginator = data.get("paginator") or {}
    if "total" not in paginator:
        raise ContractError("京东通查询缺少权威 total")
    tong_count = int(paginator["total"])
    if tong_count < 0:
        raise ContractError("京东通查询数量无效")
    components["tong"] = {"row_count": tong_count, "status": "no_data" if tong_count == 0 else "downloaded"}
    if tong_count:
        async def tasks():
            rows = []
            # This endpoint filters task creation dates. Report business dates
            # remain the separate startDay/endDay fields in each task row.
            payload = api.build_tong_report_payload(max(datetime.now(CN).date(), end))
            for page in range(1, 101):
                current, meta = api.tong_report_rows(await ctx.client.post(TLIST, {**payload, "page": page}))
                rows.extend(current)
                pagination = meta.get("paginator") or {}
                if "items" not in pagination:
                    raise ContractError("京东通任务历史缺少权威总数")
                if len(rows) >= int(pagination["items"]):
                    return rows
                if not current:
                    raise ContractError("京东通任务历史分页不完整")
            raise ContractError("京东通历史超过分页上限")
        identifier = ctx.run.reference("tong_export")
        task = api.select_tong_report(await tasks(), start=start, end=end, submitted_after_ms=0)
        if task and not identifier:
            identifier = str(task["id"])
            ctx.run.confirmed("tong_export", task_id=identifier, reused=True)
        if not identifier and ctx.run.state["operations"].get("tong_export", {}).get("status") != "confirmed":
            await ctx.submit("tong_export", lambda: ctx.client.post(TCREATE, api.build_tong_export_payload(query), effect="export"))
        def tong_ready(rows):
            current = next((r for r in rows if str(r.get("id")) == identifier), None) if identifier else api.select_tong_report(rows, start=start, end=end, submitted_after_ms=0)
            if current is None:
                return None
            if current.get("startDay") != start.isoformat() or current.get("endDay") != end.isoformat():
                raise ContractError("京东通任务账期发生变化")
            if int(current.get("status", -1)) in {3, 4, 5, -1}:
                raise ContractError("京东通原导出任务失败")
            return current if current.get("status") == 2 and current.get("downloadUrl") else None
        task = await ctx.poll(tasks, tong_ready, stage="tong_poll")
        ctx.run.confirmed("tong_export", task_id=str(task["id"]))
        await ctx.download(task["downloadUrl"], ".xlsx", label="promotion_tong")
    result = ctx.result("downloaded" if count or tong_count else "no_data", row_count=count + tong_count).public()
    result["components"] = components
    return result
