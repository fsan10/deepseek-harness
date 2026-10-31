"""快手小店独立 HTTP 客户端。"""
from commerce_api.runtime.backend import BackendClient
from commerce_api.core.errors import ContractError, redact


class Client(BackendClient):
    success_codes = {0, 1, 200}

    def validate(self, body, *, codes=None):
        # The financial gateway emits code="" on successful responses. Its
        # authoritative scalar result=1 also prevents accepting result=0 just
        # because a wrapper happens to contain code=0.
        result = body.get("result") if isinstance(body, dict) else None
        if result is not None and not isinstance(result, (dict, list)):
            if result in (1, "1", 200, "200", True):
                return body
            raise ContractError("快手接口业务失败", stage="response", details={"business_code": str(result)[:40],
                "reason": redact(body.get("error_msg") or body.get("msg") or body.get("message") or "")[:160]})
        return super().validate(body, codes=codes)

    async def identity(self):
        body = await self.post("https://syt.kwaixiaodian.com/rest/business/analysis/account/info", {})
        data = body.get("data", {}).get("userInfo", {})
        return self.bind_identity(data.get("user_name"), data.get("user_id"))
