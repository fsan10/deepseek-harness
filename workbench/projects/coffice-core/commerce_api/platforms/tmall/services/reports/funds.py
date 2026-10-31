"""聚合账户与支付宝各自调用自己的资金接口和认证上下文。"""
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from commerce_api.core.errors import ContextRequired, ContractError, NotReady
from commerce_api.core.parsing import require_rows
from ...backends.alipay.api.reports import funds as alipay

AGG_QUERY = "mtop.taobao.finance.fund.bill.query"
AGG_FILE = "mtop.taobao.finance.fund.bill.detail.file.get"
ALIPAY_QUERY = "https://mbillexprod.alipay.com/enterprise/fundDailyStat.json"


async def aggregate(ctx, request):
    month = request.period.mode == "month"
    pattern = "%Y%m" if month else "%Y%m%d"
    query = {"billCode": "BILL_MONTH_AGG" if month else "BILL_DAY_AGG", "pageNo": 1, "pageSize": 50,
        "billCycleFrom": request.period.start.strftime("%Y-%m") if month else request.period.start.isoformat(),
        "billCycleTo": request.period.end.strftime("%Y-%m") if month else request.period.end.isoformat()}
    rows = []
    for page in range(1, 101):
        body = await ctx.client.mtop(AGG_QUERY, {**query, "pageNo": page})
        table = (body.get("data") or {}).get("tableValues")
        if not isinstance(table, dict) or "hasNext" not in table:
            raise ContractError("聚合资金查询缺少完整分页结构")
        current = require_rows(table.get("data"))
        rows.extend(current)
        if table["hasNext"] is False:
            break
        if not current:
            raise ContractError("聚合资金账单分页提前结束")
    else:
        raise ContractError("聚合资金分页超过上限")
    days = [request.period.start] if month else [request.period.start + timedelta(days=i)
        for i in range((request.period.end - request.period.start).days + 1)]
    for day in days:
        key = day.strftime(pattern)
        matches = [row for row in rows if str(row.get("ds")) == key]
        if not matches:
            raise NotReady("聚合账户尚未生成请求账期账单")
        if len(matches) != 1:
            raise ContractError("聚合账户返回重复账期")
        data = (await ctx.client.mtop(AGG_FILE, {"period": key})).get("data") or {}
        links = data.get("fileUrl")
        links = [links] if isinstance(links, str) else links
        if not isinstance(links, list) or not links or not all(isinstance(x, str) for x in links):
            raise ContractError("聚合资金未返回有效的完整文件清单")
        for index, url in enumerate(links):
            await ctx.download(url, ".xlsx", label=f"fund_aggregate_{key}_{index + 1}",
                actual_period={"start": day.isoformat(), "end": (request.period.end if month else day).isoformat(),
                               "mode": "month" if month else "day"})
    return ctx.result()


async def alipay_funds(ctx, request):
    template = ctx.client.context(ALIPAY_QUERY)
    form = ctx.client.template(ALIPAY_QUERY)
    if not form.get("billUserId"):
        raise ContextRequired("支付宝会话缺少已确认资金账户，请先执行支付宝后台认证")
    url = template.get("url", ALIPAY_QUERY)
    query = dict(parse_qsl(urlsplit(url).query))
    if not query.get("ctoken"):
        token = next((c.value for c in ctx.client.http.client.cookies.jar if c.name == "ctoken"), None)
        if token:
            url = ALIPAY_QUERY + "?" + urlencode({"ctoken": token})
        else:
            raise ContextRequired("支付宝资金接口缺少当前安全上下文")
    no_data = []
    for index in range((request.period.end - request.period.start).days + 1):
        day = (request.period.start + timedelta(days=index)).isoformat()
        current_form = alipay.alipay_query_form(form, day)
        body = await ctx.client.json("POST", url, form=current_form, check=False)
        result = alipay._alipay_success(body).get("result") or {}
        rows = require_rows(result.get("dateDtls"))
        matches = [r for r in rows if r.get("bizDate") == day]
        if len(matches) != 1:
            raise NotReady("支付宝没有返回唯一目标账期")
        if any(alipay._alipay_true(matches[0].get(k)) for k in ("noData", "emptyData")):
            no_data.append(day)
            continue
        if not alipay._alipay_true(matches[0].get("downloadable")) or alipay._alipay_true(matches[0].get("processing")):
            raise NotReady("支付宝目标账期仍在生成")
        operation = "security_" + day
        link = ctx.private(operation)
        if not link:
            async def authorize():
                security_url, security_form = alipay.alipay_security_request(url, day)
                body = await ctx.client.json("POST", security_url, form=security_form, check=False, effect="verification")
                ticket = alipay.alipay_security_id(body)
                ctx.private(operation, alipay.alipay_download_url(url, current_form, day, ticket))
                return {}
            await ctx.submit(operation, authorize)
            link = ctx.private(operation)
        async def consume():
            await ctx.download(link, ".zip", label="fund_alipay_" + day,
                actual_period={"start": day, "end": day, "mode": "day"})
            return {}
        state = ctx.run.state["operations"].get("download_" + day, {}).get("status")
        if state != "confirmed":
            await ctx.submit("download_" + day, consume)
    result = ctx.result("no_data" if len(no_data) == (request.period.end - request.period.start).days + 1 else "downloaded").public()
    result["no_data_dates"] = no_data
    return result


async def download(ctx, request):
    return await alipay_funds(ctx, request) if request.backend == "alipay" else await aggregate(ctx, request)
