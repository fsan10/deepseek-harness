from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlsplit

from ReverseAPI.Formal_Script import tmall_fund_webapi_download as fund
from ReverseAPI.Formal_Script import tmall_webapi_common as common


DATE = "2026-10-11"
TEMPLATE_URL = "https://mbillexprod.alipay.com/enterprise/fundDailyStat.json?ctoken=fictional-csrf&_output_charset=utf-8"
FORM = {"billUserId": "fictional-account", "billType": "signcustomer", "pageNum": "5",
        "querySettleAccount": "false", "startDate": "2026-10-13", "endDate": "2026-10-19"}
READY = {"status": "succeed", "success": "true",
         "result": {"dateDtls": [{"bizDate": DATE, "downloadable": True, "noData": "false"}]}}
SECURITY = {"securityStatus": "succeed", "securityId": "fictional-fresh-ticket", "inWhiteList": "false"}


class AlipayPayloadTests(unittest.TestCase):
    def test_china_day_boundary_and_year_rollover(self):
        self.assertEqual(("Sat, 10 Oct 2026 16:00:00 GMT", "Sun, 11 Oct 2026 15:59:59 GMT"),
                         fund.alipay_day_times(DATE))
        self.assertEqual(("Thu, 31 Dec 2026 16:00:00 GMT", "Fri, 01 Jan 2027 15:59:59 GMT"),
                         fund.alipay_day_times("2027-01-01"))

    def test_query_overrides_only_period_and_page_without_mutation(self):
        before = dict(FORM)
        query = fund.alipay_query_form(FORM, DATE)
        self.assertEqual(before, FORM)
        self.assertEqual({**FORM, "startDate": DATE, "endDate": DATE, "pageNum": "1"}, query)
        with self.assertRaises(common.ApiError):
            fund.alipay_query_form({}, DATE)

    def test_security_request_uses_same_target_csrf_and_gmt_dates(self):
        url, body = fund.alipay_security_request(TEMPLATE_URL, DATE)
        self.assertEqual(fund.ALIPAY_SECURITY_PATH, urlsplit(url).path)
        self.assertEqual(["fictional-csrf"], parse_qs(urlsplit(url).query)["ctoken"])
        self.assertEqual({"securityBizType": fund.ALIPAY_SECURITY_BIZ_TYPE,
                          "beginDate": "Sat, 10 Oct 2026 16:00:00 GMT",
                          "endDate": "Sun, 11 Oct 2026 15:59:59 GMT", "_input_charset": "gbk"}, body)
        for bad in ("https://example.invalid/?ctoken=x", "https://mbillexprod.alipay.com/no-token"):
            with self.assertRaises(common.ApiError):
                fund.alipay_security_request(bad, DATE)

    def test_download_url_has_fresh_ticket_and_all_requested_date_fields(self):
        url = fund.alipay_download_url(TEMPLATE_URL, FORM, DATE, "fictional-new-ticket", timestamp_ms=123)
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(fund.ALIPAY_DAILY_PATH, urlsplit(url).path)
        self.assertEqual(["fictional-new-ticket"], query["securityId"])
        self.assertEqual([DATE], query["bizDate"])
        self.assertEqual(["123"], query["_t"])
        self.assertEqual(["Sat, 10 Oct 2026 16:00:00 GMT"], query["startTime"])
        self.assertEqual(["Sun, 11 Oct 2026 15:59:59 GMT"], query["endTime"])
        self.assertNotIn("ctoken", query)

    def test_security_success_does_not_require_whitelist(self):
        self.assertEqual("fictional-fresh-ticket", fund.alipay_security_id(SECURITY))
        with self.assertRaises(common.NeedsHumanError):
            fund.alipay_security_id({"securityStatus": "verify"})
        with self.assertRaises(common.ApiError):
            fund.alipay_security_id({"securityStatus": "succeed"})

    def test_rows_require_exact_date_and_explicit_ready_status(self):
        self.assertEqual(DATE, fund.alipay_target_row(READY, DATE)["bizDate"])
        self.assertIsNone(fund.alipay_target_row(READY, "2026-10-10"))
        for result in (None, {}, {"dateDtls": None}, {"dateDtls": [None]}):
            with self.subTest(result=result), self.assertRaises(common.ApiError):
                fund.alipay_target_row({"status": "succeed", "success": True, "result": result}, DATE)
        for row in ({"bizDate": DATE, "downloadable": "false"},
                    {"bizDate": DATE, "downloadable": True, "processing": "true"}):
            with self.assertRaises(common.ApiError):
                fund.alipay_target_row({**READY, "result": {"dateDtls": [row]}}, DATE)
        with self.assertRaises(common.ApiError):
            fund.alipay_target_row({**READY, "result": {"dateDtls": READY["result"]["dateDtls"] * 2}}, DATE)


class AlipayFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.page = MagicMock()
        self.context = SimpleNamespace(pages=[self.page])
        self.browser = SimpleNamespace(contexts=[self.context])
        self.natural = SimpleNamespace(url=TEMPLATE_URL, post_data=urlencode(FORM))
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.open = self.stack.enter_context(patch.object(fund, "_open_alipay_bill_page", new=AsyncMock(return_value=self.page)))
        self.load = self.stack.enter_context(patch.object(fund, "_alipay_natural_context", new=AsyncMock(return_value=self.natural)))
        self.post = self.stack.enter_context(patch.object(fund, "_alipay_page_post", new=AsyncMock(side_effect=[READY, SECURITY])))
        self.download = self.stack.enter_context(patch.object(fund, "download_browser_file", new=AsyncMock(return_value=Path("fixture.zip"))))
        self.stack.enter_context(patch.object(fund.zipfile, "is_zipfile", return_value=True))
        self.direct = self.stack.enter_context(patch.object(fund, "session_request", new=AsyncMock()))
        self.stack.enter_context(patch.object(fund, "log"))

    async def run_report(self):
        return await fund.download_alipay(self.browser, DATE, Path("output"))

    async def test_security_context_is_consumed_by_exactly_one_download(self):
        self.assertEqual(Path("fixture.zip"), await self.run_report())
        self.assertEqual(2, self.post.await_count)
        self.download.assert_awaited_once()
        self.direct.assert_not_awaited()
        self.page.locator.assert_not_called()
        query = parse_qs(urlsplit(self.download.await_args.args[1]).query)
        self.assertEqual(["fictional-fresh-ticket"], query["securityId"])
        self.assertEqual([DATE], query["bizDate"])
        self.page.close.assert_not_called()

    async def test_zero_short_circuits_security_and_download(self):
        self.post.side_effect = [{**READY, "result": {"dateDtls": []}}]
        self.assertIsNone(await self.run_report())
        self.assertEqual(1, self.post.await_count)
        self.download.assert_not_awaited()

    async def test_http_403_refreshes_same_target_once(self):
        self.post.side_effect = [common.ApiError("fixture", status=403), READY, SECURITY]
        await self.run_report()
        self.assertEqual(2, self.load.await_count)
        self.assertEqual([self.page, self.page], [call.args[0] for call in self.load.await_args_list])
        self.download.assert_awaited_once()

    async def test_second_403_is_human_gate_and_never_downloads(self):
        self.post.side_effect = common.ApiError("fixture", status=403)
        with self.assertRaises(common.NeedsHumanError):
            await self.run_report()
        self.assertEqual(2, self.load.await_count)
        self.assertEqual(2, self.post.await_count)
        self.download.assert_not_awaited()

    async def test_failed_security_and_download_timeout_do_not_replay(self):
        self.post.side_effect = [READY, {"securityStatus": "verify"}]
        with self.assertRaises(common.NeedsHumanError):
            await self.run_report()
        self.download.assert_not_awaited()
        self.post.side_effect = [READY, SECURITY]
        self.download.side_effect = common.ApiError("fixture timeout")
        with self.assertRaises(common.ApiError):
            await self.run_report()
        self.download.assert_awaited_once()

    async def test_only_newly_created_page_is_closed(self):
        owned = MagicMock()
        owned.close = AsyncMock()
        async def create(*args):
            self.context.pages.append(owned)
            return owned
        self.open.side_effect = create
        await self.run_report()
        owned.close.assert_awaited_once()
        self.page.close.assert_not_called()

    async def test_browser_failure_does_not_echo_ticket_or_retry_download(self):
        self.download.side_effect = Exception("https://example.invalid/?securityId=fictional-private")
        with self.assertRaises(common.ApiError) as error:
            await self.run_report()
        self.assertNotIn("fictional-private", str(error.exception))
        self.download.assert_awaited_once()

    async def test_invalid_zip_is_removed_and_not_reported_success(self):
        with TemporaryDirectory() as temp:
            invalid = Path(temp) / "invalid.zip"
            invalid.write_bytes(b"<html>fixture error</html>")
            self.download.return_value = invalid
            with patch.object(fund.zipfile, "is_zipfile", return_value=False):
                with self.assertRaises(common.ApiError):
                    await self.run_report()
            self.assertFalse(invalid.exists())


class AlipayPageApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_natural_listener_detaches_on_failure(self):
        page = MagicMock(reload=AsyncMock(side_effect=RuntimeError("fixture")))
        collector = MagicMock()
        with patch.object(fund, "NaturalRequestCollector", return_value=collector):
            with self.assertRaises(RuntimeError):
                await fund._alipay_natural_context(page)
        collector.attach.assert_called_once_with(page)
        collector.detach.assert_called_once()

    async def test_page_api_rejects_http_and_non_json_without_body_leak(self):
        page = MagicMock(evaluate=AsyncMock(return_value={"status": 403, "text": "secret fixture"}))
        with self.assertRaises(common.ApiError) as error:
            await fund._alipay_page_post(page, TEMPLATE_URL, {}, label="fixture")
        self.assertEqual(403, error.exception.status)
        self.assertNotIn("secret", str(error.exception))
        page.evaluate.return_value = {"status": 200, "text": "<html>secret fixture</html>"}
        with self.assertRaises(common.ApiError):
            await fund._alipay_page_post(page, TEMPLATE_URL, {}, label="fixture")

    async def test_atomic_download_preserves_existing_file_and_cleans_failed_part(self):
        class Event:
            async def __aenter__(self):
                return SimpleNamespace(value=asyncio_value(download))
            async def __aexit__(self, *args):
                return False
        async def asyncio_value(value):
            return value
        download = MagicMock()
        page = MagicMock(expect_download=MagicMock(return_value=Event()), goto=AsyncMock())
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            existing = directory / "bill.zip"
            existing.write_bytes(b"previous")
            async def save(path):
                Path(path).write_bytes(b"new-file")
            download.save_as = AsyncMock(side_effect=save)
            result = await common.download_browser_file(page, "https://example.invalid/bill", directory, "bill.zip")
            self.assertNotEqual(existing, result)
            self.assertEqual(b"previous", existing.read_bytes())
            self.assertEqual(b"new-file", result.read_bytes())
            async def fail(path):
                Path(path).write_bytes(b"incomplete")
                raise RuntimeError("fixture save failure")
            download.save_as.side_effect = fail
            with self.assertRaises(RuntimeError):
                await common.download_browser_file(page, "https://example.invalid/bill", directory, "bill.zip")
            self.assertEqual([], list(directory.glob("*.part")))


if __name__ == "__main__":
    unittest.main()
