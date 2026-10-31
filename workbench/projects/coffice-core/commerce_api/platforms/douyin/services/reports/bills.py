"""Shared 抖店资金/结算 workflow, entirely independent HTTP."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

from commerce_api.core.errors import ContractError
from commerce_api.core.parsing import require_rows

ORIGIN = "https://fxg.jinritemai.com"
HISTORY = ORIGIN + "/settlement/settlement/downloadItemList"


async def history(client):
    first = await client.get(HISTORY, {"page": 0, "size": 100})
    rows = require_rows(first.get("data"), "账单历史")
    try:
        count = int(first["total"])
    except (KeyError, TypeError, ValueError):
        raise ContractError("账单历史缺少有效 total") from None
    if count < 0 or count > 10000:
        raise ContractError("账单历史总量异常或超过明确分页上限")
    size = int(first.get("size") or 100)
    if size <= 0 or math.ceil(count / size) > 100:
        raise ContractError("账单历史分页数量无效或超限")
    for page in range(1, math.ceil(count / size)):
        rows.extend(require_rows((await client.get(HISTORY, {"page": page, "size": size})).get("data")))
    return rows


async def execute(ctx, request, contract):
    start, end = request.period.times()
    body = await ctx.client.post(ORIGIN + "/bill_center/domestic/shop/query_item", contract.build_query_payload(start, end), codes={100000})
    try:
        total = int(body["total"])
    except (KeyError, ValueError, TypeError):
        raise ContractError("账单查询缺少有效 total") from None
    if total < 0:
        raise ContractError("账单查询数量无效")
    if total == 0:
        return ctx.result("no_data", row_count=0)
    task_id = ctx.run.reference("create_export")

    def matches(row):
        return (str(row.get("start_time", "")).replace("T", " ")[:19] == start
            and str(row.get("end_time", "")).replace("T", " ")[:19] == end
            and row.get("download_type") == contract.DOWNLOAD_TYPE
            and row.get("time_type") == contract.TIME_TYPE
            and (not task_id or str(row.get("download_id")) == str(task_id)))

    if not task_id:
        existing = [r for r in await history(ctx.client) if matches(r) and r.get("status") in {"SUCCESS", "PROCESSING", "PENDING", "RUNNING"}]
        if existing:
            row = max(existing, key=lambda r: str(r.get("create_time", "")))
            task_id = str(row["download_id"])
            ctx.run.confirmed("create_export", task_id=task_id, reused=True)
        else:
            def reference(value):
                identifier = value.get("download_id") or (value.get("data") or {}).get("download_id")
                if not identifier:
                    raise ContractError("创建账单任务没有返回 download_id")
                return {"task_id": str(identifier)}
            await ctx.submit("create_export", lambda: ctx.client.post(
                ORIGIN + "/bill_center/domestic/shop/download_item", contract.build_export_payload(start, end), effect="export", codes={100000}), reference=reference)
            task_id = ctx.run.reference("create_export")

    def ready(rows):
        row = next((r for r in rows if matches(r)), None)
        if row is None:
            return None
        if row.get("status") in {"FAIL", "FAILED", "ERROR", "INVALID", "CANCELLED"}:
            raise ContractError("原账单导出任务已失败或取消", stage="poll")
        return row if row.get("status") in {"SUCCESS", "SUCCEED", "FINISH", "FINISHED"} else None

    await ctx.poll(lambda: history(ctx.client), ready)
    body = await ctx.client.get(ORIGIN + "/settlement/settlement/downloadFileFromId", {"download_id": task_id})
    url = (body.get("data") or {}).get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ContractError("账单任务没有返回有效文件地址")
    extension = next((ext for ext in (".zip", ".xlsx", ".xls", ".csv") if urlsplit(url).path.lower().endswith(ext)), ".xlsx")
    await ctx.download(url, extension)
    result = ctx.result().public()
    result["query_summary_count"] = total
    return result
