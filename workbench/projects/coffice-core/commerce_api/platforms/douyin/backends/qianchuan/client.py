"""千川会话独立验证店铺、广告账户和财务权限。"""
from urllib.parse import parse_qs, urlsplit

from commerce_api.runtime.backend import BackendClient
from commerce_api.core.errors import ContextRequired, IdentityMismatch, NeedsHuman

ORIGIN = "https://qianchuan.jinritemai.com"
USER = ORIGIN + "/ad/api/v1/account/user/info"
FINANCE = ORIGIN + "/cg_trade/finance/backend/"


class Client(BackendClient):
    success_codes = {0, 1}
    session_query_keys = {"gfversion", "aavid", "aadvid"}

    def advertiser(self):
        value = self.credential.get("account_id")
        if not value:
            for context in self.credential.get("contexts", {}).values():
                query = parse_qs(urlsplit(context.get("url", "")).query)
                value = (query.get("aadvid") or query.get("aavid") or [None])[0]
                if value:
                    break
        if not value or not str(value).isdigit():
            raise ContextRequired("千川缺少已确认的广告账户，请执行千川后台认证", stage="identity")
        return str(value)

    async def finance(self, path, params=None):
        return await self.get(FINANCE + path, {**(params or {}), "aadvid": self.advertiser()}, codes={1})

    async def identity(self):
        identifier = self.advertiser()
        body = await self.get(USER, {"aavid": identifier}, codes={0})
        data = body.get("data") or {}
        shop, account = data.get("shopInfo") or {}, data.get("accountInfo") or {}
        if str(account.get("advId")) != identifier:
            raise IdentityMismatch("千川实际广告账户与会话绑定不一致", stage="identity")
        pinned = self.credential.get("identity", {})
        if pinned.get("advertiser_id") and pinned["advertiser_id"] != identifier:
            raise IdentityMismatch("千川广告账户发生变化", stage="identity")
        permissions = (await self.finance("funds/permission")).get("data") or {}
        if permissions.get("finance_read") is not True:
            raise NeedsHuman("千川账户缺少财务读取权限", stage="identity")
        return self.bind_identity(shop.get("shopName"), shop.get("shopId"), advertiser_id=identifier,
            scopes=["shop_identity", "advertiser_identity", "finance_read"])
