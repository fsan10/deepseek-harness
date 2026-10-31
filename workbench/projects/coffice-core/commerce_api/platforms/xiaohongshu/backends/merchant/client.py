"""千帆商家后台 HTTP 客户端，动态头按 endpoint 保存。"""
from commerce_api.runtime.backend import BackendClient


class Client(BackendClient):
    success_codes = {0}

    async def identity(self):
        body = await self.get("https://ark.xiaohongshu.com/api/edith/seller/info/v2")
        data = body.get("data") or {}
        return self.bind_identity(data.get("seller_name"), data.get("seller_id"))
