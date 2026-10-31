"""抖店独立 HTTP 客户端；会话上下文与每次请求的本地签名。"""
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from commerce_api.core.errors import ContextRequired
from commerce_api.runtime.contexts import context_key
from commerce_api.runtime.http import domain_matches
from commerce_api.runtime.backend import BackendClient
from .signing import Signer, derive_material, strip_signature


class Client(BackendClient):
    success_codes = {0}
    auth_codes = {"1000004", "1000005", "10008"}
    # These are session/device context, not a reusable per-request signature.
    session_query_keys = {"appid", "__token", "_bid", "aid", "_lid"}
    order_session_query_keys = session_query_keys | {"msToken", "verifyFp", "fp"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signers = {}
        self.http.request_signer = self._sign_request

    def _contexts(self, url):
        """Only the current merchant credential can supply signing context."""
        path = urlsplit(url).path
        contexts = [value for value in self.credential.get("contexts", {}).values()
            if urlsplit(value.get("url", "")).hostname == "fxg.jinritemai.com"]
        def rank(value):
            candidate = urlsplit(value["url"]).path
            priority = 0 if candidate == path else 1 if candidate.startswith(("/api/order/", "/order/torder/")) else 2
            return priority
        # Within each priority prefer the freshest authenticated SDK sample.
        contexts.sort(key=lambda value: value.get("captured_at", ""), reverse=True)
        return sorted(contexts, key=rank)

    def prepare_url(self, url):
        parts = urlsplit(url)
        if parts.hostname != "fxg.jinritemai.com" or not parts.path.startswith(("/api/order/", "/order/torder/")):
            return super().prepare_url(url)
        context = next(iter(self._contexts(url)), {})
        saved = dict(parse_qsl(urlsplit(context.get("url", "")).query, keep_blank_values=True))
        query = {key: value for key, value in saved.items() if key in self.order_session_query_keys}
        query.update(dict(parse_qsl(parts.query, keep_blank_values=True)))
        # Prefer a fresh scoped token received by independent HTTP to its older
        # captured query value. Never synthesize tokens or a device identity.
        current = next((cookie.value for cookie in self.http.client.cookies.jar
            if cookie.name == "msToken" and not cookie.is_expired() and domain_matches(parts.hostname, (cookie.domain,))
            and (parts.path == cookie.path or parts.path.startswith(cookie.path.rstrip("/") + "/"))), None)
        if current is not None:
            query["msToken"] = current
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _sign_request(self, request):
        if request.url.host != "fxg.jinritemai.com" or not request.url.path.startswith(("/api/order/", "/order/torder/")):
            return
        if request.headers.get("user-agent") != self.credential["user_agent"]:
            raise ContextRequired("抖店请求身份与签名上下文不一致", stage="context")
        key = context_key(str(request.url))
        signer = self._signers.get(key)
        if signer is None:
            for context in self._contexts(str(request.url)):
                try:
                    material = derive_material(context["url"], self.credential["user_agent"],
                        (context.get("post_data") or "").encode())
                except ContextRequired:
                    continue
                signer = self._signers[key] = Signer(material, self.credential["user_agent"])
                break
            if signer is None:
                raise ContextRequired("抖店订单缺少已校验的本地签名上下文，请显式认证更新", stage="context")
        query = strip_signature(request.url.query.decode("ascii"))
        signature = signer.sign(query, request.content)
        query += ("&" if query else "") + "a_bogus=" + quote(signature, safe="")
        request.url = request.url.copy_with(query=query.encode("ascii"))

    async def identity(self):
        body = await self.get("https://fxg.jinritemai.com/center/qualification/shop/info",
                              params={"version": 0, "appid": 1, "_bid": "fxg_admin"})
        data = body.get("data") or {}
        return self.bind_identity(data.get("shop_name"), data.get("shop_id") or data.get("qual_id"))
