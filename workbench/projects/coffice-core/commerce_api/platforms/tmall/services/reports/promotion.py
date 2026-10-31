"""淘宝联盟和万相台分别保留认证范围和完整业务筛选。"""
import time
from urllib.parse import parse_qsl, urlsplit

from commerce_api.core.errors import ContextRequired, ContractError
from commerce_api.core.parsing import require_rows
from ...backends.alimama.api.reports.promotion import UNION_BIZ_TYPE, UNION_EXT

UNION = "https://ad.alimama.com/openapi/param2/1/gateway.unionadv/shopkeeper.rpt."
WANXIANG = "https://stlacct.alimama.com/settleAccount/account/"


async def union(ctx, request):
    token = ctx.client.tb_token()
    start, end = request.period.times()
    prefix = start + "~" + end
    async def tasks():
        rows = []
        for page in range(1, 101):
            data = (await ctx.client.get(UNION + "process.list.json", {"t": int(time.time() * 1000),
                "_tb_token_": token, "pageNo": page, "pageSize": 20, "bizTypeList": "105,96"})).get("data")
            if not isinstance(data, dict):
                raise ContractError("淘宝联盟导出历史缺少 data")
            current = require_rows(data.get("result"))
            rows.extend(current)
            total = data.get("totalCount", data.get("total"))
            if total is not None and len(rows) >= int(total) or len(current) < 20:
                return rows
        raise ContractError("淘宝联盟导出历史超过分页上限")
    def matches(row):
        return str(row.get("bizType")) == UNION_BIZ_TYPE and str(row.get("fileName", "")).startswith(prefix)
    identifier = ctx.run.reference("create_export")
    rows = await tasks()
    candidates = [r for r in rows if matches(r) and (not identifier or str(r.get("id")) == identifier)]
    if not candidates and ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
        form = {"t": str(int(time.time() * 1000)), "_tb_token_": token, "startTime": start, "endTime": end,
                "bizType": UNION_BIZ_TYPE, "ext": UNION_EXT}
        await ctx.submit("create_export", lambda: ctx.client.json("POST", UNION + "taskstart.json", form=form, effect="export"))
    def ready(rows):
        candidates = [r for r in rows if matches(r) and (not identifier or str(r.get("id")) == identifier)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: int(r.get("id") or 0))
        if int(row.get("status", -1)) < 0 or row.get("failedReason"):
            raise ContractError("淘宝联盟导出任务失败")
        return row if int(row.get("status", -1)) == 1 else None
    row = await ctx.poll(tasks, ready)
    ctx.run.confirmed("create_export", task_id=str(row["id"]))
    data = (await ctx.client.get(UNION + "filelink.json", {"t": int(time.time() * 1000), "_tb_token_": token,
        "idList": str(row["id"]), "bizType": UNION_BIZ_TYPE})).get("data") or {}
    links = require_rows(data.get("urlList"))
    if not links:
        raise ContractError("淘宝联盟导出未返回完整文件清单")
    for index, item in enumerate(links):
        if not isinstance(item.get("url"), str):
            raise ContractError("淘宝联盟文件清单含无效地址")
        await ctx.download(item["url"], ".csv", label=f"promotion_alimama_{index + 1}")
    return ctx.result()


async def wanxiang(ctx, request):
    endpoint = WANXIANG + "listAccountJournalWithTrans.json"
    context = ctx.client.context(endpoint)
    params = dict(parse_qsl(urlsplit(context.get("url", "")).query))
    if not params.get("csrfId"):
        raise ContextRequired("万相台缺少当前账户的验证上下文，请先认证万相台后台")
    params.update(beginTime=request.period.start.isoformat(), endTime=request.period.end.isoformat(),
        offset="0", limit="20", timeType="acount", tradeType="DEDUCT")
    data = (await ctx.client.get(endpoint, params)).get("data")
    if not isinstance(data, dict) or "total" not in data:
        raise ContractError("万相台资金查询缺少权威 total")
    count = int(data["total"])
    if count < 0:
        raise ContractError("万相台查询总数无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)
    url = ctx.private("export_link")
    if not url:
        form = {key: params.get(key, "") for key in ("csrfId", "bizCode", "beginTime", "endTime", "timeType", "tradeType", "loginPointId")}
        form["bizCode"] = form["bizCode"] or "universalBP"
        async def export():
            data = (await ctx.client.json("POST", WANXIANG + "exportAccountJournalWithTrans.action", form=form, effect="export")).get("data") or {}
            link = data.get("downloadLink")
            link = "https:" + link if isinstance(link, str) and link.startswith("//") else link
            if not isinstance(link, str) or not link.startswith("https://"):
                raise ContractError("万相台导出未返回有效文件地址")
            ctx.private("export_link", link)
            return {}
        await ctx.submit("create_export", export)
        url = ctx.private("export_link")
    await ctx.download(url, ".csv")
    return ctx.result(row_count=count)


async def download(ctx, request):
    return await union(ctx, request) if request.backend == "alimama" else await wanxiang(ctx, request)
