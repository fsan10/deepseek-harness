"""对账中心使用独立 scope；商家身份与财务可用性分别检查。"""
from commerce_api.platforms.pinduoduo.backends.merchant.client import Client as MerchantClient


class Client(MerchantClient):
    async def identity(self):
        identity = await self.parent_identity()
        await self.post("https://cashier.pinduoduo.com/templar/api/bill/queryBillDownloadTaskList?__app_code=113", {"page": 1, "size": 1})
        return self.bind_identity(identity["shop_name"], identity["shop_id"], scopes=["merchant_identity", "cashier_read"])
