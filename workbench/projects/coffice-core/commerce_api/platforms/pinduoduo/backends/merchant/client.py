"""拼多多商家 HTTP 会话与平台成功码。"""
from commerce_api.runtime.backend import BackendClient
import copy


class Client(BackendClient):
    success_codes = {0, 1000000}
    auth_codes = {"43001"}

    async def identity(self):
        body = await self.post("https://mms.pinduoduo.com/janus/api/userinfo", {})
        data = body.get("result", {}).get("mall", {})
        return self.bind_identity(data.get("mall_name"), data.get("mall_id"))

    async def parent_identity(self):
        """Check the merchant without overwriting a child portal's cookie jar.

        Live comparison confirmed that janus/userinfo rotates shared cookies.
        Accepting those Set-Cookies into the promotion connection invalidates
        its otherwise valid endpoint context. The verification connection is
        deliberately isolated; target responses still refresh the target jar.
        """
        client = Client(self.spec, copy.deepcopy(self.credential), self.profile, transport=self.transport)
        try:
            return await client.identity()
        finally:
            await client.close()
