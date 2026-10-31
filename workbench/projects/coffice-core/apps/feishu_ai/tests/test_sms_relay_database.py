"""Real PostgreSQL, mocked Feishu delivery, rolled-back private fixtures only."""
from __future__ import annotations

import os
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg2
from psycopg2.extras import RealDictCursor

from apps.ai_analysis.crypto import SecretCipher
from apps.feishu_ai.service import FeishuService
from apps.feishu_ai.sms import SmsMessage
from apps.fund_split_adjust.server import load_project_env


@unittest.skipUnless(os.getenv("RUN_SMS_RELAY_DB_TESTS") == "1", "live database tests opt-in")
class SmsRelayDatabaseTests(unittest.TestCase):
    def setUp(self):
        load_project_env()
        self.connection = psycopg2.connect(host=os.getenv("PGHOST", "192.168.77.111"),
            port=os.getenv("PGPORT", "5432"), dbname=os.getenv("PGDATABASE", "mock_coffice"),
            user=os.getenv("PGUSER", "postgres"), password=os.getenv("PGPASSWORD"))
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)

        @contextmanager
        def transaction():
            with self.connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor

        self.database = SimpleNamespace(transaction=transaction)
        self.service = FeishuService(self.database, SecretCipher(key=os.urandom(32)))
        self.addCleanup(self.service.close)
        self.service._send_to_chat = Mock()
        self.service._send_post_to_chat = Mock(return_value="om_fixture_notice")
        self.service._app = Mock(return_value={"is_enabled": True})
        self.sms = self.service.sms
        prefix = "sms_test_" + uuid.uuid4().hex
        with transaction() as cursor:
            cursor.execute("SELECT EXTRACT(EPOCH FROM NOW())*1000 AS now_ms")
            self.clock_ms = int(cursor.fetchone()["now_ms"])
            self.sms.message_now_ms = Mock(return_value=self.clock_ms + 1000)
            cursor.execute("""INSERT INTO ai.feishu_app(config_code,config_name,app_id,app_secret_ciphertext,
                app_secret_nonce,is_enabled) VALUES (%s,'SMS regression fixture','cli_fixture','placeholder','placeholder',TRUE)
                RETURNING feishu_app_id""", (prefix,))
            self.app_id = cursor.fetchone()["feishu_app_id"]
            cursor.execute("""INSERT INTO ai.verification_relay_config(config_code,config_name,feishu_app_id,chat_id,is_enabled)
                VALUES (%s,'SMS regression fixture',%s,%s,TRUE) RETURNING *""", (prefix, self.app_id, "oc_" + prefix))
            self.relay = dict(cursor.fetchone())
            cursor.execute("""INSERT INTO ai.sms_forwarder_config(config_code,config_name,verification_relay_config_id,
                webhook_ciphertext,webhook_nonce,is_enabled,trusted_senders) VALUES (%s,'SMS regression fixture',%s,
                'placeholder','placeholder',TRUE,'[{"id_type":"app_id","id":"cli_fixture_sender"}]')""",
                (prefix, self.relay["verification_relay_config_id"]))

    def create(self, kind="archive_password", force_human=False):
        return self.sms.create({"force_human": force_human}, self.relay, kind, "抖音", "测试公司", "测试店铺",
            "订单报表 ZIP 解压" if kind == "archive_password" else "订单报表下载验证码",
            "https://fxg.jinritemai.com/ffa/morder/order/export")["challenge_id"]

    def message(self, text, *, user=False, message_id=None):
        return SmsMessage(message_id or "om_" + uuid.uuid4().hex, self.relay["chat_id"], "user" if user else "app",
            (("open_id", "ou_fixture"),) if user else (("app_id", "cli_fixture_sender"),),
            self.clock_ms + 500, text)

    def test_immediate_password_is_stored_and_acknowledged_once_for_duplicate_intake(self):
        challenge = self.create()
        message = self.message("【抖音商城】订单导出文件已加密，解压密码为testPw，文件使用后请尽快删除")
        self.assertTrue(self.sms.ingest_bot(self.app_id, message))
        self.assertFalse(self.sms.ingest_bot(self.app_id, message))
        self.assertFalse(self.sms.notify_answer(challenge))
        self.assertEqual("testPw", self.service.get_verification_challenge(challenge)["answer"])
        self.service._send_to_chat.assert_called_once_with({"is_enabled": True}, self.relay["chat_id"], "解压密码已收到，自动化任务将继续。")

    def test_auto_otp_receipt_uses_requested_wording(self):
        challenge = self.create("verification_code")
        self.assertTrue(self.sms.ingest_bot(self.app_id, self.message("【抖店】验证码6136，5分钟内有效。")))
        self.assertEqual("auto", self.service.get_verification_challenge(challenge)["answer_source"])
        self.assertEqual("验证码已收到，自动化任务将继续。", self.service._send_to_chat.call_args.args[-1])

    def test_manual_history_answer_also_acknowledges_and_resumes(self):
        challenge = self.create(force_human=True)
        self.assertIsNotNone(self.service._answer_human_message({"feishu_app_id": self.app_id}, self.message("testPw", user=True)))
        self.assertEqual("human", self.service.get_verification_challenge(challenge)["answer_source"])
        self.service._send_to_chat.assert_called_once()

    def test_failed_receipt_send_can_retry_without_losing_the_answer(self):
        challenge = self.create()
        self.service._send_to_chat.side_effect = RuntimeError("fixture send failure")
        self.assertTrue(self.sms.ingest_bot(self.app_id, self.message("【抖音商城】订单导出文件已加密，解压密码为testPw。")))
        self.assertEqual("answered", self.service.get_verification_challenge(challenge)["status"])
        self.service._send_to_chat.side_effect = None
        self.assertTrue(self.sms.notify_answer(challenge))
        self.assertFalse(self.sms.notify_answer(challenge))
        self.assertEqual(2, self.service._send_to_chat.call_count)

    def test_explicit_resume_resends_original_manual_template_and_preserves_deadline(self):
        challenge = self.create(force_human=True)
        expires = self.service.get_verification_challenge(challenge)["expires_at"]
        self.sms.resume(challenge)
        self.assertEqual(2, self.service._send_post_to_chat.call_count)
        text = self.service._send_post_to_chat.call_args.args[-1]["zh_cn"]["content"][0][0]["text"]
        self.assertIn("接收已启动", text)
        self.assertIn("请负责人回复平台发送的原始密码", text)
        self.assertIn("https://fxg.jinritemai.com/ffa/morder/order/export", text)
        self.assertEqual(expires, self.service.get_verification_challenge(challenge)["expires_at"])

    def test_resume_does_not_invalidate_an_accepted_password(self):
        challenge = self.create()
        self.sms.ingest_bot(self.app_id, self.message("【抖音商城】订单导出文件已加密，解压密码为testPw。"))
        self.assertEqual("answered", self.sms.resume(challenge)["status"])
        self.assertEqual("testPw", self.service.get_verification_challenge(challenge)["answer"])
        self.service._send_post_to_chat.assert_not_called()

    def test_rejected_code_can_receive_a_new_answer_and_new_receipt(self):
        challenge = self.create()
        self.sms.ingest_bot(self.app_id, self.message("【抖音商城】订单导出文件已加密，解压密码为testPw。"))
        self.sms.reject(challenge)
        self.service._answer_human_message({"feishu_app_id": self.app_id}, self.message("newTestPw", user=True))
        self.assertEqual(2, self.service._send_to_chat.call_count)
        self.assertEqual("newTestPw", self.service.get_verification_challenge(challenge)["answer"])

    def test_cancelled_prearm_releases_stream_for_otp(self):
        self.sms.cancel(self.create())
        self.assertTrue(self.create("verification_code"))

    def test_disabled_sms_prearm_waits_to_request_human_until_zip_needs_password(self):
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.sms_forwarder_config SET is_enabled=FALSE WHERE verification_relay_config_id=%s", (self.relay["verification_relay_config_id"],))
        result = self.sms.create({"defer_human_notice": True}, self.relay, "archive_password", "抖音", "测试公司", "测试店铺", "订单报表 ZIP 解压", "")
        self.assertFalse(result["automatic_enabled"])
        self.service._send_post_to_chat.assert_not_called()
        self.sms.resume(result["challenge_id"])
        self.service._send_post_to_chat.assert_called_once()

    def test_pre_request_sms_is_still_rejected_after_timing_fix(self):
        self.create()
        message = self.message("【抖音商城】订单导出文件已加密，解压密码为testPw。")
        message = SmsMessage(message.message_id, message.chat_id, message.sender_type, message.sender_ids,
            self.clock_ms - 1000, message.text)
        self.assertFalse(self.sms.ingest_bot(self.app_id, message))
        self.service._send_to_chat.assert_not_called()

    def test_migration_column_has_comment(self):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT col_description('ai.verification_challenge'::regclass,attnum) AS comment
                FROM pg_attribute WHERE attrelid='ai.verification_challenge'::regclass AND attname='answer_notice_sent_at'""")
            self.assertTrue(cursor.fetchone()["comment"])
