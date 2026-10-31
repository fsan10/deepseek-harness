"""对账中心：会话单独存储，按完整筛选查询并复用导出任务。"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from commerce_api.core.errors import ContractError
from commerce_api.core.parsing import require_rows
from ...backends.cashier.api.reports import settlements as api

BASE = "https://cashier.pinduoduo.com/templar/api/bill/"


def endpoint(name):
    return BASE + name + "?__app_code=113"


async def download(ctx, request):
    start, end = request.period.timestamps()
    filters = api.build_filter_payload(start, end)
    result = (await ctx.client.post(endpoint("pagingQueryMallBalanceBillListForMms"), api.build_list_payload(filters))).get("result")
    if not isinstance(result, dict) or "total" not in result:
        raise ContractError("拼多多对账中心缺少权威 total")
    count = int(result["total"])
    if count < 0:
        raise ContractError("对账中心账单数量无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)

    async def tasks():
        rows = []
        for page in range(1, 101):
            data = (await ctx.client.post(endpoint("queryBillDownloadTaskList"), {"page": page, "size": 50})).get("result")
            if not isinstance(data, dict) or "total" not in data:
                raise ContractError("对账中心任务列表缺少分页总数")
            current = require_rows(data.get("data"))
            rows.extend(current)
            if len(rows) >= int(data["total"]):
                return rows
            if not current:
                raise ContractError("对账中心历史分页不完整")
        raise ContractError("对账中心任务列表超过分页上限")

    def matches(row):
        query = api.task_query(row)
        return api.task_range_matches(row, start, end) and all(query.get(k) == filters[k]
            for k in ("groupType", "classList", "minAmount", "maxAmount", "orderSn"))

    identifier = ctx.run.reference("create_export")
    if not identifier:
        candidates = [r for r in await tasks() if matches(r) and r.get("status") in {0, 1}]
        if candidates:
            identifier = str(max(candidates, key=lambda r: int(r.get("createdAt") or 0))["id"])
            ctx.run.confirmed("create_export", task_id=identifier, reused=True)
        elif ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
            payload = api.build_create_task_payload(filters)
            # The live DOM contract has no isHistory field.
            payload.pop("isHistory", None)
            await ctx.submit("create_export", lambda: ctx.client.post(endpoint("createBillDownloadTask"), payload, effect="export"))

    def ready(rows):
        candidates = [r for r in rows if matches(r) and (not identifier or str(r.get("id")) == identifier)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: int(r.get("createdAt") or 0))
        if row.get("status") not in {0, 1}:
            raise ContractError("对账中心原导出任务失败")
        return row if row.get("status") == 1 and row.get("downloadUrl") else None

    row = await ctx.poll(tasks, ready)
    ctx.run.confirmed("create_export", task_id=str(row["id"]))
    parts = urlsplit(row["downloadUrl"])
    values = {**dict(parse_qsl(parts.query)), "__app_code": "113"}
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(values), ""))
    await ctx.download(url, ".csv", headers={"Referer": "https://cashier.pinduoduo.com/main/bills/export-history"})
    return ctx.result(row_count=count)
