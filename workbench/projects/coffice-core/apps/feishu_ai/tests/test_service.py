import unittest

from apps.feishu_ai.service import FeishuService


class VerificationCandidateTests(unittest.TestCase):
    def test_extracts_code_after_feishu_mention_and_chinese_punctuation(self):
        self.assertEqual(
            FeishuService._verification_candidates("@每日日报机器人 验证码： 1222122"),
            ["1222122"],
        )

    def test_extracts_code_from_feishu_at_markup(self):
        self.assertEqual(
            FeishuService._verification_candidates(
                '<at user_id="ou_test">每日日报机器人</at>\n验证码: TEST1234'
            ),
            ["TEST1234"],
        )

    def test_falls_back_to_plain_alphanumeric_code(self):
        self.assertEqual(FeishuService._verification_candidates("@_user_1 TEST1234"), ["TEST1234"])

    def test_archive_password_parser_keeps_password_challenge_typed(self):
        self.assertEqual(
            FeishuService._challenge_candidates("archive_password", "@每日日报机器人 解压密码：QHrVql"),
            ["QHrVql"],
        )

    def test_archive_password_parser_accepts_file_extraction_code_label(self):
        self.assertEqual(
            FeishuService._challenge_candidates("archive_password", "文件提取码：KS-1234"),
            ["KS-1234"],
        )

    def test_archive_password_parser_does_not_accept_chinese_chat_text(self):
        self.assertEqual(
            FeishuService._challenge_candidates("archive_password", "请稍等，我去找密码"),
            [],
        )

    def test_retry_message_explains_archive_password_failure(self):
        message = FeishuService._verification_message(
            None,
            {"mention_open_ids": []},
            platform="抖音",
            company="公司",
            shop="店铺",
            purpose="解压密码错误，请重新输入。订单报表 ZIP 解压",
            challenge_type="archive_password",
        )
        text = message["zh_cn"]["content"][0][0]["text"]
        self.assertIn("上一次解压密码输入错误，请重新输入。", text)

    def test_automation_notice_is_human_handoff_without_reply_instruction(self):
        message = FeishuService._automation_notice_message(
            {"mention_open_ids": ["ou_test"]},
            platform="抖音",
            company="公司",
            shop="店铺",
            purpose="抖店登录滑块验证",
        )
        text = message["zh_cn"]["content"][0][0]["text"]
        self.assertIn("需要人工完成验证", text)
        self.assertIn("完成后继续进入店铺选择或业务页面", text)
        self.assertNotIn("回复验证码", text)


if __name__ == "__main__":
    unittest.main()
