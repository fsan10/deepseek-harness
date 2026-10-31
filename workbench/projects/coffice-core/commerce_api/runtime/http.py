"""Independent HTTP transport. No browser, page, CDP, or DOM dependency."""
from __future__ import annotations

import json
import re
from http.cookiejar import Cookie
from urllib.parse import urlsplit

import httpx

from ..core.errors import AuthRequired, ContractError, NeedsHuman, NetworkError, OutcomeUnknown


def domain_matches(host: str, domains) -> bool:
    return any(host == d.lstrip(".") or host.endswith("." + d.lstrip(".")) for d in domains)


def cookie_jar(cookies: list[dict], hosts: tuple[str, ...]) -> httpx.Cookies:
    jar = httpx.Cookies()
    for item in cookies:
        domain = str(item.get("domain", ""))
        if not domain or not any(domain_matches(host, (domain,)) for host in hosts):
            continue
        expires = item.get("expires")
        jar.jar.set_cookie(Cookie(0, item["name"], item["value"], None, False, domain, True,
            domain.startswith("."), item.get("path", "/"), True, bool(item.get("secure", True)),
            int(expires) if expires and expires > 0 else None, False, None, None, {}, False))
    return jar


class HttpSession:
    def __init__(self, backend, credential: dict, *, store=None, transport=None, timeout=40):
        self.backend = backend
        self.credential = credential
        self.store = store
        self.last_cookie_updates = []
        # Backends may sign the final serialized request. This hook runs before
        # the network operation, including non-JSON verification/download calls.
        self.request_signer = None
        if credential.get("platform") != backend.platform or credential.get("backend") != backend.id:
            raise AuthRequired("后台会话归属不匹配，禁止混用", stage="auth")
        if not credential.get("user_agent"):
            raise AuthRequired("会话缺少浏览器身份信息，请重新认证", stage="auth")
        self.client = httpx.AsyncClient(cookies=cookie_jar(credential.get("cookies", []), backend.domains),
            headers={"User-Agent": credential["user_agent"], "Accept": "application/json, text/plain, */*"},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10)), follow_redirects=False,
            trust_env=False, proxy=credential.get("proxy") or None, transport=transport)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        await self.client.aclose()

    def snapshot(self) -> dict:
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                    "secure": c.secure, "expires": c.expires or -1} for c in self.client.cookies.jar]
        return {**self.credential, "cookies": cookies}

    def persist(self):
        if self.store and self.credential.get("key"):
            self.store.refresh(self.credential["key"], self.snapshot())

    def validate_url(self, url: str):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not domain_matches(parsed.hostname or "", self.backend.domains):
            raise ContractError("拒绝未登记的后台接口地址", stage="request")

    def headers(self, url: str, extra: dict | None = None) -> dict:
        from .contexts import context_key
        context = self.credential.get("contexts", {}).get(context_key(url), {})
        if not context and "/h5/" in urlsplit(url).path:
            parsed = urlsplit(url)
            context = next((value for value in self.credential.get("contexts", {}).values()
                if (urlsplit(value.get("url", "")).hostname, urlsplit(value.get("url", "")).path)
                == (parsed.hostname, parsed.path)), {})
        captured = context.get("headers", {})
        forbidden = {"cookie", "host", "content-length", "connection", "accept-encoding", "authorization"}
        # HTTP header names are case-insensitive. A plain dict is not: retaining
        # captured 'origin' and adding 'Origin' sends duplicate values and breaks
        # PDD's request-context validation.
        headers = {key.lower(): value for key, value in captured.items() if key.lower() not in forbidden and not key.lower().startswith(":")}
        if self.backend.platform == "jd":
            # Read-only capture probes confirmed the merchant gateway accepts
            # changed payloads without replaying browser-generated signatures.
            headers = {k: v for k, v in headers.items() if k.lower() not in {"h5st", "dsm-trace-id"}}
        headers.setdefault("referer", context.get("referer") or self.backend.home)
        page = urlsplit(headers["referer"])
        headers.setdefault("origin", f"{page.scheme}://{page.netloc}")
        csrf = next((c.value for c in self.client.cookies.jar if c.name.lower() in {"csrftoken", "csrf_token"} and domain_matches(urlsplit(url).hostname or "", (c.domain,))), None)
        if csrf:
            headers["x-csrftoken"] = csrf
        headers.update({key.lower(): value for key, value in (extra or {}).items()})
        return headers

    async def request(self, method: str, url: str, *, params=None, payload=None, form=None,
                      headers=None, effect="read", allow_download_redirect=False) -> httpx.Response:
        self.validate_url(url)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ContractError("不支持的 HTTP 方法")
        try:
            request = self.client.build_request(method, url, params=params, json=payload, data=form,
                                                headers=self.headers(url, headers))
            if self.request_signer is not None:
                self.request_signer(request)
            response = await self.client.send(request)
        except httpx.RequestError:
            error = NetworkError if effect == "read" else OutcomeUnknown
            raise error("请求中断；查询可重试，已提交操作须先核查服务端状态", stage="request") from None
        self.last_cookie_updates = [(c.name, c.domain, c.path) for c in response.cookies.jar]
        self.persist()
        if response.status_code == 401 or response.is_redirect and re.search(r"login|passport|signin", response.headers.get("location", ""), re.I):
            raise AuthRequired("目标后台认证已失效", stage="request")
        if response.status_code in {403, 412, 418, 429}:
            raise NeedsHuman(f"后台要求检查权限、验证或请求频率（HTTP {response.status_code}）", stage="request")
        if response.is_redirect and allow_download_redirect:
            return response
        if response.status_code >= 500 and effect != "read":
            raise OutcomeUnknown("服务端未确认操作结果，请先查询原任务", stage="request")
        if not response.is_success:
            raise ContractError(f"接口返回 HTTP {response.status_code}", stage="request")
        return response

    async def json(self, method: str, url: str, **kwargs):
        response = await self.request(method, url, **kwargs)
        try:
            # Older merchant endpoints return JSON with a declared GBK charset.
            # response.json() decodes the bytes as UTF-8 and rejects those valid
            # responses; the HTTP text decoder respects the declared charset.
            body = json.loads(response.text.lstrip("\ufeff"))
        except ValueError:
            match = re.fullmatch(r"[A-Za-z_$][\w$]*\((.*)\);?", response.text.strip(), re.S)
            if match:
                try:
                    body = json.loads(match[1])
                except ValueError:
                    raise ContractError("JSONP 数据结构异常", stage="response") from None
            elif re.search(r"passport|login-form|loginForm|loginmyseller|login\.m\.taobao\.com/login\.htm|login\.taobao\.com/member", response.text, re.I):
                raise AuthRequired("后台返回登录页面", stage="response") from None
            elif re.search(r"baxia|x5sec|rgv587|nc-container|punish|安全验证|请完成.{0,10}验证", response.text, re.I):
                raise NeedsHuman("后台返回安全验证页面，已停止业务请求", stage="response") from None
            else:
                raise ContractError("后台返回非 JSON，不能作为零数据", stage="response",
                    details={"content_type": response.headers.get("content-type", "").split(";")[0][:80]}) from None
        if not isinstance(body, (dict, list)):
            raise ContractError("接口返回结构异常", stage="response")
        if isinstance(body, dict):
            code = body.get("error_code", body.get("errorCode", body.get("code", body.get("status_code"))))
            message = str(body.get("msg") or body.get("message") or body.get("error_msg") or body.get("errorMsg") or "")
            if self.backend.platform == "pinduoduo" and str(code) == "43001":
                raise AuthRequired("拼多多会话已过期", stage="response")
            if re.search(r"未登录|请先登录|登录失效|登录过期|重新登录|not.?login|login.?required|未登陆|SESSION_EXPIRED|TOKEN_EXPIRED|NEED_LOGIN", message, re.I):
                raise AuthRequired("平台明确返回认证失效", stage="response")
            success_flag = body.get("success")
            explicitly_successful = str(success_flag).lower() != "false" and (success_flag is True or
                str(success_flag).lower() == "true" or str(code) in {"0", "1", "200", "1000", "100000", "1000000", "success"})
            if not explicitly_successful and re.search(r"验证码|滑块|安全验证|无权限|权限不足|风控|存在风险|环境.{0,8}风险|频繁|二次验证|签名错误|签名失败", message):
                from ..core.errors import redact
                from .contexts import context_key
                raise NeedsHuman("平台要求验证、权限或请求上下文检查", stage="response",
                    details={"business_code": str(code), "reason": redact(message)[:160], "api": context_key(url)})
        return body
