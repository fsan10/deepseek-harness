"""万相台财务独立会话与令牌。"""
from ...client import TmallClient
from commerce_api.core.errors import AuthRequired, ContractError, NeedsHuman, redact
import re


class Client(TmallClient):
    def validate(self, body, *, codes=None):
        info = body.get("info") if isinstance(body, dict) else None
        if isinstance(info, dict) and isinstance(info.get("ok"), bool):
            if info["ok"]:
                return body
            message = str(info.get("message") or info.get("errorCode") or "")
            if re.search(r"未登录|重新登录|登录失效|SESSION_EXPIRED|NEED_LOGIN", message, re.I):
                raise AuthRequired("万相台财务授权已失效", stage="response")
            if re.search(r"验证|权限|风控|风险|频繁", message):
                raise NeedsHuman("万相台财务接口要求检查授权或验证", stage="response")
            raise ContractError("万相台财务接口返回失败", stage="response",
                details={"business_code": str(info.get("errorCode", ""))[:40], "reason": redact(message)[:160]})
        return super().validate(body, codes=codes)

    async def identity(self):
        from commerce_api.core.errors import ContextRequired, ContractError
        from urllib.parse import parse_qs, urlsplit
        identity = await super().identity()
        url = "https://stlacct.alimama.com/settleAccount/account/listAccountJournalWithTrans.json"
        context = self.context(url)
        actual_url = context.get("url", "")
        if not parse_qs(urlsplit(actual_url).query).get("csrfId"):
            raise ContextRequired("万相台尚无已验证的财务上下文，请先执行该后台认证", stage="identity")
        body = await self.get(actual_url)
        if not isinstance(body.get("data"), dict) or "total" not in body["data"]:
            raise ContractError("万相台财务授权未返回有效总数", stage="identity")
        return self.bind_identity(identity["shop_name"], identity["shop_id"], scopes=["shop_identity", "wanxiangtai_finance_read"])
