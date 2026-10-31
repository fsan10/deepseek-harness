"""千牛宝贝销售明细：固定十三字段，按报表类型和精确账期匹配。"""
import re

from commerce_api.core.errors import ContractError, NeedsHuman
from commerce_api.core.parsing import require_rows
from commerce_api.runtime.archives import finish_order
from ...backends.qianniu.api.reports import orders as api

QUERY = "https://trade.taobao.com/trade/itemlist/asyncSold.htm?event_submit_do_query=1&_input_charset=utf8"
CREATE = "https://trade.taobao.com/trade/itemlist/list_export_order.htm?_input_charset=utf8"
FIELDS = "1,2,3,5,7,10,11,17,13,14,15,16,18"
REQUIRED_FIELDS = ("子订单编号", "主订单编号", "商品标题", "购买数量", "商品属性", "订单状态", "商家编码",
    "买家应付货款", "买家实付金额", "退款状态", "退款金额", "订单创建时间", "订单付款时间")


def validate_fields(path):
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book:
            sheet.reset_dimensions()
            for row in sheet.iter_rows(max_row=20, values_only=True):
                labels = [str(value).strip().lstrip("\ufeff") for value in row if value not in (None, "")]
                if len(labels) == len(REQUIRED_FIELDS) and set(labels) == set(REQUIRED_FIELDS):
                    return
        raise ContractError("天猫订单文件不符合宝贝销售明细的十三字段契约", stage="validate")
    finally:
        book.close()


async def download(ctx, request):
    start, end = request.period.start.isoformat(), request.period.end.isoformat()
    form = api._fallback_query_form(start, end)
    form.update(api._with_order_dates(ctx.client.template(QUERY), start, end))
    count = api.order_count(await ctx.client.json("POST", QUERY, form=form, check=False))
    if count == 0:
        return ctx.result("no_data", row_count=0)
    async def history():
        rows = []
        # A shop can retain thousands of exports. Reuse recent matching tasks;
        # an export submitted by this Run must appear on the first page. Never
        # rescan the whole archive on each poll.
        pages = 1 if ctx.run.state["operations"].get("create_export") else 5
        for page in range(1, pages + 1):
            data = (await ctx.client.mtop("mtop.taobao.trade.order.exportlist", {"page": str(page)})).get("data")
            if not isinstance(data, dict) or "detailList" not in data or "pageTotal" not in data:
                raise ContractError("千牛导出历史缺少有效分页结构")
            if int(data.get("pageNo", page)) != page:
                raise ContractError("千牛导出历史没有接受请求页码，已停止翻页")
            current = require_rows(data["detailList"])
            rows.extend(current)
            if any(matches(row) and (not identifier or str(row.get("exportId")) == identifier) for row in current):
                return rows
            if page >= max(1, int(data["pageTotal"])):
                return rows
        return rows
    def matches(row):
        begin, finish = request.period.times()
        return (row.get("startTimeStr") == begin and row.get("endTimeStr") == finish
            and str(row.get("exportType")) == "2")
    identifier = ctx.run.reference("create_export")
    rows = await history()
    candidates = [r for r in rows if matches(r) and (not identifier or str(r.get("exportId")) == identifier)]
    if not candidates and ctx.run.state["operations"].get("create_export", {}).get("status") != "confirmed":
        prepared = await ctx.client.mtop("mtop.com.taobao.order.sold.export", {"type": "online", "operate": "prepare"})
        if not (prepared.get("data") or {}).get("newExportPlatform"):
            raise ContractError("当前千牛账户未返回预期导出契约")
        export = {**form, "action": "itemlist/ExportOrderAction", "exportType": "2", "fileType": "xlsx",
            "selectFieldIds": FIELDS, "newExportPlatform": "true", "event_submit_do_apply_export": "1"}
        async def create():
            response = await ctx.client.http.request("POST", CREATE, form=export, effect="export")
            text = response.text
            if any(marker in text for marker in ("频繁", "限频", "稍后再试", "次数上限")):
                raise NeedsHuman("千牛导出受平台频率或次数限制，保留原任务")
            if not any(marker in text for marker in ("导出", "export-list", "EXPORT", "export")):
                raise ContractError("千牛提交响应无法确认导出结果，已保留原提交")
            return {}
        await ctx.submit("create_export", create)

    def ready(rows):
        candidates = [r for r in rows if matches(r) and (not identifier or str(r.get("exportId")) == identifier)]
        if not candidates:
            return None
        row = max(candidates, key=lambda r: str(r.get("applyTime", "")))
        status = str(row.get("exportStatus", "")).lower()
        if status in {"exportfail", "failed", "error", "cancelled"}:
            raise ContractError("千牛宝贝销售明细导出任务失败")
        return row if status in {"exportsuccess", "success", "done", "complete"} else None
    row = await ctx.poll(history, ready)
    ctx.run.confirmed("create_export", task_id=str(row["exportId"]))
    source = await ctx.download(api.export_download_url(row), ".xlsx")
    report = await finish_order(ctx, source)
    validate_fields(report)
    return ctx.result(row_count=count)
