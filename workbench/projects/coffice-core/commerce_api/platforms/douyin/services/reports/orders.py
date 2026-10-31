"""抖店订单：API 发码、群回复、API 下载及本地解密。"""
from urllib.parse import urlencode

from commerce_api.core.errors import ContractError, NeedsHuman
from commerce_api.core.parsing import require_rows
from commerce_api.runtime.archives import finish_order
from commerce_api.runtime.files import save_response, valid_receipt
from ...backends.merchant.api.reports import orders as api


async def download(ctx, request):
    previous = next((f for f in ctx.run.state["files"] if f.get("role") == "source" and valid_receipt(f)), None)
    if previous:
        await finish_order(ctx, previous)
        return ctx.result()
    query = api.query_params(request.period)
    body = await ctx.client.get(api.QUERY, query)
    if "total" not in body:
        raise ContractError("抖店订单查询缺少权威 total")
    count = int(body["total"])
    if count < 0:
        raise ContractError("抖店订单数量无效")
    if count == 0:
        return ctx.result("no_data", row_count=0)

    async def history():
        rows = []
        for page in range(1, 101):
            body = await ctx.client.get(api.HISTORY, {"page": page, "size": 50, "come_from": "pc"})
            data = body.get("data") or {}
            current = require_rows(data.get("task_list"))
            rows.extend(current)
            # The response's outer total is authoritative. data.total is zero
            # even when history contains many tasks in real captured responses.
            total = body.get("total")
            if total is None:
                raise ContractError("抖店订单导出历史缺少权威 total")
            if len(rows) >= int(total):
                return rows
            if not current:
                raise ContractError("抖店订单导出历史分页不完整")
        raise ContractError("抖店订单导出历史超过分页上限")

    task_id = ctx.run.reference("create_export")
    if not task_id:
        candidates = [r for r in await history() if api.matches(r, request.period) and r.get("status") in {0, 1, 2}]
        if candidates:
            task_id = str(max(candidates, key=lambda r: str(r.get("create_time")))["task_id"])
            ctx.run.confirmed("create_export", task_id=task_id, reused=True)
        else:
            def reference(body):
                identifier = (body.get("data") or {}).get("task_id")
                if not identifier:
                    raise ContractError("抖店订单导出未返回 task_id")
                return {"task_id": str(identifier)}
            await ctx.submit("create_export", lambda: ctx.client.post(api.CREATE,
                api.export_payload(request.period, ctx.client.template(api.CREATE)), effect="export"), reference=reference)
            task_id = ctx.run.reference("create_export")

    def ready(rows):
        row = next((r for r in rows if str(r.get("task_id")) == task_id and api.matches(r, request.period)), None)
        if row and row.get("status") not in {0, 1, 2}:
            raise ContractError("抖店原订单导出任务失败")
        return row if row and row.get("status") == 2 else None
    await ctx.poll(history, ready)
    await ctx.register_verification(purpose="订单报表 ZIP 解压密码", kind="archive_password",
        name="archive_password", defer_human_notice=True)

    async def receive(params, operation):
        async def fetch():
            url = ctx.client.prepare_url(api.FILE + "?" + urlencode(params))
            response = await ctx.client.http.request("GET", url, effect="verification", allow_download_redirect=True)
            if response.is_redirect:
                target = str(response.url.join(response.headers.get("location", "")))
                ctx.private("download_verification", {"data": {"url": target}})
                return {"file": False}
            if "json" in response.headers.get("content-type", ""):
                body = ctx.client.validate(response.json())
                ctx.private("download_verification", body)
                return {"file": False}
            source = save_response(response, ctx.paths.root / "downloads" / ctx.run.id,
                f"douyin_order_{request.period.start}_to_{request.period.end}.zip", period=request.period.public())
            source["role"] = "source"
            ctx.run.state["files"].append(source)
            ctx.run.save()
            return {"file": True}
        await ctx.submit(operation, fetch)

    params = {"task_id": task_id, "come_from": "pc"}
    if ctx.run.state["operations"].get("authorize_download", {}).get("status") != "confirmed":
        await receive(params, "authorize_download")
    source = next((f for f in ctx.run.state["files"] if f.get("role") == "source"), None)
    if source is None:
        data = (ctx.private("download_verification") or {}).get("data") or {}
        if data.get("url"):
            source = await ctx.download(data["url"], ".zip")
            source["role"] = "source"
        elif data.get("verify_type") and ctx.run.state["operations"].get("download_with_code", {}).get("status") != "confirmed":
            # Match the legacy routing order: a password listener must not
            # consume the download OTP arriving for the same shop.
            await ctx.cancel_verification("archive_password")
            verification = data.get("verify_params") or {}
            verify_type = data["verify_type"]
            account = verification.get("verify_account", "SUB")
            async def send():
                return await ctx.client.get(api.SEND, {"come_from": "pc", "verify_type": verify_type,
                    "verify_account": account, "scene": "2"}, effect="verification")
            code = await ctx.verification(purpose="订单报表下载验证码", name="download_code", send=send)
            await ctx.register_verification(purpose="订单报表 ZIP 解压密码", kind="archive_password",
                name="archive_password", defer_human_notice=True)
            try:
                await receive({**params, "verify_type": verify_type, "verify_account": account, "verify_code": code}, "download_with_code")
            except ContractError as exc:
                reason = str(exc.details.get("reason", ""))
                if "验证码" in reason and any(word in reason for word in ("错误", "无效", "失效")):
                    from commerce_api.integrations.legacy.verification import reject
                    await ctx.cancel_verification("archive_password")
                    operation = ctx.run.state["operations"]["download_code"]
                    await reject(operation["challenge_id"])
                    operation["status"] = "sent"
                    ctx.run.save()
                    raise NeedsHuman("下载验证码未通过，请在原群更正后续跑；未重建报表或重复发码") from None
                raise
            source = next((f for f in ctx.run.state["files"] if f.get("role") == "source"), None)
            if source is None:
                data = (ctx.private("download_verification") or {}).get("data") or {}
                if data.get("url"):
                    source = await ctx.download(data["url"], ".zip")
                    source["role"] = "source"
        if source is None:
            data = (ctx.private("download_verification") or {}).get("data") or {}
            # A successful OTP returns a private file_name, not the ZIP. The
            # normal UI then calls the same endpoint with that file_name and no
            # OTP. Resume this step without replaying the confirmed validation.
            if data.get("file_name") and not data.get("verify_type"):
                if not isinstance(data["file_name"], str):
                    raise ContractError("抖店订单下载授权缺少有效文件标识")
                if ctx.run.state["operations"].get("retrieve_file", {}).get("status") != "confirmed":
                    await receive({**params, "file_name": data["file_name"]}, "retrieve_file")
                source = next((f for f in ctx.run.state["files"] if f.get("role") == "source"), None)
                if source is None:
                    result = (ctx.private("download_verification") or {}).get("data") or {}
                    if result.get("url"):
                        source = await ctx.download(result["url"], ".zip")
                        source["role"] = "source"
        if source is None:
            raise NeedsHuman("订单下载验证尚未完成，保留原导出任务与群回复通道")
    await finish_order(ctx, source)
    return ctx.result(row_count=count)
