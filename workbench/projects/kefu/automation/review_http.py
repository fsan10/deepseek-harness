"""独立 HTTP 传输。此模块不导入浏览器、Playwright、CDP 或页面脚本。"""
from __future__ import annotations

import json
from http.cookiejar import Cookie
import httpx
from .review_errors import AuthRequired, ContractError, HumanRequired, NetworkError, ReviewError

ORIGIN = "https://fxg.jinritemai.com"
SHOP_PATH = "/center/qualification/shop/info"
ALLOWED_PATHS = {SHOP_PATH, "/product/tcomment/commentList", "/api/order/orderDetail"}


class DirectHttpSession:
    def __init__(self, profile: dict, credentials: dict, *, store=None, on_state=None, transport=None):
        if credentials.get("profile_id") != profile["profile_id"]:
            raise AuthRequired("登录会话与店铺 profile 不一致，请重新登录")
        self.profile = profile; self.credentials = credentials; self.store = store; self.on_state = on_state
        jar = httpx.Cookies()
        for item in credentials.get("cookies", []):
            domain = str(item.get("domain", ""))
            if not (domain.lstrip(".") == "jinritemai.com" or domain.lstrip(".").endswith(".jinritemai.com")):
                continue
            expires = item.get("expires")
            jar.jar.set_cookie(Cookie(0, item["name"], item["value"], None, False, domain, bool(domain), domain.startswith("."),
                                      item.get("path", "/"), True, bool(item.get("secure", True)),
                                      int(expires) if expires and expires > 0 else None, False, None, None, {}, False))
        self.client = httpx.AsyncClient(
            headers={"User-Agent": credentials["user_agent"], "Accept": "application/json, text/plain, */*",
                     "Origin": ORIGIN, "Referer": ORIGIN + "/ffa/mshop/homepage/index"},
            cookies=jar, timeout=httpx.Timeout(30, connect=8), follow_redirects=False, transport=transport, trust_env=False,
        )

    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.client.aclose()

    def _state(self, state: str, message: str, code: str = "", shop_name: str = ""):
        if self.on_state:
            self.on_state(state, message, code, shop_name)

    def snapshot(self) -> dict:
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure, "expires": c.expires or -1}
                   for c in self.client.cookies.jar]
        return {**self.credentials, "cookies": cookies}

    async def get_json(self, path: str, query=None, *, label: str, expected_codes=None, **_):
        try:
            return await self._get_json(path, query, label=label, expected_codes=expected_codes)
        except ReviewError as exc:
            if not isinstance(exc, (HumanRequired, NetworkError)):
                self._state("error", str(exc), exc.code)
            raise

    async def _get_json(self, path: str, query=None, *, label: str, expected_codes=None):
        if path not in ALLOWED_PATHS:
            raise ContractError("不支持的 WebAPI 路径")
        try:
            response = await self.client.get(ORIGIN + path, params=query)
        except httpx.RequestError:
            self._state("error", "网络请求失败，尚不能判断登录是否失效", "NETWORK_ERROR")
            raise NetworkError(f"{label}网络请求失败，请检查网络后重试") from None
        status = response.status_code
        location = response.headers.get("location", "")
        if status == 401 or status in {301, 302, 303, 307, 308} and "/login" in location:
            self._state("auth_required", "登录已失效，请重新登录", "AUTH_REQUIRED")
            raise AuthRequired("店铺登录已失效，请重新执行登录操作")
        if status in {403, 412, 418, 429}:
            self._state("needs_human", "平台要求检查权限、安全验证或请求频率", "NEEDS_HUMAN")
            raise HumanRequired(f"{label}返回 HTTP {status}，请在对应 profile 检查权限或验证")
        if status < 200 or status >= 300:
            raise ReviewError(f"{label}返回 HTTP {status}")
        try:
            body = json.loads(response.text)
        except (ValueError, TypeError):
            if "/login" in str(response.url) or "passport.bytedance.com" in response.text or 'id="ecomLoginForm"' in response.text:
                self._state("auth_required", "登录已失效，请重新登录", "AUTH_REQUIRED")
                raise AuthRequired("店铺登录已失效，请重新执行登录操作") from None
            raise ContractError(f"{label}返回非 JSON，不能按无数据处理") from None
        if not isinstance(body, dict):
            raise ContractError(f"{label}返回结构异常")
        if str(body.get("code")) not in {str(c) for c in (expected_codes or {0})}:
            message = str(body.get("msg") or body.get("message") or "")
            if any(text in message for text in ("未登录", "请先登录", "登录失效", "登录过期", "重新登录")):
                self._state("auth_required", "登录已失效，请重新登录", "AUTH_REQUIRED")
                raise AuthRequired("店铺登录已失效，请重新执行登录操作")
            if any(text in message for text in ("验证码", "验证", "权限", "风控", "频繁", "安全")):
                self._state("needs_human", "平台要求人工检查权限或验证", "NEEDS_HUMAN")
                raise HumanRequired(f"{label}需要人工检查权限或验证")
            raise ReviewError(f"{label}业务响应失败，请核对接口状态")
        if self.store:
            self.store.refresh(self.profile["profile_id"], self.snapshot())
        return body

    async def check_identity(self) -> dict:
        body = await self.get_json(SHOP_PATH, {"version": 0, "appid": 1, "_bid": "fxg_admin"}, label="店铺登录状态")
        data = body.get("data")
        shop = str(data.get("shop_name") or "").strip() if isinstance(data, dict) else ""
        if not shop:
            self._state("error", "店铺身份接口缺少店铺名称", "CONTRACT_ERROR")
            raise ContractError("店铺身份接口缺少店铺名称")
        if self.profile.get("shop_name") and shop != self.profile["shop_name"] or shop == "MOCK吉饮咖啡专卖店":
            self._state("needs_human", "当前会话店铺与 profile 备注不一致", "SHOP_MISMATCH", shop)
            raise HumanRequired("当前会话店铺与 profile 备注不一致，请重新确认登录店铺")
        self._state("valid", "登录有效", "", shop)
        return {"profile_id": self.profile["profile_id"], "shop_name": shop, "state": "valid", "transport": "direct_http"}
