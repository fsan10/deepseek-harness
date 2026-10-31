"""Tmall HTTP protocol primitives, including fresh per-request MTop signing."""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from commerce_api.core.errors import AuthRequired, ContextRequired, ContractError, NeedsHuman
from commerce_api.runtime.backend import BackendClient
from commerce_api.runtime.contexts import context_key
from commerce_api.runtime.http import domain_matches


class TmallClient(BackendClient):
    success_codes = {0, 200, "success"}

    def signer_cookie(self, url):
        request_path = urlsplit(url).path or "/"
        cookies = [c for c in self.http.client.cookies.jar if c.name == "_m_h5_tk"
            and domain_matches("h5api.m.taobao.com", (c.domain,)) and not c.is_expired()
            and (request_path == c.path or request_path.startswith(c.path.rstrip("/") + "/"))]
        binding = self.credential.get("mtop_signer_domains", {}).get(context_key(url))
        if binding:
            selected = next((c for c in cookies if [c.domain, c.path] == binding), None)
            if selected:
                return selected.value.split("_", 1)[0]
        # A captured signature identifies the cookie that actually signed the
        # request. Domain/order guesses are unsafe after mobile/desktop SSO.
        contexts = [self.context(url), *self.credential.get("contexts", {}).values()]
        for context in contexts:
            query = dict(parse_qsl(urlsplit(context.get("url", "")).query))
            if not all(query.get(k) for k in ("sign", "t", "appKey", "data")):
                continue
            matches = [c for c in cookies if hashlib.md5(
                f"{c.value.split('_', 1)[0]}&{query['t']}&{query['appKey']}&{query['data']}".encode()).hexdigest() == query["sign"]]
            if matches:
                cookie = matches[0]
                self.credential.setdefault("mtop_signer_domains", {})[context_key(url)] = [cookie.domain, cookie.path]
                return cookie.value.split("_", 1)[0]
        tokens = {c.value.split("_", 1)[0] for c in cookies}
        if len(tokens) > 1:
            raise ContextRequired("MTop 存在多个签名 Cookie，尚无证据确定签名范围，请显式认证提取上下文", stage="context")
        return next(iter(tokens), "")

    async def mtop(self, api, data, *, effect="read", headers=None):
        path = f"/h5/{api}/1.0/"
        url = "https://h5api.m.taobao.com" + path
        captured = self.context(url)
        template = dict(parse_qsl(urlsplit(captured.get("url", "")).query))
        app_key = template.get("appKey", "12574478")
        for attempt in range(2):
            token = self.signer_cookie(url)
            stamp = str(int(time.time() * 1000))
            raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            sign = hashlib.md5(f"{token}&{stamp}&{app_key}&{raw}".encode()).hexdigest()
            params = {"jsv": template.get("jsv", "2.6.1"), "appKey": app_key,
                "api": api, "v": "1.0", "t": stamp, "sign": sign, "data": raw,
                "type": "originaljson", "dataType": "json", "ttid": template.get("ttid", "11320@taobao_WEB_9.9.99")}
            body = await self.http.json("GET", url, params=params, effect=effect, headers=headers)
            updates = [(domain, path) for name, domain, path in self.http.last_cookie_updates if name == "_m_h5_tk"]
            if updates:
                self.credential.setdefault("mtop_signer_domains", {})[context_key(url)] = list(updates[-1])
                self.http.persist()
            ret = body.get("ret")
            if not isinstance(ret, list) or not ret:
                raise ContractError("MTop 响应缺少 ret 状态")
            if all(str(value).startswith("SUCCESS::") for value in ret):
                return body
            message = " ".join(str(value) for value in ret)
            if any(key in message for key in {"TOKEN_EXPIRED", "TOKEN_EMPTY"}) and not attempt and effect == "read":
                # MTop refreshes its token via Set-Cookie. Sign again locally,
                # using the updated HTTP cookie jar; do not open a browser.
                continue
            if any(key in message for key in {"SESSION_EXPIRED", "TOKEN_EXPIRED", "TOKEN_EMPTY", "NEED_LOGIN"}):
                raise AuthRequired("天猫目标后台认证失效", stage="request")
            raise NeedsHuman("天猫接口要求检查授权、签名上下文或平台验证", stage="request")

    async def identity(self):
        body = await self.mtop("mtop.taobao.jdy.resource.shop.info.get", {},
            headers={"referer": "https://qn.taobao.com/", "origin": "https://qn.taobao.com"})
        data = body.get("data", {}).get("result", {})
        return self.bind_identity(data.get("shopName"), data.get("shopId"), account_nick=data.get("nick"))

    def tb_token(self):
        from commerce_api.runtime.http import domain_matches
        values = [cookie.value for cookie in self.http.client.cookies.jar if cookie.name == "_tb_token_"
                  and domain_matches("ad.alimama.com", (cookie.domain,))]
        if not values:
            for context in self.credential.get("contexts", {}).values():
                value = dict(parse_qsl(urlsplit(context.get("url", "")).query)).get("_tb_token_")
                if value:
                    return value
            raise AuthRequired("阿里妈妈会话缺少认证令牌", stage="auth")
        return values[-1]
