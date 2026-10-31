"""Order verification and authorized file retrieval use the same persisted Run."""
import io
import json
import unittest
import zipfile
from unittest.mock import AsyncMock, patch

import httpx

from commerce_api.core.contracts import Period, ReportRequest
from commerce_api.core.registry import Registry
from commerce_api.platforms.douyin.backends.merchant.client import Client
from commerce_api.platforms.douyin.backends.merchant.api.reports import orders as api
from commerce_api.platforms.douyin.services.reports.orders import download
from commerce_api.runtime.engine import Context
from commerce_api.runtime.runs import Run
from .support import owned_temporary, fictional_profile
from .test_douyin_signing import credential, derive_material, UA


class OrderDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, verified=False, direct=False):
        paths = owned_temporary(self)
        profile = fictional_profile(paths)
        request = ReportRequest("douyin", "order", "merchant", profile.name, Period.parse(day="2026-10-28"))
        run = Run.create(paths, request, profile.id)
        run.confirmed("create_export", task_id="fictional-task", reused=True)
        bundle = io.BytesIO()
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("fictional.csv", "订单创建时间,数量\n2026-10-28 12:00:00,1\n")
        calls = {"send": 0, "otp": 0, "file": 0}
        def response(value):
            return httpx.Response(200, json={"code": 0, "data": value})
        def respond(sent):
            derive_material(str(sent.url), UA, sent.content)
            query = dict(sent.url.params)
            if sent.url.path == "/api/order/searchlist":
                return httpx.Response(200, json={"code": 0, "total": 1})
            if sent.url.path == "/order/torder/exportHistory":
                start, end = request.period.timestamps()
                return httpx.Response(200, json={"code": 0, "total": 1, "data": {"total": 0, "task_list": [
                    {"task_id": "fictional-task", "status": 2, "report_type": "STANDARD",
                        "query_condition": json.dumps({"create_time_start": start, "create_time_end": end})}]}})
            if sent.url.path == "/api/order/sendcode":
                calls["send"] += 1
                return response(None)
            self.assertEqual(sent.url.path, "/order/torder/exportHistory/downloadfile")
            if query.get("file_name"):
                self.assertEqual(query["file_name"], "fictional-file-name")
                self.assertNotIn("verify_code", query)
                calls["file"] += 1
                return httpx.Response(200, content=bundle.getvalue(), headers={"content-type": "application/zip"})
            if query.get("verify_code"):
                self.assertFalse(verified, "Resume must not replay the confirmed OTP")
                self.assertEqual(query["verify_code"], "fictional-answer")
                calls["otp"] += 1
                return response({"verify_type": "", "file_name": "fictional-file-name", "need_popup": True})
            self.assertFalse(verified, "Resume must keep the existing authorized file")
            if direct:
                return response({"verify_type": "", "file_name": "fictional-file-name", "need_popup": True})
            return response({"verify_type": "email", "verify_params": {"verify_account": "SUB"}, "file_name": ""})
        backend = Registry().backend("douyin", "merchant")
        client = Client(backend, credential(), profile, transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(client.close)
        ctx = Context(paths, run, profile, backend, client)
        if verified:
            run.confirmed("authorize_download")
            run.confirmed("download_with_code")
            ctx.private("download_verification", {"code": 0, "data": {
                "verify_type": "", "file_name": "fictional-file-name", "need_popup": True}})
        answers = AsyncMock(return_value="fictional-answer")
        with patch("commerce_api.integrations.legacy.verification.create", new=AsyncMock(
                side_effect=lambda *a, **kw: {"challenge_id": "fictional-" + kw["kind"]})), patch(
                "commerce_api.integrations.legacy.verification.cancel", new=AsyncMock()), patch(
                "commerce_api.integrations.legacy.verification.answer", new=answers):
            result = await download(ctx, request)
        self.assertEqual(result.status, "downloaded")
        self.assertEqual(result.row_count, 1)
        self.assertEqual(calls, {"send": 0 if (direct or verified) else 1,
            "otp": 0 if (direct or verified) else 1, "file": 1})
        self.assertEqual(answers.await_count, 0 if (direct or verified) else 1)
        self.assertEqual([f["role"] for f in result.files], ["source", "report"])
        serialized = paths.file("runs", run.id).read_text(encoding="utf-8")
        self.assertNotIn("fictional-answer", serialized)
        self.assertNotIn("fictional-file-name", serialized)

    async def test_otp_success_is_followed_by_authorized_file_download(self):
        await self.exercise()

    async def test_resume_authorized_file_does_not_resend_or_reverify_otp(self):
        await self.exercise(verified=True)

    async def test_file_name_without_otp_is_downloaded_directly(self):
        await self.exercise(direct=True)
