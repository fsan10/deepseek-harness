"""拼多多推广后台独立 HTTP scope。"""
from commerce_api.platforms.pinduoduo.backends.merchant.client import Client as MerchantClient


class Client(MerchantClient):
    success_codes = {0, 1000, 1000000}

    async def identity(self):
        identity = await self.parent_identity()
        body = await self.post("https://yingxiao.pinduoduo.com/mms-gateway/user/checkToken", {})
        if body.get("result") is not True:
            from commerce_api.core.errors import AuthRequired
            raise AuthRequired("拼多多推广后台会话未通过独立验证", stage="identity")
        return self.bind_identity(identity["shop_name"], identity["shop_id"], scopes=["merchant_identity", "promotion_read"])
