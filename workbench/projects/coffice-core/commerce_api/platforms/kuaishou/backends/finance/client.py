"""快手财务 scope；HTTP 会话与小店保持隔离。"""
from commerce_api.platforms.kuaishou.backends.merchant.client import Client as MerchantClient


class Client(MerchantClient):
    async def identity(self):
        identity = await super().identity()
        await self.post("https://s.kwaixiaodian.com/rest/app/tts/business/api/funds/wallet/sub/query/info", {
            "accountRole": "ACCOUNT_ROLE_SELLER", "accountType": "ACCOUNT_TYPE_WALLET_PINGAN", "bidBizType": "seller_or_promoter"})
        return self.bind_identity(identity["shop_name"], identity["shop_id"], scopes=["merchant_identity", "finance_read"])
