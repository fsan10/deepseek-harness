"""Strict requested-period matching for 千帆资金与结算账单。"""
from datetime import timedelta

from commerce_api.core.errors import ContractError, NotReady
from commerce_api.core.parsing import require_rows

ORIGIN = "https://ark.xiaohongshu.com"


async def execute(ctx, request, contract, *, settlement=False):
    period = request.period
    mode = "month" if period.mode == "month" else "day"
    start_time = f"{period.start} 00:00:00"
    end_time = f"{period.end + timedelta(days=1)} 00:00:00"
    path = "/api/edith/settlebill/query_period_settle_bill_list" if settlement else "/api/edith/settlebill/query_period_fund_bill_list"
    rows = []
    page = 1
    while True:
        body = await ctx.client.post(ORIGIN + path, contract.build_period_payload(mode, start_time, end_time, page_num=page))
        data = body.get("data")
        if not isinstance(data, dict):
            raise ContractError("账单列表缺少 data 对象")
        current = data.get("list", data.get("items", data.get("periodFundBillList" if not settlement else "periodSettleBillList")))
        if current is None:
            current = data.get("records", data.get("billList"))
        current = require_rows(current, "账单列表")
        rows.extend(current)
        pages = int(data.get("totalPage") or 1)
        if pages < 1 or pages > 100:
            raise ContractError("账单分页总数无效或超限")
        total = data.get("total", data.get("totalCount"))
        if page >= pages or total is not None and len(rows) >= int(total):
            break
        if not current:
            raise ContractError("账单分页提前空页，未将缺失数据当作完成")
        page += 1
        if page > 100:
            raise ContractError("账单分页超出上限，未静默截断")
    targets = [period.start] if mode == "month" else [period.start + timedelta(days=i)
        for i in range((period.end - period.start).days + 1)]
    selected = [(day, contract.select_period_row(rows, mode, day)) for day in targets]
    if any(row is None for _, row in selected):
        raise NotReady("平台尚未生成全部请求账期的可下载账单", stage="query")
    field = "periodSettleNo" if settlement else "periodFundNo"
    for day, row in selected:
        body = await ctx.client.post(ORIGIN + "/api/edith/settlebill/get_bill_download_url", {
            "periodSettleNo": row[field], "billType": "PERIOD_SETTLE_BILL" if settlement else "PERIOD_FUND_BILL"})
        data = body.get("data")
        url = data if isinstance(data, str) else next((data.get(key) for key in ("downloadUrl", "download_url", "url", "fileUrl", "file_url") if isinstance(data, dict) and data.get(key)), None)
        if not url:
            raise ContractError("账单没有返回文件地址")
        await ctx.download(url, ".xlsx", label=request.kind + "_" + day.isoformat(),
            actual_period={"start": day.isoformat(), "end": (period.end if mode == "month" else day).isoformat(), "mode": mode})
    return ctx.result()
