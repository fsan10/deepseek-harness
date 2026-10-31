from __future__ import annotations

import ast
import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from automation.metric_http import ENDPOINTS, MetricHttpSession
from automation.metric_collect import check_identity, fetch_metrics
from automation.metric_parsers import (DataNotReady, business_date, number, parse_douyin_reception, parse_douyin_score,
    parse_jd_reception, parse_kuaishou_reception, parse_pdd_reception, parse_pdd_score, parse_tmall_reception, parse_tmall_score, parse_xhs_reception)
from automation.metric_profiles import discover, sync_profiles
from automation.metric_worker import enqueue, execute_run, import_records, now, period, schedule_due
from automation.review_errors import AuthRequired, ContractError, HumanRequired, ReviewError
from automation.collection_alerts import public_config, save_config, queue_alert, flush_alerts, send_alert

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-09-15"


def profile(platform="douyin", identifier="p1"):
    return {"profile_id": identifier, "profile_name": "测试账号-" + identifier, "platform": platform, "shop_name": "测试店", "expected_shop_name": "测试店", "company": "测试公司", "excluded": 0, "exclusion_reason": ""}


class ParserTests(unittest.TestCase):
    def test_strict_dates(self):
        self.assertEqual(business_date(20260915), DAY)
        for value in (None, "2026-02-30", "2026/09/15", "", True):
            with self.assertRaises(ContractError): business_date(value)

    def test_missing_is_not_zero(self):
        self.assertEqual(number("0", integer=True), 0)
        for value in (None, "--", "NaN", True, -1, "", "-0.1"):
            with self.assertRaises(ContractError): number(value)
        with self.assertRaises(ContractError): number(1.5, integer=True)

    def test_reception_all_six_platforms_zero_and_source(self):
        samples = [
            ("douyin", parse_douyin_reception, {"data": {"list": [{"date": "20260915", "shop_serv_conv_cnt": {"value": 0}}]}}),
            ("jd", parse_jd_reception, {"trend": [{"sdate": DAY, "receiveNum": 0}]}),
            ("kuaishou", parse_kuaishou_reception, {"data": [{"category": "人工会话量", "sourceDate": "20260915", "value": {"sourceValue": 0}}]}),
            ("pinduoduo", parse_pdd_reception, {"result": [{"statDate": DAY, "consultUserCnt": 0}]}),
            ("xiaohongshu", parse_xhs_reception, {"data": [{"blockKey": "sellerCSOverall", "statisticsDate": "20260915", "data": [{"dtm": {"value": 20260915}, "caseCnt": {"value": 0}}]}]}),
            ("tmall", parse_tmall_reception, {"data": {"data": [{"key": "cstUv1d", "name": "咨询人数", "delay": False, "value": 0}]}}),
        ]
        for platform, parse, body in samples:
            with self.subTest(platform=platform):
                rows = parse(profile(platform), body, DAY)
                self.assertEqual(rows[0]["value"], 0)
                self.assertEqual(rows[0]["metricName"], "接待量")
                self.assertEqual(rows[0]["reportDate"], DAY)
                self.assertTrue(rows[0]["note"].startswith("来源口径："))

    def test_wrong_date_and_duplicate_fail(self):
        for rows in ([], [{"sdate": "2026-09-14", "receiveNum": 20}]):
            with self.assertRaises(DataNotReady): parse_jd_reception(profile("jd"), {"trend": rows}, DAY)
        with self.assertRaises(ContractError):
            parse_jd_reception(profile("jd"), {"trend": [{"sdate": DAY, "receiveNum": 1}] * 2}, DAY)

    def test_xhs_null_is_not_zero(self):
        body = {"data": [{"blockKey": "sellerCSOverall", "statisticsDate": "20260915", "data": [{"dtm": {"value": 20260915}, "caseCnt": {"value": None}}]}]}
        with self.assertRaises(DataNotReady): parse_xhs_reception(profile("xiaohongshu"), body, DAY)

    def test_tmall_delay_is_not_zero(self):
        with self.assertRaises(DataNotReady):
            parse_tmall_reception(profile("tmall"), {"data": {"data": [{"key": "cstUv1d", "name": "咨询人数", "delay": True, "value": 0}]}}, DAY)

    def test_douyin_scores_preserve_dynamic_name_and_units(self):
        overview = {"data": {"has_data": True, "done_info": {"done_date": "20260915"}, "formal_score_info": {k: {"score": 90} for k in ("experience_score", "goods_score", "logistics_score", "service_score")}}}
        detail = {"data": {"has_data": True, "shop_name": "测试店", "done_info": {"done_date": "20260915"}, "shop_order_latest_30_cnt": 10,
            "formal_score_metric_info": {"shop_sub_score": [{"sub_score_node": 1, "sub_score_name": "商品体验"}],
            "metrics": [{"node_id": 123, "title": "新增百分比指标", "value": {"value_type": 2, "value_figure": .12}}]}}}
        rows = parse_douyin_score(profile(), overview, detail)
        self.assertEqual(rows[-1]["value"], "12%")
        self.assertEqual(rows[-1]["metricCategory"], "商品体验")
        detail["data"]["done_info"]["done_date"] = "20260914"
        with self.assertRaises(ContractError): parse_douyin_score(profile(), overview, detail)

    def test_pdd_rank_keeps_interval(self):
        values = {"readyDate": DAY, "cstmrServScore": 4, "attiLmScore": 4, "jcfwLmScore": 4, "spLmScore": 4, "fhLmScore": 4, "wlLmScore": 4}
        for rank, expected in ((.317, "30%-40%"), (.3, "20%-30%"), (.01, "0%-10%"), (.99, "90%-100%")):
            rows = parse_pdd_score(profile("pinduoduo"), {"result": {**values, "cstmrServRank": rank}})
            self.assertEqual(rows[-1]["value"], expected)

    def test_tmall_scores_and_details(self):
        overview = {"data": {"resSuccess": True, "dataSource": {"validOrderCount": "123", "list": [{"code": key, "score": "4.9"} for key in ("nps", "newGoods", "newLogistics", "newServices")]}}}
        detail = {"data": {"data": {"mainIndexInfoList": [{"code": "newServices", "subIndexInfoList": [{"name": "动态服务率", "value": "0.95", "showValue": "95%"}]}]}}}
        rows = parse_tmall_score(profile("tmall"), DAY, overview, detail)
        self.assertEqual(rows[-1]["value"], "95%")
        self.assertEqual(rows[-1]["metricCategory"], "服务体验")
        overview["data"]["dataSource"]["list"].pop()
        with self.assertRaises(ContractError): parse_tmall_score(profile("tmall"), DAY, overview, detail)

    def test_http_modules_have_no_browser_calls(self):
        for name in ("metric_http.py", "metric_collect.py", "metric_parsers.py", "metric_worker.py"):
            tree = ast.parse((ROOT / "automation" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    source = node.module if isinstance(node, ast.ImportFrom) else " ".join(n.name for n in node.names)
                    self.assertNotIn("playwright", source or "")
                if isinstance(node, ast.Attribute): self.assertNotIn(node.attr, ("evaluate", "goto", "connect_over_cdp", "locator", "inner_text"))


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_kuaishou_confirmed_alias_preserves_profile_and_import_mapping(self):
        p = {**profile("kuaishou"), "profile_name": "KS-快手-MOCK禧饮专卖店",
             "expected_shop_name": "MOCK禧饮咖啡专卖店", "shop_name": "MOCK禧饮专卖店"}
        original = dict(p)
        def handle(request):
            if request.url.path == "/rest/business/analysis/account/info":
                return httpx.Response(200, json={"result": 1, "data": {"userInfo": {"user_name": "MOCK禧饮专卖店", "user_id": "test-shop-id"}}})
            return httpx.Response(200, json={"result": 1, "data": [{"category": "人工会话量", "sourceDate": "20260915", "value": {"sourceValue": 7}}]})
        credentials = {"profile_id": "p1", "user_agent": "test", "cookies": [], "identity": {"shop_id": "test-shop-id"}}
        async with MetricHttpSession(p, credentials, transport=httpx.MockTransport(handle)) as client:
            result = await fetch_metrics(p, "reception", date.fromisoformat(DAY), client=client)
        self.assertEqual(result["identity"]["shop_name"], "MOCK禧饮专卖店")
        self.assertEqual(result["records"][0]["shopName"], "MOCK禧饮专卖店")
        self.assertEqual(result["records"][0]["value"], 7)
        self.assertEqual(p, original)

    async def test_identity_alias_is_exact_platform_scoped_and_keeps_id_guard(self):
        cases = [
            ("kuaishou", "MOCK禧饮咖啡专卖店", "MOCK禧饮咖啡专卖店", "test-shop-id", True),
            ("kuaishou", "MOCK禧饮专卖店", "MOCK禧饮咖啡专卖店", "test-shop-id", True),
            ("kuaishou", "MOCK禧饮咖啡专卖店", "MOCK禧饮专卖店", "different-id", False),
            ("kuaishou", "MOCK禧饮咖啡专卖店", "MOCK禧饮专卖店分店", "test-shop-id", False),
            ("kuaishou", "MOCK禧饮咖啡专卖店", "mock禧饮专卖店", "test-shop-id", False),
            ("kuaishou", "其他店铺", "MOCK禧饮专卖店", "test-shop-id", False),
            ("kuaishou", "", "MOCK禧饮专卖店", "test-shop-id", False),
            ("douyin", "MOCK禧饮咖啡专卖店", "MOCK禧饮专卖店", "test-shop-id", False),
        ]
        for platform, expected, actual, identifier, accepted in cases:
            with self.subTest(platform=platform, expected=expected, actual=actual, identifier=identifier):
                p = {**profile(platform), "expected_shop_name": expected}
                data = {"userInfo": {"user_name": actual, "user_id": identifier}} if platform == "kuaishou" else {"shop_name": actual, "shop_id": identifier}
                response = {"result": 1, "data": data} if platform == "kuaishou" else {"code": 0, "data": data}
                credentials = {"profile_id": "p1", "user_agent": "test", "cookies": [], "identity": {"shop_id": "test-shop-id"}}
                async with MetricHttpSession(p, credentials, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))) as client:
                    if accepted:
                        self.assertEqual((await check_identity(client))["shop_name"], actual)
                    else:
                        with self.assertRaises(HumanRequired): await check_identity(client)

    async def request(self, response, platform="douyin", path="https://fxg.jinritemai.com/center/qualification/shop/info"):
        async with MetricHttpSession(profile(platform), {"profile_id": "p1", "user_agent": "test", "cookies": []}, transport=httpx.MockTransport(lambda _: response)) as client:
            return await client.request(path)

    async def test_auth_risk_and_contract(self):
        for status, error in ((401, AuthRequired), (403, HumanRequired), (429, HumanRequired)):
            with self.assertRaises(error): await self.request(httpx.Response(status))
        with self.assertRaises(ContractError): await self.request(httpx.Response(200, text="not JSON"))
        with self.assertRaises(AuthRequired): await self.request(httpx.Response(200, json={"code": 4, "msg": "请先登录"}))
        with self.assertRaises(ReviewError): await self.request(httpx.Response(200, json={"success": True}))

    async def test_pdd_expired_session_is_auth_required(self):
        # 拼多多实际未登录响应使用 snake_case，且仍返回 HTTP 200。
        for body in (
            {"success": False, "error_code": 43001, "error_msg": "会话已过期"},
            {"success": False, "errorCode": "43001", "errorMsg": ""},
        ):
            with self.subTest(body=body), self.assertRaises(AuthRequired):
                await self.request(httpx.Response(200, json=body), platform="pinduoduo",
                                   path="https://mms.pinduoduo.com/janus/api/userinfo")

    async def test_pdd_other_failures_are_not_session_expiration(self):
        for body, error in (
            ({"success": False, "error_code": 50001, "error_msg": "服务异常"}, ReviewError),
            ({"success": False, "error_code": 50002, "error_msg": "无权限"}, HumanRequired),
            ({"success": False, "error_code": 50003, "error_msg": "安全验证"}, HumanRequired),
        ):
            with self.subTest(body=body), self.assertRaises(error) as caught:
                await self.request(httpx.Response(200, json=body), platform="pinduoduo",
                                   path="https://mms.pinduoduo.com/janus/api/userinfo")
            self.assertNotIsInstance(caught.exception, AuthRequired)
        with self.assertRaises(ReviewError) as caught:
            await self.request(httpx.Response(200, json={"code": 43001}))
        self.assertNotIsInstance(caught.exception, AuthRequired)

    async def test_allowlist_rejects_other_platform_or_path(self):
        for url in ("http://fxg.jinritemai.com/center/qualification/shop/info", "https://fxg.jinritemai.com/delete", "https://mms.pinduoduo.com/janus/api/userinfo", "https://fxg.jinritemai.com/center/qualification/shop/info?token=x"):
            with self.assertRaises(ContractError): await self.request(httpx.Response(200, json={"code": 0}), path=url)

    async def test_import_validation_precedes_write(self):
        calls = []
        def handle(req):
            body = json.loads(req.content); calls.append(body)
            return httpx.Response(200, json={"ok": True, "valid" if body["dryRun"] else "processed": 1})
        with patch.dict(os.environ, {"IMPORT_API_KEY": "temporary-test-key", "KEFU_IMPORT_BASE_URL": "http://127.0.0.1:12345"}):
            self.assertEqual(await import_records([{"value": 0}], "test", transport=httpx.MockTransport(handle)), 1)
        self.assertEqual([c["dryRun"] for c in calls], [True, False])

    async def test_invalid_import_never_writes(self):
        calls = []
        def handle(req):
            calls.append(json.loads(req.content)); return httpx.Response(422, json={"ok": False})
        with patch.dict(os.environ, {"IMPORT_API_KEY": "temporary-test-key", "KEFU_IMPORT_BASE_URL": "http://127.0.0.1:12345"}):
            with self.assertRaises(ContractError): await import_records([{"value": None}], "test", transport=httpx.MockTransport(handle))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["dryRun"])

    async def test_import_never_sends_key_external(self):
        with patch.dict(os.environ, {"IMPORT_API_KEY": "temporary-test-key", "KEFU_IMPORT_BASE_URL": "https://example.com"}):
            with self.assertRaises(ContractError): await import_records([{}], "test")

    async def test_feishu_requires_business_success_and_message_id(self):
        for response in ({"code": 12}, {"code": 0, "data": {}}, {"code": 0, "data": None}, {"code": 0, "data": {"message_id": "test-message"}}):
            def handle(req):
                return httpx.Response(200, json={"code": 0, "tenant_access_token": "test"} if "/auth/" in str(req.url) else response)
            config = {"app_id": "test-app", "app_secret": "test-secret", "chat_id": "oc_test"}
            if isinstance(response.get("data"), dict) and response["data"].get("message_id"):
                self.assertEqual(await send_alert(config, "test", transport=httpx.MockTransport(handle)), "test-message")
            else:
                with self.assertRaises(ReviewError): await send_alert(config, "test", transport=httpx.MockTransport(handle))


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"COLLECTION_ALERT_CONFIG_PATH": str(Path(self.temporary.name) / "alerts.enc")})
        self.env.start()
        self.db = sqlite3.connect(":memory:"); self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript((ROOT / "db" / "metrics-collection.sql").read_text(encoding="utf-8"))
        sync_profiles(self.db, [profile()], [{"platform": "抖音", "name": "测试店", "score": True, "reception": True}])

    def tearDown(self):
        self.db.close(); self.env.stop(); self.temporary.cleanup()

    async def test_pdd_poll_refreshes_expired_session_and_retries_once(self):
        from automation.metric_auth import poll_auth_status, record_auth
        from automation.metric_collect import client_for_profile
        p = profile("pinduoduo", "pdd")
        sync_profiles(self.db, [p], [{"platform": "拼多多", "name": "测试店", "score": True, "reception": True}])
        record_auth(self.db, p, "error", "拼多多店铺身份业务响应失败，请核对平台状态", "API_ERROR")
        with self.db:
            self.db.execute("UPDATE metric_auth_status SET checked_at='2000-01-01' WHERE profile_id='pdd'")
        credentials = {"profile_id": "pdd", "platform": "pinduoduo", "user_agent": "test", "cookies": [], "session_id": "expired"}
        store = type("Store", (), {"load": lambda _, key: dict(credentials), "refresh": lambda *_: True})()
        generations = []
        def make_client(current, **kwargs):
            generations.append(credentials["session_id"])
            body = ({"success": False, "error_code": 43001, "error_msg": "会话已过期"}
                    if credentials["session_id"] == "expired" else
                    {"success": True, "errorCode": 1000000, "result": {"mall": {"mall_name": "测试店", "mall_id": "stable-id"}}})
            return client_for_profile(current, store=store, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
        async def logged_in(*args, **kwargs): credentials["session_id"] = "fresh"
        with patch("automation.metric_auth.client_for_profile", side_effect=make_client), patch("automation.metric_auth.login_profile", side_effect=logged_in) as login, patch("automation.metric_auth.queue_alert") as alert:
            await poll_auth_status(self.db)
        login.assert_awaited_once()
        self.assertTrue(login.await_args.kwargs["automatic"])
        self.assertEqual(generations, ["expired", "fresh"])
        state = self.db.execute("SELECT state,actual_shop_id FROM metric_auth_status WHERE profile_id='pdd'").fetchone()
        self.assertEqual(tuple(state), ("valid", "stable-id"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM collection_events WHERE profile_id='pdd' AND status='open'").fetchone()[0], 0)
        alert.assert_not_called()

    async def test_pdd_expiration_after_recovery_does_not_loop(self):
        from automation.metric_auth import check_profile
        from automation.review_errors import LoginFailed
        p = profile("pinduoduo")
        sync_profiles(self.db, [p], [{"platform": "拼多多", "name": "测试店", "score": True, "reception": True}])
        def make_client(*args, **kwargs):
            return MetricHttpSession(p, {"profile_id": "p1", "user_agent": "test", "cookies": []},
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"success": False, "error_code": 43001, "error_msg": "会话已过期"})))
        with patch("automation.metric_auth.client_for_profile", side_effect=make_client) as clients, patch("automation.metric_auth.login_profile", new=AsyncMock()) as login, patch("automation.metric_auth.queue_alert") as alert:
            with self.assertRaises(LoginFailed): await check_profile(self.db, p)
        login.assert_awaited_once()
        self.assertEqual(clients.call_count, 2)
        self.assertEqual(self.db.execute("SELECT error_code FROM metric_auth_status WHERE profile_id='p1'").fetchone()[0], "LOGIN_FAILED")
        alert.assert_called_once()

    async def test_every_platform_recovers_mid_collection_with_polling_off(self):
        from automation.metric_profiles import PLATFORMS
        for platform, spec in PLATFORMS.items():
            with self.subTest(platform=platform):
                current = profile(platform, platform)
                sync_profiles(self.db, [current], [{"platform": spec["name"], "name": "测试店", "score": spec["score"], "reception": True}])
                with self.db: self.db.execute("UPDATE metric_profiles SET auth_check_enabled=0 WHERE profile_id=?", (platform,))
                run = enqueue(self.db, {"kind": "reception", "profileIds": [platform]})
                # 采集 API 返回 401 时走恢复入口，即使后台轮询开关关闭。
                async def fetch(current_profile, kind, day):
                    async with MetricHttpSession(current_profile, {"profile_id": platform, "user_agent": "test", "cookies": []}, transport=httpx.MockTransport(lambda _: httpx.Response(401))) as client:
                        if not login.await_count:
                            url = next(endpoint for endpoint in sorted(ENDPOINTS[platform]) if endpoint[1] != "/mall/api")
                            await client.request("https://" + url[0] + url[1])
                    return {"identity": {"shop_name": "测试店", "shop_id": platform}, "records": [{"value": 1}], "report_date": day.isoformat(), "source_metric": "测试口径"}
                with patch("automation.metric_auth.login_profile", new=AsyncMock()) as login, patch("automation.metric_worker.fetch_metrics", new=fetch), patch("automation.metric_worker.import_records", new=AsyncMock(return_value=1)) as writer, patch("automation.metric_auth.queue_alert") as alert:
                    await execute_run(self.db, self.db.execute("SELECT * FROM metric_runs WHERE id=?", (run["id"],)).fetchone())
                login.assert_awaited_once(); writer.assert_awaited_once(); alert.assert_not_called()
                self.assertTrue(login.await_args.kwargs["automatic"])
                self.assertEqual(self.db.execute("SELECT status FROM metric_runs WHERE id=?", (run["id"],)).fetchone()[0], "success")

    def test_profile_scope_exact_accounts_and_closed(self):
        raws = [{"id": str(i), "name": name, "note": "platform=天猫;shop=测试店"} for i, name in enumerate(("TMALL-天猫-MOCK旗舰店", "TMALL-天猫-MOCK旗舰店-财务账号", "巨量云图", "视频号"))]
        self.assertEqual(len(discover(raws)), 1)
        p = discover([{"id": "closed", "name": "DY-抖音-MOCK吉饮咖啡专卖店", "note": "platform=抖音;shop=MOCK吉饮咖啡专卖店"}])[0]
        self.assertEqual(p["excluded"], 1)

    def test_no_fuzzy_mapping(self):
        sync_profiles(self.db, [profile()], [{"platform": "抖音", "name": "测试店旗舰店", "score": True, "reception": True}])
        self.assertEqual(self.db.execute("SELECT shop_name FROM metric_profiles").fetchone()[0], "")

    def test_duplicate_shop_mapping_rolls_back(self):
        with self.assertRaises(ContractError):
            sync_profiles(self.db, [profile(identifier="p1"), profile(identifier="p2")], [{"platform": "抖音", "name": "测试店", "score": True, "reception": True}])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM metric_profiles WHERE excluded=0").fetchone()[0], 1)

    def test_enqueue_deduplicates_and_separates_kinds(self):
        result = enqueue(self.db, {"kind": "reception"})
        with self.assertRaises(ContractError): enqueue(self.db, {"kind": "reception"})
        enqueue(self.db, {"kind": "score"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM metric_runs").fetchone()[0], 2)
        self.assertEqual(result["items"], 1)

    def test_score_does_not_fake_historical_snapshots(self):
        with self.assertRaises(ContractError): enqueue(self.db, {"kind": "score", "from": DAY})

    async def test_retry_preserves_successful_dates(self):
        last = datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=1)
        first = last - timedelta(days=1)
        item = enqueue(self.db, {"kind": "reception", "from": first.isoformat(), "to": last.isoformat()})
        results = [{"identity": {"shop_name": "测试店", "shop_id": "1"}, "records": [{"value": 0}], "report_date": first.isoformat(), "source_metric": "测试口径"}, ContractError("接口结构变化")]
        with patch("automation.metric_worker.fetch_metrics", new=AsyncMock(side_effect=results)), patch("automation.metric_worker.import_records", new=AsyncMock(return_value=1)):
            await execute_run(self.db, self.db.execute("SELECT * FROM metric_runs WHERE id=?", (item["id"],)).fetchone())
        self.assertEqual(self.db.execute("SELECT status FROM metric_runs").fetchone()[0], "partial")
        enqueue(self.db, {"action": "retry", "kind": "reception", "runId": item["id"]})
        states = [r[0] for r in self.db.execute("SELECT status FROM metric_run_items ORDER BY requested_date")]
        self.assertEqual(states, ["success", "pending"])
        fetch = AsyncMock(return_value={**results[0], "report_date": last.isoformat()})
        with patch("automation.metric_worker.fetch_metrics", new=fetch), patch("automation.metric_worker.import_records", new=AsyncMock(return_value=1)):
            await execute_run(self.db, self.db.execute("SELECT * FROM metric_runs WHERE id=?", (item["id"],)).fetchone())
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(self.db.execute("SELECT status FROM metric_runs").fetchone()[0], "success")

    async def test_no_import_when_cancelled_during_fetch(self):
        item = enqueue(self.db, {"kind": "reception"})
        async def cancel(*_):
            enqueue(self.db, {"action": "cancel", "kind": "reception", "runId": item["id"]})
            return {"identity": {"shop_name": "测试店", "shop_id": "1"}, "records": [{"value": 1}]}
        writer = AsyncMock()
        with patch("automation.metric_worker.fetch_metrics", new=cancel), patch("automation.metric_worker.import_records", new=writer):
            await execute_run(self.db, self.db.execute("SELECT * FROM metric_runs").fetchone())
        writer.assert_not_awaited()
        self.assertEqual(self.db.execute("SELECT status FROM metric_runs").fetchone()[0], "cancelled")

    async def test_alert_deduplication_and_claim(self):
        with patch("automation.collection_alerts.load_config", return_value={"enabled": True}):
            queue_alert(self.db, "event", "p1", "TEST", "message")
            queue_alert(self.db, "event", "p1", "TEST", "message")
            sender = AsyncMock(return_value="test-message")
            with patch("automation.collection_alerts.send_alert", new=sender):
                await flush_alerts(self.db); await flush_alerts(self.db)
            sender.assert_awaited_once()
        self.assertEqual(self.db.execute("SELECT status FROM collection_notifications").fetchone()[0], "sent")

    def test_schedule_gap_is_reported(self):
        current = datetime.now(timezone.utc)
        with self.db:
            self.db.execute("UPDATE metric_collection_settings SET enabled=1,next_run_at=? WHERE kind='reception'", ((current - timedelta(minutes=1)).isoformat(),))
        schedule_due(self.db, current)
        self.assertEqual(self.db.execute("SELECT trigger_type FROM metric_runs").fetchone()[0], "scheduled")

    def test_schedule_retries_old_checkpoint_before_new_period(self):
        current = datetime.now(timezone.utc)
        item = enqueue(self.db, {"kind": "reception", "trigger_type": "scheduled"})
        with self.db:
            self.db.execute("UPDATE metric_runs SET status='partial'")
            self.db.execute("UPDATE metric_collection_settings SET enabled=1,next_run_at=? WHERE kind='reception'", ((current - timedelta(minutes=1)).isoformat(),))
        schedule_due(self.db, current)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM metric_runs").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT id,status FROM metric_runs").fetchone()[:], (item["id"], "queued"))

    async def test_parent_shutdown_cancels_metric_worker(self):
        from automation import metric_worker
        path = Path(self.temporary.name) / "worker.sqlite"
        entered = asyncio.Event()
        alive = True
        async def blocked_fetch(*_):
            entered.set()
            await asyncio.Event().wait()
        with patch.dict(os.environ, {"KEFU_DB_PATH": str(path)}):
            db = metric_worker.connect()
            sync_profiles(db, [profile()], [{"platform": "抖音", "name": "测试店", "score": True, "reception": True}])
            enqueue(db, {"kind": "reception"}); db.close()
            with patch("automation.review_worker.parent_alive", side_effect=lambda _: alive), patch("automation.metric_worker.fetch_metrics", new=blocked_fetch):
                task = asyncio.create_task(metric_worker.worker(999999))
                await asyncio.wait_for(entered.wait(), 2)
                alive = False
                await asyncio.wait_for(task, 3)
            db = metric_worker.connect()
            self.assertEqual(db.execute("SELECT status FROM metric_runs").fetchone()[0], "failed")
            self.assertEqual(db.execute("SELECT message FROM metric_worker_state").fetchone()[0], "网页服务已停止")
            db.close()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI required")
    def test_alert_secrets_encrypted_and_masked(self):
        body = {"enabled": True, "app_id": "test", "app_secret": "temporary-test-secret", "chat_id": "oc_test"}
        result = save_config(body)
        self.assertTrue(result["app_secret_configured"])
        self.assertNotIn("app_secret", result)
        self.assertNotIn(b"temporary-test-secret", (Path(self.temporary.name) / "alerts.enc").read_bytes())
        self.assertTrue(public_config()["app_secret_configured"])


if __name__ == "__main__": unittest.main()
