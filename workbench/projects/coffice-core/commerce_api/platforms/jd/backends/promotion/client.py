"""京准通 API 会话独立于商家报表 scope。"""
from commerce_api.platforms.jd.backends.merchant.client import Client as MerchantClient


class Client(MerchantClient):
    async def identity(self):
        from datetime import datetime, timedelta
        from commerce_api.core.contracts import CN
        identity = await super().identity()
        day = (datetime.now(CN).date() - timedelta(days=1)).isoformat()
        await self.post("https://jzt-api.jd.com/union/pop/account/list/billList?requestFrom=0", {
            "dateType": 2, "startDate": day, "endDate": day, "endDateForSubmit": day,
            "billStatus": 2, "pageIndex": 1, "pageSize": 1, "withDailyData": 0})
        return {**identity, "scopes": ["merchant_identity", "promotion_read"]}
