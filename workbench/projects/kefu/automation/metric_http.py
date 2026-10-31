"""商家 WebAPI 传输。此模块禁止导入浏览器或执行页面脚本。"""
from __future__ import annotations

import json
import re
import hashlib
import time
from http.cookiejar import Cookie
from urllib.parse import urlsplit

import httpx

from .metric_profiles import PLATFORMS
from .review_errors import AuthRequired, ContractError, HumanRequired, NetworkError, ReviewError

# 每个路径均是只读查询；即使平台使用 POST，也不允许任意路径或跨平台请求。
ENDPOINTS = {
    "douyin": {
        ("fxg.jinritemai.com", "/center/qualification/shop/info"),
        ("fxg.jinritemai.com", "/governance/shop/experiencescore/getOverviewV10"),
        ("fxg.jinritemai.com", "/governance/shop/experiencescore/getSubScoreMetricsV10"),
        ("pigeon.jinritemai.com", "/backstage/data/shop_data_list_v2"),
        ("pigeon.jinritemai.com", "/backstage/data/shop_core_data"),
    },
    "pinduoduo": {
        ("mms.pinduoduo.com", "/janus/api/checkLogin"),
        ("mms.pinduoduo.com", "/janus/api/userinfo"),
        ("mms.pinduoduo.com", "/desert/stat/mallServiceOverviewData"),
        ("mms.pinduoduo.com", "/desert/stat/mallMonthServiceData"),
        ("mms.pinduoduo.com", "/sydney/api/mallService/getMallServeScoreV2"),
    },
    "jd": {("ddmall.jd.com", "/user-info.do"), ("ddmall.jd.com", "/mall/api"), ("kf.jd.com", "/jingmai/T1/queryIndicatorOverview")},
    "kuaishou": {("syt.kwaixiaodian.com", "/rest/business/analysis/account/info"),
                  ("syt.kwaixiaodian.com", "/rest/business/gateway/service/data")},
    "xiaohongshu": {("ark.xiaohongshu.com", "/api/edith/seller/info/v2"),
                     ("ark.xiaohongshu.com", "/api/edith/butterfly/data")},
    "tmall": {("sycm.taobao.com", "/csp/api/token/generate.json"),
              ("sycm.taobao.com", "/csp/api/account/info.json"),
              ("sycm.taobao.com", "/csp/api/core/monitor/overview/list"),
              *{("h5api.m.taobao.com", "/h5/" + api + "/1.0/") for api in (
                  "mtop.alibaba.tmall.query.date", "mtop.alibaba.tmall.front.store.index", "mtop.sdx.nps.home.indexsummary",
                  "mtop.taobao.jdy.resource.shop.info.get")}},
}


def cookie_jar(cookies, domains):
    jar = httpx.Cookies()
    for c in cookies:
        domain = str(c.get("domain", ""))
        host = domain.lstrip(".")
        if not any(host == d or host.endswith("." + d) for d in domains):
            continue
        expiry = c.get("expires")
        jar.jar.set_cookie(Cookie(0, c["name"], c["value"], None, False, domain, bool(domain), domain.startswith("."),
                                  c.get("path", "/"), True, bool(c.get("secure", True)),
                                  int(expiry) if expiry and expiry > 0 else None, False, None, None, {}, False))
    return jar


class MetricHttpSession:
    def __init__(self, profile, credentials, *, store=None, transport=None):
        self.profile = profile
        self.platform = profile["platform"]
        if credentials.get("profile_id") != profile["profile_id"] or credentials.get("platform", self.platform) != self.platform:
            raise AuthRequired("登录会话与 profile 平台不一致，请重新登录")
        self.credentials = credentials
        self.store = store
        self.client = httpx.AsyncClient(cookies=cookie_jar(credentials.get("cookies", []), PLATFORMS[self.platform]["domains"]),
            headers={"User-Agent": credentials["user_agent"], "Accept": "application/json, text/plain, */*"},
            timeout=httpx.Timeout(35, connect=8), follow_redirects=False, trust_env=False, transport=transport)

    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.client.aclose()

    def snapshot(self):
        cookies = [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                    "secure": c.secure, "expires": c.expires or -1} for c in self.client.cookies.jar]
        return {**self.credentials, "cookies": cookies}

    async def request(self, url, *, method="GET", params=None, payload=None, form=None, label="平台接口", codes=None, referer=None, extra_headers=None):
        parsed = urlsplit(url)
        if method not in ("GET", "POST"): raise ContractError("商家采集仅允许已登记的查询方法")
        if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.query or parsed.fragment or (parsed.hostname, parsed.path) not in ENDPOINTS[self.platform]:
            raise ContractError("拒绝未登记的商家 WebAPI 地址")
        if self.platform == "jd" and parsed.path == "/mall/api" and (params or {}).get("m") != "getMallByOperator":
            raise ContractError("拒绝未登记的京东网关方法")
        page_url = referer or PLATFORMS[self.platform]["home"]
        origin = "https://" + urlsplit(page_url).hostname
        headers = {"Origin": origin, "Referer": page_url}
        headers.update(extra_headers or {})
        csrf = next((c.value for c in self.client.cookies.jar if c.name.lower() in ("csrftoken", "csrf_token") and parsed.hostname.endswith(c.domain.lstrip("."))), None)
        if csrf:
            headers["X-CSRFToken"] = csrf
        try:
            response = await self.client.request(method, url, params=params, json=payload, data=form, headers=headers)
        except httpx.RequestError:
            raise NetworkError(f"{label}网络请求失败，请检查网络后重试") from None
        if response.status_code == 401 or response.is_redirect and re.search(r"login|passport|signin", response.headers.get("location", ""), re.I):
            raise AuthRequired("店铺登录失效，请在采集设置中重新登录")
        if response.status_code in (403, 412, 418, 429):
            raise HumanRequired(f"{label}需要检查权限、验证或请求频率（HTTP {response.status_code}）")
        if not response.is_success:
            raise ReviewError(f"{label}返回 HTTP {response.status_code}")
        try:
            try:
                body = response.json()
            except ValueError:
                # 部分旧版 MTop 仅支持 JSONP；只解 JSON 参数，不执行 JavaScript。
                match = re.fullmatch(r"[A-Za-z_$][\w$]*\((.*)\);?", response.text.strip(), re.S)
                if not match: raise ValueError()
                body = json.loads(match[1])
        except ValueError:
            if re.search(r"passport|login-form|loginForm|loginmyseller", response.text, re.I):
                raise AuthRequired("店铺登录失效，请重新登录") from None
            raise ContractError(f"{label}返回非 JSON，不能作为零数据") from None
        if not isinstance(body, dict):
            raise ContractError(f"{label}返回结构异常")
        if self.platform == "jd" and parsed.path == "/user-info.do" and isinstance(body.get("userName"), str) and body["userName"]:
            return body
        if self.platform == "tmall" and parsed.hostname == "h5api.m.taobao.com":
            ret = body.get("ret")
            if not isinstance(ret, list) or not ret:
                raise ContractError(f"{label}缺少 MTop 状态")
            text = " ".join(str(v) for v in ret)
            if re.search(r"SESSION_EXPIRED|TOKEN_EXPIRED|TOKEN_EMPTY|NEED_LOGIN", text):
                raise AuthRequired("天猫会话失效，请重新登录")
            if not all(str(v).startswith("SUCCESS::") for v in ret):
                raise HumanRequired("天猫接口需要检查会话、签名或权限")
            if self.store: self.store.refresh(self.profile["profile_id"], self.snapshot())
            return body
        code = body.get("code", body.get("errorCode", body.get("error_code", body.get("result"))))
        # 拼多多失效会话仍返回 HTTP 200，error_code=43001、error_msg=会话已过期。
        # 按平台明确识别该码，让检查与采集复用自动登录恢复，不把其他业务失败当成掉线。
        if self.platform == "pinduoduo" and str(code) == "43001":
            raise AuthRequired("拼多多会话已过期，需重新登录")
        message = str(body.get("msg") or body.get("message") or body.get("errorMsg") or body.get("error_msg") or "")
        if re.search(r"未登录|请先登录|登录失效|登录过期|重新登录|not.?login|login.?required|未登陆", message, re.I):
            raise AuthRequired("店铺登录失效，请重新登录")
        spam = body.get("check_spam_resp", {})
        if re.search(r"验证码|安全验证|无权限|风控|频繁|二次验证|签名", message) or isinstance(spam, dict) and spam.get("decision") not in (None, "", "PASS"):
            raise HumanRequired(f"{label}需要人工检查权限或验证")
        good_codes = codes or {"douyin": {0}, "pinduoduo": {1000000}, "jd": {200, "success"}, "kuaishou": {1, 200}, "xiaohongshu": {0}, "tmall": {0}}[self.platform]
        if body.get("success") is False or str(code) not in {str(c) for c in good_codes}:
            raise ReviewError(f"{label}业务响应失败，请核对平台状态")
        if self.store:
            self.store.refresh(self.profile["profile_id"], self.snapshot())
        return body

    async def mtop(self, api, data):
        if self.platform != "tmall": raise ContractError("MTop 平台不匹配")
        app_key = self.credentials.get("mtop_app_key")
        tokens = {c.value.split("_")[0] for c in self.client.cookies.jar if c.name == "_m_h5_tk" and c.domain.lstrip(".").endswith("taobao.com")}
        if not app_key or len(tokens) != 1:
            raise AuthRequired("天猫认证会话不完整，请重新登录并提取会话")
        stamp = str(int(time.time() * 1000))
        serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        signature = hashlib.md5(f"{next(iter(tokens))}&{stamp}&{app_key}&{serialized}".encode()).hexdigest()
        return await self.request("https://h5api.m.taobao.com/h5/" + api.lower() + "/1.0/",
            params={"jsv": "2.6.1", "appKey": app_key, "t": stamp, "sign": signature, "api": api,
                    "v": "1.0", "type": "originaljson", "dataType": "json", "data": serialized},
            referer="https://qn.taobao.com/", label="天猫体验分接口")
