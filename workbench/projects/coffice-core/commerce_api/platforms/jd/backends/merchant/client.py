"""京东商家 HTTP 客户端和稳定店铺身份。"""
from commerce_api.runtime.backend import BackendClient
from commerce_api.core.errors import AuthRequired
from commerce_api.runtime.contexts import context_key
from urllib.parse import urlencode


class Client(BackendClient):
    success_codes = {0, 1, 200, "success"}

    def sff_url(self, api):
        fallback = "https://sff.jd.com/api?" + urlencode({"v": "1.0", "appId": "QDWB4GJVETRIFPT7RHSL", "api": api})
        context = self.context(fallback)
        return context.get("url") or fallback

    async def sff(self, api, payload, *, effect="read"):
        return await self.post(self.sff_url(api), payload, effect=effect)

    async def identity(self):
        user = await self.get("https://ddmall.jd.com/user-info.do", check=False)
        operator = user.get("userName")
        if not operator:
            raise AuthRequired("京东账号身份未认证", stage="identity")
        body = await self.json("POST", "https://ddmall.jd.com/mall/api", params={"m": "getMallByOperator"},
                               form={"operator": operator, "m": "getMallByOperator"})
        data = body.get("data", {}).get("mall", {})
        return self.bind_identity(data.get("name"), data.get("id"))
