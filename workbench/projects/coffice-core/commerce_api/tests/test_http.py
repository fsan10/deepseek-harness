import unittest
import json
from types import SimpleNamespace

import httpx

from commerce_api.core.contracts import Profile
from commerce_api.core.errors import AuthRequired, ContractError, NeedsHuman
from commerce_api.core.registry import Registry
from commerce_api.runtime.http import HttpSession, cookie_jar
from commerce_api.runtime.files import download
from commerce_api.runtime.contexts import context_key
from .support import owned_temporary


def credential(platform="pinduoduo", backend="promotion"):
    return {"platform": platform, "backend": backend, "user_agent": "Fictional Test Agent",
        "cookies": [{"name": "_nano_fp", "value": "fictional-original", "domain": ".pinduoduo.com",
            "path": "/", "secure": True, "expires": -1}], "contexts": {}}


class HttpBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_kuaishou_result_is_authoritative_over_empty_or_zero_code(self):
        from commerce_api.platforms.kuaishou.backends.merchant.client import Client
        value = credential("kuaishou", "merchant")
        profile = Profile("fictional-profile", "Example", "kuaishou", "Example Company", "Example Shop")
        client = Client(Registry().backend("kuaishou", "merchant"), value, profile)
        self.addAsyncCleanup(client.close)
        self.assertEqual(client.validate({"result": 1, "code": "", "msg": "成功"})["result"], 1)
        self.assertEqual(client.validate({"result": 200, "data": {"userInfo": {}}})["result"], 200)
        with self.assertRaises(ContractError):
            client.validate({"result": 0, "code": 0, "data": {"total": 0}})

    async def test_json_uses_the_platform_declared_gbk_charset(self):
        content = json.dumps({"code": 0, "data": {"label": "账单"}}, ensure_ascii=False).encode("gb18030")
        transport = httpx.MockTransport(lambda r: httpx.Response(200, content=content,
            headers={"content-type": "application/json;charset=GB18030"}))
        async with HttpSession(Registry().backend("pinduoduo", "promotion"), credential(), transport=transport) as session:
            result = await session.json("GET", "https://yingxiao.pinduoduo.com/example")
        self.assertEqual(result["data"]["label"], "账单")

    async def test_header_names_are_case_insensitive_and_have_one_origin(self):
        url = "https://yingxiao.pinduoduo.com/example"
        value = credential()
        value["contexts"][context_key(url)] = {"headers": {"origin": "https://yingxiao.pinduoduo.com",
            "referer": "https://yingxiao.pinduoduo.com/mains/account/report", "Cookie": "forbidden"}}
        async with HttpSession(Registry().backend("pinduoduo", "promotion"), value) as session:
            request = session.client.build_request("POST", url, headers=session.headers(url,
                {"Referer": "https://yingxiao.pinduoduo.com/expected"}))
            self.assertEqual(len(request.headers.get_list("origin")), 1)
            self.assertEqual(request.headers["referer"], "https://yingxiao.pinduoduo.com/expected")
            self.assertNotIn("forbidden", request.headers.get("cookie", ""))

    async def test_http_200_pdd_expiry_is_auth_required(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"errorCode": 43001, "success": False}))
        async with HttpSession(Registry().backend("pinduoduo", "promotion"), credential(), transport=transport) as session:
            with self.assertRaises(AuthRequired):
                await session.json("POST", "https://mms.pinduoduo.com/janus/api/userinfo", payload={})

    async def test_risk_response_does_not_masquerade_as_login_expiry(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(429))
        async with HttpSession(Registry().backend("pinduoduo", "promotion"), credential(), transport=transport) as session:
            with self.assertRaises(NeedsHuman):
                await session.json("POST", "https://yingxiao.pinduoduo.com/example", payload={})

    async def test_douyin_environment_risk_stops_before_login_recovery(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200,
            json={"code": "10001010A", "msg": "当前环境存在风险，请稍后重试"}))
        value = credential("douyin", "merchant")
        async with HttpSession(Registry().backend("douyin", "merchant"), value, transport=transport) as session:
            with self.assertRaises(NeedsHuman):
                await session.json("GET", "https://fxg.jinritemai.com/order/torder/exportHistory")

    async def test_successful_sms_notice_is_not_a_risk_or_slider_failure(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 200, "msg": "验证码发送成功", "data": True}))
        async with HttpSession(Registry().backend("pinduoduo", "promotion"), credential(), transport=transport) as session:
            result = await session.json("POST", "https://yingxiao.pinduoduo.com/example", payload={})
        self.assertTrue(result["data"])

    async def test_merchant_identity_probe_cannot_rotate_child_cookies(self):
        from commerce_api.platforms.pinduoduo.backends.promotion.client import Client
        def respond(request):
            if request.url.host == "mms.pinduoduo.com":
                return httpx.Response(200, json={"success": True, "errorCode": 0, "result": {
                    "mall": {"mall_name": "Example Shop", "mall_id": "fictional-mall"}}},
                    headers={"set-cookie": "_nano_fp=fictional-rotated; Domain=.pinduoduo.com; Path=/; Secure"})
            self.assertIn("_nano_fp=fictional-original", request.headers.get("cookie", ""))
            self.assertNotIn("fictional-rotated", request.headers.get("cookie", ""))
            return httpx.Response(200, json={"errorCode": 1000, "success": True, "result": True})
        profile = Profile("fictional-profile", "Example", "pinduoduo", "Example Company", "Example Shop")
        client = Client(Registry().backend("pinduoduo", "promotion"), credential(), profile,
            transport=httpx.MockTransport(respond))
        try:
            identity = await client.identity()
            self.assertEqual(identity["shop_id"], "fictional-mall")
            self.assertEqual(client.http.client.cookies.get("_nano_fp"), "fictional-original")
        finally:
            await client.close()

    def test_cookie_domain_and_path_scope_are_preserved(self):
        cookies = [{"name": "scoped", "value": "fictional", "domain": "mms.pinduoduo.com", "path": "/restricted", "secure": True}]
        jar = cookie_jar(cookies, ("mms.pinduoduo.com",))
        client = httpx.Client(cookies=jar, trust_env=False)
        try:
            self.assertIn("scoped=", client.build_request("GET", "https://mms.pinduoduo.com/restricted/a").headers.get("cookie", ""))
            self.assertNotIn("scoped=", client.build_request("GET", "https://yingxiao.pinduoduo.com/restricted/a").headers.get("cookie", ""))
            self.assertNotIn("scoped=", client.build_request("GET", "https://mms.pinduoduo.com/other").headers.get("cookie", ""))
        finally:
            client.close()

    async def test_cross_host_download_drops_portal_auth_headers(self):
        paths = owned_temporary(self)
        def respond(request):
            if request.url.host == "source.example.test":
                return httpx.Response(302, headers={"location": "https://cdn.example.test/file"})
            self.assertNotIn("x-csrf-token", request.headers)
            self.assertNotIn("x-fin-sherlock-passid", request.headers)
            self.assertEqual(request.headers.get("referer"), "https://source.example.test/")
            return httpx.Response(200, content=b"date,total\n2026-10-28,1\n",
                headers={"content-type": "text/csv", "content-disposition": 'attachment; filename="bill.csv"'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            file = await download("https://source.example.test/file", paths.root, "bill.xlsx", client=client,
                headers={"X-CSRF-Token": "fictional", "X-Fin-Sherlock-Passid": "fictional",
                    "Referer": "https://source.example.test/private?token=fictional"},
                allowed_hosts=("source.example.test", "cdn.example.test"))
        self.assertTrue(file["path"].endswith(".csv"))

    async def test_json_error_is_never_saved_as_a_report(self):
        paths = owned_temporary(self)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": 1}))) as client:
            with self.assertRaises(ContractError):
                await download("https://source.example.test/file", paths.root, "report.csv", client=client,
                    allowed_hosts=("source.example.test",))
        self.assertFalse(list(paths.root.glob("*.csv")))
        self.assertFalse(list(paths.root.glob("*.part")))
