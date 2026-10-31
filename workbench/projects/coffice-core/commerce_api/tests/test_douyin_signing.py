"""Fictional signing fixtures; no browser, credentials or network services."""
import hashlib
import random
import unittest
from urllib.parse import parse_qsl, quote

import httpx

from commerce_api.core.contracts import Profile
from commerce_api.core.errors import ContextRequired, NeedsHuman
from commerce_api.core.registry import Registry
from commerce_api.platforms.douyin.backends.merchant.client import Client
from commerce_api.platforms.douyin.backends.merchant.signing import Signer, derive_material, sm3, strip_signature
from commerce_api.runtime.contexts import context_key


UA = "Fictional Test Browser/1.0"
ORIGIN = "https://fxg.jinritemai.com"
HISTORY = ORIGIN + "/order/torder/exportHistory"
MATERIAL = {"version": 1, "sdk_version": 1, "sdk_minor": 14, "aid": 4272, "page_id": 23756,
    "environment_flags": 0, "sdk_flags": [0, 0, 0], "geometry": "1200|800|1200|800|0|0|0|0|Win32",
    "browser_base": 40, "timing_byte": 2, "tail_delta": 1,
    "user_agent_sha256": hashlib.sha256(UA.encode()).hexdigest()}


def sample(path=HISTORY, query="page=1&size=10&msToken=fictional-session", body=b""):
    signer = Signer(MATERIAL, UA, clock=lambda: 1793318400000, random=random.Random(7).random)
    return path + "?" + query + "&a_bogus=" + quote(signer.sign(query, body), safe="")


def credential():
    context = {"url": sample(), "post_data": None, "captured_at": "2026-10-30T00:00:00+00:00"}
    return {"platform": "douyin", "backend": "merchant", "user_agent": UA,
        "cookies": [], "contexts": {context_key(HISTORY): context}}


class SigningTests(unittest.TestCase):
    def test_sm3_standard_abc_vector(self):
        self.assertEqual(sm3(b"abc").hex(),
            "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0")

    def test_sample_validates_encoded_query_body_and_user_agent(self):
        url = sample(query="name=one%20two&name=second&empty=", body=b'{"value":1}')
        self.assertEqual(derive_material(url, UA, b'{"value":1}'), MATERIAL)
        for changed_url, changed_ua, body in (
            (url.replace("%20", "+"), UA, b'{"value":1}'),
            (url, UA, b'{"value":2}'),
            (url, "Different Fictional Browser", b'{"value":1}'),
            (url.replace("fxg.jinritemai.com", "example.test"), UA, b'{"value":1}'),
        ):
            with self.subTest(url=changed_url.split("?")[0], ua=changed_ua, body=body):
                with self.assertRaises(ContextRequired):
                    derive_material(changed_url, changed_ua, body)

    def test_signature_removal_preserves_encoded_order_and_duplicates(self):
        self.assertEqual(strip_signature("x=a%20b&x=c%2Bd&a_bogus=stale&empty=&z=%2f"),
            "x=a%20b&x=c%2Bd&empty=&z=%2f")

    def test_invalid_or_mismatched_material_is_not_accepted(self):
        with self.assertRaises(ContextRequired):
            derive_material(HISTORY + "?a_bogus=broken", UA)
        with self.assertRaises(ContextRequired):
            Signer(MATERIAL, "Different Fictional Browser")


class SignedHttpTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self, value, handler):
        client = Client(Registry().backend("douyin", "merchant"), value,
            Profile("fictional-profile", "Example", "douyin", "Example Company", "Example Shop"),
            transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        return client

    async def test_changed_query_and_json_body_are_signed_after_serialization(self):
        signatures = []
        bodies = []
        def respond(request):
            # Independently decode and verify the digest of the bytes sent to
            # the transport, rather than verifying an unencoded input dict.
            self.assertEqual(derive_material(str(request.url), UA, request.content)["aid"], 4272)
            signatures.append(dict(parse_qsl(request.url.query.decode()))["a_bogus"])
            bodies.append(request.content)
            self.assertIn(b"value=one+two", request.url.query)
            self.assertNotIn("stale", signatures[-1])
            return httpx.Response(200, json={"code": 0})
        client = self.make_client(credential(), respond)
        for value in (1, 2):
            await client.post(ORIGIN + "/order/torder/export?value=one%20two&a_bogus=stale",
                payload={"value": value, "label": "虚构"})
        self.assertNotEqual(signatures[0], signatures[1])
        self.assertNotEqual(bodies[0], bodies[1])

    async def test_direct_verification_request_is_signed_without_json_wrapper(self):
        seen = []
        def respond(request):
            derive_material(str(request.url), UA, request.content)
            seen.append(dict(parse_qsl(request.url.query.decode()))["a_bogus"])
            return httpx.Response(200, content=b"fictional-binary")
        client = self.make_client(credential(), respond)
        for _ in range(2):
            response = await client.http.request("GET", client.prepare_url(
                ORIGIN + "/order/torder/exportHistory/downloadfile?task_id=fictional"), effect="verification")
            self.assertEqual(response.content, b"fictional-binary")
        self.assertNotEqual(seen[0], seen[1])

    async def test_missing_or_foreign_context_stops_before_network(self):
        value = credential()
        value["contexts"] = {"foreign": {"url": sample().replace("fxg.jinritemai.com", "example.test")}}
        def unexpected(request):
            self.fail("Missing verified context must fail before sending")
        client = self.make_client(value, unexpected)
        with self.assertRaises(ContextRequired):
            await client.get(HISTORY, {"page": 1})

    async def test_unsigned_bill_paths_and_risk_handling_are_preserved(self):
        def respond(request):
            if request.url.path == "/order/torder/exportHistory":
                return httpx.Response(200, json={"code": "10001010A", "msg": "当前环境存在风险，请稍后重试"})
            self.assertNotIn("a_bogus", request.url.query.decode())
            self.assertNotIn("msToken", request.url.query.decode())
            return httpx.Response(200, json={"code": 0})
        client = self.make_client(credential(), respond)
        await client.get(ORIGIN + "/settle/example")
        with self.assertRaises(NeedsHuman):
            await client.get(HISTORY)
