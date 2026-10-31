import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode

import httpx

from commerce_api.core.contracts import Profile
from commerce_api.core.errors import ContextRequired
from commerce_api.core.registry import Registry
from commerce_api.platforms.tmall.client import TmallClient
from commerce_api.runtime.contexts import context_key
from .support import owned_temporary


API = "mtop.taobao.jdy.resource.shop.info.get"
URL = f"https://h5api.m.taobao.com/h5/{API}/1.0/"


def credential():
    return {"platform": "tmall", "backend": "qianniu", "user_agent": "Fictional Test Agent",
        "cookies": [{"name": "_m_h5_tk", "value": token + "_9999999999999", "domain": domain,
            "path": "/", "secure": True, "expires": -1}
            for token, domain in (("fictional-parent", ".taobao.com"), ("fictional-mobile", ".m.taobao.com"))],
        "contexts": {}}


class MtopTests(unittest.IsolatedAsyncioTestCase):
    def client(self, value, transport=None):
        profile = Profile("fictional-profile", "Example", "tmall", "Example Company", "Example Shop")
        client = TmallClient(Registry().backend("tmall", "qianniu"), value, profile, transport=transport)
        self.addAsyncCleanup(client.close)
        return client

    async def test_captured_signature_selects_matching_cookie_and_signs_fresh_payload(self):
        value = credential()
        captured = {"appKey": "fictional-key", "t": "123", "data": "{}"}
        captured["sign"] = hashlib.md5(f"fictional-mobile&123&fictional-key&{{}}".encode()).hexdigest()
        value["contexts"][context_key(URL)] = {"url": URL + "?" + urlencode(captured)}
        def respond(request):
            params = dict(request.url.params)
            self.assertNotEqual(params["t"], "123")
            self.assertEqual(json.loads(params["data"]), {"example": "new-payload"})
            expected = hashlib.md5(f"fictional-mobile&{params['t']}&fictional-key&{params['data']}".encode()).hexdigest()
            self.assertEqual(params["sign"], expected)
            return httpx.Response(200, json={"ret": ["SUCCESS::OK"], "data": {}})
        client = self.client(value, httpx.MockTransport(respond))
        await client.mtop(API, {"example": "new-payload"})
        self.assertEqual(value["mtop_signer_domains"][context_key(URL)], [".m.taobao.com", "/"])

    async def test_ambiguous_cookie_without_signature_evidence_requires_context(self):
        client = self.client(credential())
        with self.assertRaises(ContextRequired):
            client.signer_cookie(URL)

    async def test_cookie_for_unrelated_path_cannot_sign_request(self):
        value = credential()
        value["cookies"][0]["path"] = "/unrelated"
        client = self.client(value)
        self.assertEqual(client.signer_cookie(URL), "fictional-mobile")

    async def test_read_token_refresh_rebinds_cookie_scope_and_retries_once(self):
        value = credential()
        value["mtop_signer_domains"] = {context_key(URL): [".taobao.com", "/"]}
        calls = []
        def respond(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(200, json={"ret": ["FAIL_SYS_TOKEN_EXOIRED::TOKEN_EXPIRED"]},
                    headers={"set-cookie": "_m_h5_tk=fictional-refreshed_9999999999999; Domain=.m.taobao.com; Path=/; Secure"})
            params = dict(request.url.params)
            expected = hashlib.md5(f"fictional-refreshed&{params['t']}&{params['appKey']}&{params['data']}".encode()).hexdigest()
            self.assertEqual(params["sign"], expected)
            return httpx.Response(200, json={"ret": ["SUCCESS::OK"], "data": {}})
        client = self.client(value, httpx.MockTransport(respond))
        await client.mtop(API, {})
        self.assertEqual(len(calls), 2)
        self.assertEqual(value["mtop_signer_domains"][context_key(URL)], [".m.taobao.com", "/"])

    def test_wrong_order_report_schema_cannot_be_accepted(self):
        from openpyxl import Workbook
        from commerce_api.core.errors import ContractError
        from commerce_api.platforms.tmall.services.reports.orders import REQUIRED_FIELDS, validate_fields
        paths = owned_temporary(self)
        file = paths.root / "fictional-report.xlsx"
        book = Workbook()
        book.active.append(list(REQUIRED_FIELDS))
        book.save(file)
        book.close()
        validate_fields(file)
        book = Workbook()
        book.active.append(list(REQUIRED_FIELDS[:-1]) + ["不相关的报表字段"])
        book.save(file)
        book.close()
        with self.assertRaises(ContractError):
            validate_fields(file)

    async def test_wanxiang_failed_info_is_not_a_successful_zero_report(self):
        from commerce_api.core.errors import ContractError
        from commerce_api.platforms.tmall.backends.wanxiangtai.client import Client
        value = credential()
        value["backend"] = "wanxiangtai"
        profile = Profile("fictional-profile", "Example", "tmall", "Example Company", "Example Shop")
        client = Client(Registry().backend("tmall", "wanxiangtai"), value, profile)
        self.addAsyncCleanup(client.close)
        with self.assertRaises(ContractError):
            client.validate({"info": {"ok": False, "errorCode": "fictional_failure"}, "data": {"total": 0}})
        self.assertEqual(client.validate({"info": {"ok": True}, "data": {"total": 0}})["data"]["total"], 0)

    async def test_parent_shop_check_cannot_erase_alipay_account_pin(self):
        from commerce_api.core.errors import IdentityMismatch
        from commerce_api.platforms.tmall.backends.alipay.client import Client
        value = credential()
        value["cookies"] = value["cookies"][:1]
        value["backend"] = "alipay"
        old_pin = hashlib.sha256(b"fictional-original-account").hexdigest()
        value["identity"] = {"shop_id": "fictional-shop", "fund_account_fingerprint": old_pin}
        url = "https://mbillexprod.alipay.com/enterprise/mbillDownloadStatus.json"
        value["contexts"][context_key(url)] = {"url": url + "?ctoken=fictional", "post_data": urlencode({
            "billUserId": "fictional-different-account", "startDate": "2026-10-28", "endDate": "2026-10-28"})}
        def respond(request):
            return httpx.Response(200, json={"ret": ["SUCCESS::OK"], "data": {"result": {
                "shopName": "Example Shop", "shopId": "fictional-shop"}}})
        profile = Profile("fictional-profile", "Example", "tmall", "Example Company", "Example Shop")
        client = Client(Registry().backend("tmall", "alipay"), value, profile, transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(client.close)
        for _ in range(2):
            with self.assertRaises(IdentityMismatch):
                await client.identity()
            self.assertEqual(value["identity"]["fund_account_fingerprint"], old_pin)

    async def test_alipay_auth_derives_http_query_from_calendar_account_context(self):
        from commerce_api.platforms.tmall.backends.alipay.client import Client
        value = credential()
        value["cookies"] = value["cookies"][:1]
        value["backend"] = "alipay"
        url = "https://mbillexprod.alipay.com/enterprise/mbillDownloadStatus.json"
        value["contexts"][context_key(url)] = {"url": url + "?ctoken=fictional", "post_data": urlencode({
            "billUserId": "fictional-account", "startDate": "2026-10-28", "endDate": "2026-10-28"})}
        def respond(request):
            if request.url.host == "h5api.m.taobao.com":
                return httpx.Response(200, json={"ret": ["SUCCESS::OK"], "data": {"result": {
                    "shopName": "Example Shop", "shopId": "fictional-shop"}}})
            self.assertEqual(request.url.path, "/enterprise/fundDailyStat.json")
            form = parse_qs(request.content.decode())
            self.assertEqual(form["billUserId"], ["fictional-account"])
            self.assertEqual(form["namespace"], ["fundBillModel"])
            self.assertEqual(request.url.params["ctoken"], "fictional")
            return httpx.Response(200, json={"status": "succeed", "success": "true",
                "fundBillSmryForm": {"billUserId": "fictional-account"}, "result": {"dateDtls": []}})
        profile = Profile("fictional-profile", "Example", "tmall", "Example Company", "Example Shop")
        client = Client(Registry().backend("tmall", "alipay"), value, profile, transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(client.close)
        identity = await client.identity()
        self.assertEqual(identity["fund_account_fingerprint"], hashlib.sha256(b"fictional-account").hexdigest())

    async def test_large_order_archive_does_not_block_or_rescan_every_export(self):
        from commerce_api.core.contracts import Period
        from commerce_api.core.errors import ContractError
        from commerce_api.platforms.tmall.services.reports.orders import download
        async def mtop(api, data):
            if api == "mtop.com.taobao.order.sold.export":
                return {"data": {"newExportPlatform": True}}
            return {"data": {"pageNo": data["page"], "pageTotal": "112", "detailList": [{
                "exportId": f"fictional-{data['page']}-{i}", "exportType": "1",
                "startTimeStr": "2026-09-01 00:00:00", "endTimeStr": "2026-09-01 23:59:59"}
                for i in range(10)]}}
        client = SimpleNamespace(template=lambda url: {}, json=AsyncMock(return_value={"page": {"totalNumber": 1}}),
            mtop=AsyncMock(side_effect=mtop))
        submit = AsyncMock(side_effect=ContractError("fictional submission boundary"))
        ctx = SimpleNamespace(client=client, submit=submit,
            run=SimpleNamespace(state={"operations": {}}, reference=lambda name: None))
        with self.assertRaises(ContractError):
            await download(ctx, SimpleNamespace(period=Period.parse(day="2026-10-28")))
        self.assertEqual(sum(call.args[0] == "mtop.taobao.trade.order.exportlist" for call in client.mtop.await_args_list), 5)
        submit.assert_awaited_once()

    def test_item_sales_download_uses_the_item_export_path(self):
        from commerce_api.platforms.tmall.backends.qianniu.api.reports.orders import export_download_url
        query = parse_qs(export_download_url({"exportType": "2", "exportId": "fictional-export",
            "itemEncrypterStr": "fictional-item", "orderEncrypterStr": "fictional-unrelated"}).split("?", 1)[1])
        self.assertEqual(query["f_p"], ["fictional-item"])
        self.assertEqual(query["isQnNew"], ["true"])


if __name__ == "__main__":
    unittest.main()
