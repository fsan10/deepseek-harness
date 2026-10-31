import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from apps.feishu_ai.sms import SmsMessage, bot_matches, extract_code, normalize_event, normalize_history, visible_text
from apps.feishu_ai.sms_relay import SmsRelay
from apps.feishu_ai.service import FeishuService


class SmsMatchingTests(unittest.TestCase):
    def test_five_platform_purposes_preserve_case_and_zeroes(self):
        samples = [
            ('jd_archive_password', '【京东】以taskid-123-开头的加密导出文件，密码（区分大小写）：KkTa3q。', 'KkTa3q'),
            ('kuaishou_export_otp', '【快手小店】验证码是2c19，正申请导出订单。', '2c19'),
            ('kuaishou_extract_code', '【快手小店】提取码：b96566，正申请文件提取码。', 'b96566'),
            ('douyin_order_otp', '【抖店】验证码：003762，电话13800138000，有效至2026-10-10。', '003762'),
            ('douyin_archive_password', '【抖音商城】订单导出文件已加密，解压密码为vGCPMK。', 'vGCPMK'),
        ]
        for key, text, expected in samples:
            with self.subTest(key=key):
                self.assertEqual(extract_code(text, key), expected)

    def test_rejects_ambiguous_long_and_wrong_purpose_codes(self):
        self.assertIsNone(extract_code('【抖店】验证码：1234 验证码：5678', 'douyin_order_otp'))
        self.assertIsNone(extract_code('【抖店】验证码：123456789', 'douyin_order_otp'))
        self.assertIsNone(extract_code('【快手小店】提取码：1234，正申请文件提取码。', 'kuaishou_export_otp'))

    def test_manual_reply_requires_a_label_or_standalone_code(self):
        self.assertEqual(FeishuService._verification_candidates('003762'), ['003762'])
        self.assertEqual(FeishuService._verification_candidates('@每日日报机器人 003762'), ['003762'])
        self.assertEqual(FeishuService._verification_candidates('今天处理了1234个订单'), [])
        self.assertEqual(FeishuService._verification_candidates('验证码：123456789012345'), [])

    def test_jd_task_reference_must_match_exactly(self):
        text = '【京东】以taskid-123-开头的加密导出文件，密码：KkTa3q。'
        self.assertEqual(extract_code(text, 'jd_archive_password', 'taskid-123'), 'KkTa3q')
        self.assertIsNone(extract_code(text, 'jd_archive_password', 'taskid-12'))

    def test_visible_text_excludes_ids_urls_and_controls(self):
        card = {'elements': [{'tag': 'markdown', 'content': '验证码：1234'}, {'tag': 'at', 'user_id': '123456'}, {'tag': 'button', 'text': '验证码：5678'}, {'url': 'https://example.com/123456'}]}
        self.assertEqual(visible_text('interactive', card), '验证码：1234')

    def test_event_and_history_sender_identity_types_are_distinct(self):
        history = normalize_history({'message_id': 'om_test', 'chat_id': 'oc_test', 'create_time': '123456', 'msg_type': 'text', 'body': {'content': '{"text":"验证码：1234"}'}, 'sender': {'sender_type': 'app', 'id_type': 'app_id', 'id': 'cli_sender'}})
        event = normalize_event({'header': {'event_type': 'im.message.receive_v1', 'app_id': 'cli_receiver'}, 'event': {'sender': {'sender_type': 'bot', 'sender_id': {'open_id': 'ou_sender'}}, 'message': {'message_id': 'om_test', 'chat_id': 'oc_test', 'create_time': '123456', 'message_type': 'text', 'content': '{"text":"验证码：1234"}'}}})
        self.assertEqual(history.sender_ids, (('app_id', 'cli_sender'),))
        self.assertEqual(event.sender_ids, (('open_id', 'ou_sender'),))
        self.assertNotIn(('app_id', 'cli_receiver'), event.sender_ids)

    def test_bot_matching_requires_identity_group_and_request_time(self):
        now = datetime.now(timezone.utc)
        challenge = {'chat_id': 'oc_test', 'created_at': now - timedelta(seconds=10), 'sms_route_key': 'douyin_order_otp'}
        trusted = [{'id_type': 'app_id', 'id': 'cli_sender'}]
        message = SmsMessage('om_test', 'oc_test', 'app', (('app_id', 'cli_sender'),), int(now.timestamp()*1000), '【抖店】验证码：1234')
        self.assertEqual(bot_matches(message, challenge, trusted, message.created_ms), '1234')
        self.assertIsNone(bot_matches(message, challenge, [{'id_type': 'open_id', 'id': 'cli_sender'}], message.created_ms))
        challenge['created_at'] = now + timedelta(seconds=1)
        self.assertIsNone(bot_matches(message, challenge, trusted, message.created_ms))

    def test_webhook_validation_never_accepts_other_hosts(self):
        SmsRelay.validate_webhook('https://open.feishu.cn/open-apis/bot/v2/hook/example-token')
        for value in ['http://open.feishu.cn/open-apis/bot/v2/hook/example', 'https://open.feishu.cn.evil.com/open-apis/bot/v2/hook/example', 'https://open.feishu.cn/open-apis/bot/v2/hook/example?secret=x']:
            with self.assertRaises(ValueError):
                SmsRelay.validate_webhook(value)

    def test_remote_clock_maps_database_age_without_admitting_older_messages(self):
        relay = SmsRelay(type('Service', (), {'database': None, 'cipher': None})())
        with patch('apps.feishu_ai.sms_relay.time.time', return_value=10):
            relay.observe_clock('Thu, 01 Jan 1970 00:00:07 GMT', 10000)
            self.assertEqual(relay.message_now_ms(), 8000)
            challenge = {'chat_id': 'oc_test', 'created_at': datetime.fromtimestamp(9, timezone.utc),
                         'challenge_age_seconds': 1, 'sms_route_key': 'douyin_order_otp'}
            challenge['message_cutoff_ms'] = relay.message_cutoff_ms(challenge, 8000)
            trusted = [{'id_type': 'app_id', 'id': 'cli_sender'}]
            current = SmsMessage('new', 'oc_test', 'app', (('app_id', 'cli_sender'),), 7500, '【抖店】验证码：1234')
            old = SmsMessage('old', 'oc_test', 'app', (('app_id', 'cli_sender'),), 6500, '【抖店】验证码：1234')
            self.assertEqual(bot_matches(current, challenge, trusted, 8000), '1234')
            self.assertIsNone(bot_matches(old, challenge, trusted, 8000))
