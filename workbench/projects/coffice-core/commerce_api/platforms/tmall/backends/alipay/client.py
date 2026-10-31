"""支付宝资金独立认证 scope。"""
from ...client import TmallClient
from commerce_api.runtime.contexts import context_key
from urllib.parse import urlencode, urlsplit, urlunsplit


class Client(TmallClient):
    def ensure_fund_context(self):
        url = "https://mbillexprod.alipay.com/enterprise/fundDailyStat.json"
        if self.template(url).get("billUserId"):
            return
        # The current auth landing defaults to calendar mode. Its status
        # request identifies the same authorized account; list-mode discovery
        # confirmed these fixed query fields. No business DOM switch is needed.
        source = "https://mbillexprod.alipay.com/enterprise/mbillDownloadStatus.json"
        context, form = self.context(source), self.template(source)
        if not context.get("url") or not form.get("billUserId"):
            return
        from datetime import datetime, timedelta
        from commerce_api.core.contracts import CN
        yesterday = (datetime.now(CN).date() - timedelta(days=1)).isoformat()
        query_form = {"billUserId": form["billUserId"], "namespace": "fundBillModel", "skipStatus": "false",
            "billType": "signcustomer", "pageSize": "20", "pageNum": "1", "querySettleAccount": "false",
            "startDate": form.get("startDate") or yesterday, "endDate": form.get("endDate") or yesterday,
            "_input_charset": "gbk"}
        parsed = urlsplit(context["url"])
        target = urlunsplit((parsed.scheme, parsed.netloc, urlsplit(url).path, parsed.query, ""))
        self.credential.setdefault("contexts", {})[context_key(url)] = {
            **context, "url": target, "method": "POST", "post_data": urlencode(query_form)}

    async def identity(self):
        import hashlib
        from commerce_api.core.errors import ContextRequired, ContractError, IdentityMismatch
        from .api.reports.funds import _alipay_success
        identity = await super().identity()
        self.ensure_fund_context()
        url = "https://mbillexprod.alipay.com/enterprise/fundDailyStat.json"
        form = self.template(url)
        context = self.context(url)
        account = form.get("billUserId")
        if not account or not context.get("url"):
            raise ContextRequired("支付宝缺少已确认资金账户的接口上下文，请先认证支付宝后台", stage="identity")
        fingerprint = hashlib.sha256(str(account).encode()).hexdigest()
        previous = self.credential.get("identity", {}).get("fund_account_fingerprint")
        if previous and previous != fingerprint:
            raise IdentityMismatch("支付宝实际资金账户发生变化，拒绝自动接受新绑定", stage="identity")
        body = _alipay_success(await self.json("POST", context["url"], form=form, check=False))
        actual = (body.get("fundBillSmryForm") or {}).get("billUserId")
        if not actual:
            raise ContractError("支付宝资金查询未确认实际资金账户", stage="identity")
        if str(actual) != str(account):
            raise IdentityMismatch("支付宝返回的实际资金账户与请求不一致", stage="identity")
        return self.bind_identity(identity["shop_name"], identity["shop_id"],
            fund_account_fingerprint=fingerprint, scopes=["shop_identity", "alipay_fund_read"])
