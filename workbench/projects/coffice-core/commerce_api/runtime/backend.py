"""Base for endpoint adapters; platform-specific success and identity stay local."""
from __future__ import annotations

import copy
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..core.errors import AuthRequired, ContextRequired, ContractError, IdentityMismatch, NeedsHuman, redact
from .contexts import context_key
from .http import HttpSession


class BackendClient:
    success_codes = {0}
    auth_codes: set[str] = set()
    session_query_keys: set[str] = set()

    def __init__(self, spec, credential, profile, *, store=None, transport=None):
        self.spec, self.credential, self.profile = spec, credential, profile
        self.transport = transport
        self.http = HttpSession(spec, credential, store=store, transport=transport)
        self.identity_data = {}

    async def close(self):
        await self.http.close()

    def context(self, url: str, *, required=False) -> dict:
        result = self.credential.get("contexts", {}).get(context_key(url))
        if result is None and "/h5/" in urlsplit(url).path:
            expected = urlsplit(url)
            result = next((value for value in self.credential.get("contexts", {}).values()
                if (urlsplit(value.get("url", "")).hostname, urlsplit(value.get("url", "")).path)
                == (expected.hostname, expected.path)), None)
        if result is None and required:
            raise ContextRequired("该接口缺少已验证的认证上下文，请先执行指定后台认证", stage="context")
        return copy.deepcopy(result or {})

    def template(self, url: str, *, required=False) -> dict:
        raw = self.context(url, required=required).get("post_data")
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = dict(parse_qsl(raw))
        if not isinstance(value, dict):
            raise ContractError("接口请求模板不是对象", stage="context")
        return value

    def prepare_url(self, url: str) -> str:
        if not self.session_query_keys:
            return url
        parts = urlsplit(url)
        context = self.context(url)
        if not context:
            context = next(iter(self.credential.get("contexts", {}).values()), {})
        saved = dict(parse_qsl(urlsplit(context.get("url", "")).query, keep_blank_values=True))
        query = {k: v for k, v in saved.items() if k in self.session_query_keys}
        query.update(dict(parse_qsl(parts.query, keep_blank_values=True)))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def validate(self, body, *, codes=None):
        if not isinstance(body, dict):
            raise ContractError("平台接口没有返回对象", stage="response")
        code = body.get("code", body.get("status_code", body.get("errorCode", body.get("error_code", body.get("result") if not isinstance(body.get("result"), (dict, list)) else None))))
        if str(code) in self.auth_codes:
            raise AuthRequired("平台明确返回认证失效码", stage="response")
        good = {str(c) for c in (self.success_codes if codes is None else codes)}
        if body.get("success") is False or (code is not None and str(code) not in good):
            message = body.get("msg") or body.get("message") or body.get("errorMsg") or body.get("error_msg") or ""
            raise ContractError("平台业务响应失败", stage="response", details={"business_code": str(code)[:40], "reason": redact(message)[:160]})
        if code is None and body.get("success") is not True:
            raise ContractError("响应缺少平台成功状态", stage="response", details={"response_keys": list(body)[:20]})
        return body

    async def json(self, method, url, *, check=True, codes=None, **kwargs):
        url = self.prepare_url(url)
        params = kwargs.pop("params", None)
        if params:
            parts = urlsplit(url)
            merged = dict(parse_qsl(parts.query, keep_blank_values=True))
            merged.update(params)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(merged, doseq=True), parts.fragment))
        body = await self.http.json(method, url, **kwargs)
        try:
            return self.validate(body, codes=codes) if check else body
        except ContractError as exc:
            exc.details["api"] = context_key(url)
            raise

    async def get(self, url, params=None, **kwargs):
        return await self.json("GET", url, params=params, **kwargs)

    async def post(self, url, payload=None, **kwargs):
        return await self.json("POST", url, payload=payload, **kwargs)

    def bind_identity(self, name, identifier, **extra):
        expected, actual = self.profile.shop, str(name or "")
        # The existing, explicitly confirmed Kuaishou spelling alias is preserved.
        aliases = {"MOCK禧饮咖啡专卖店": "MOCK禧饮专卖店"} if self.profile.platform == "kuaishou" else {}
        if not actual or identifier in (None, ""):
            raise ContractError("身份接口缺少店铺名称或稳定标识", stage="identity")
        if aliases.get(actual, actual) != aliases.get(expected, expected):
            raise IdentityMismatch("HTTP 实际店铺与 Profile 绑定不一致", stage="identity")
        pinned = self.credential.get("identity", {})
        if pinned.get("shop_id") and str(pinned["shop_id"]) != str(identifier):
            raise IdentityMismatch("真实店铺稳定标识发生变化，拒绝自动接受新身份", stage="identity")
        # A parent-shop proof must not erase a child's pinned account before
        # the child check finishes. Otherwise a failed SSO check can silently
        # remove the account fence for the next attempt.
        pinned_accounts = {key: pinned[key] for key in ("advertiser_id", "fund_account_fingerprint") if key in pinned}
        identity = {**pinned_accounts, "shop_name": actual, "shop_id": str(identifier), "backend": self.spec.id,
                    "transport": "direct_http", **extra}
        self.identity_data = identity
        self.credential["identity"] = identity
        self.http.credential["identity"] = identity
        self.http.persist()
        return identity
