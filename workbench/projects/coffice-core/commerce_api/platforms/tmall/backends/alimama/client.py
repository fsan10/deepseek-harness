"""淘宝联盟独立会话与令牌。"""
from ...client import TmallClient


class Client(TmallClient):
    async def identity(self):
        import time
        from commerce_api.core.errors import ContractError
        identity = await super().identity()
        body = await self.get("https://ad.alimama.com/openapi/param2/1/gateway.unionadv/shopkeeper.rpt.process.list.json", {
            "_tb_token_": self.tb_token(), "t": int(time.time() * 1000), "pageNo": 1, "pageSize": 20, "bizTypeList": "105,96"})
        if not isinstance(body.get("data"), dict) or not isinstance(body["data"].get("result"), list):
            raise ContractError("淘宝联盟未返回有效的授权后报表列表", stage="identity")
        return self.bind_identity(identity["shop_name"], identity["shop_id"], scopes=["shop_identity", "alimama_report_read"])
