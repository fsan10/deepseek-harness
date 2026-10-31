"""快手钱包资金；单日/月独立导出，范围按日组成完整成果。"""
import json
from datetime import timedelta

from commerce_api.core.errors import ContextRequired, ContractError, NotReady
from commerce_api.core.parsing import require_rows
from ...backends.finance.api.reports import funds as api

BASE = "https://s.kwaixiaodian.com/rest/app/tts/business/api/funds/wallet/"


async def download(ctx, request):
    mode = "month" if request.period.mode == "month" else "day"
    accounts = require_rows((await ctx.client.post(BASE + "sub/query/info", {
        "accountRole": api.ACCOUNT_ROLE, "accountType": api.ACCOUNT_TYPE, "bidBizType": api.BID_BIZ_TYPE})).get("data"))
    account = api.select_account(accounts, request.account_id)
    ctx.bind_account("fund_submerchant", account["subMchId"])
    rows = api.fund_rows(await ctx.client.post(BASE + "query/account/bill/statistic", api.build_statistic_payload(
        {}, mode, request.period.start, request.period.end, account["subMchId"])))
    periods = [request.period.start] if mode == "month" else [request.period.start + timedelta(days=i)
        for i in range((request.period.end - request.period.start).days + 1)]
    for day in periods:
        row = api.select_fund_row(rows, mode, day)
        if row is None:
            raise NotReady("快手尚未生成请求账期的资金账单")
        key = api.fund_period_key(day, mode)
        operation = "create_fund_" + key
        url = ctx.private(operation)
        if not url:
            template = ctx.client.template(BASE + "create/export/task")
            operator = template.get("operatorName") or ctx.client.identity_data.get("shop_id")
            if not operator:
                raise ContextRequired("快手资金缺少已验证操作员身份")
            end = request.period.end if mode == "month" else day
            config = {"startTime": api.date_to_ms(day, end_of_day=False),
                "endTime": api.date_to_ms(end, end_of_day=True, end_millisecond=999),
                "accountType": api.ACCOUNT_TYPE, "accountRole": api.ACCOUNT_ROLE,
                "operatorName": str(operator), "subMchId": str(account["subMchId"]), "dateType": 2 if mode == "month" else 1}
            payload = {"accountType": api.ACCOUNT_TYPE, "accountRole": api.ACCOUNT_ROLE,
                "operatorName": str(operator), "taskKind": api.TASK_KIND,
                "exportConfig": json.dumps(config, separators=(",", ":")), "bidBizType": api.BID_BIZ_TYPE}

            async def create():
                body = await ctx.client.post(BASE + "create/export/task", payload, effect="export")
                link = api.fund_download_url(body)
                if not link:
                    raise ContractError("快手资金导出未返回可直接下载地址，保留原任务供核查")
                ctx.private(operation, link)
                return body
            await ctx.submit(operation, create)
            url = ctx.private(operation)
        await ctx.download(url, ".csv", label="fund_" + key,
            actual_period={"start": day.isoformat(), "end": (request.period.end if mode == "month" else day).isoformat(), "mode": mode})
    return ctx.result()
