from __future__ import annotations

import unittest

from scripts.auto_download.playwright.douyin_login import (
    AGREEMENT_XPATH,
    CAPTCHA_IFRAME_XPATH,
    CAPTCHA_IFRAME_SELECTORS,
    EMAIL_FORM_MARKER_TEXT,
    EMAIL_LOGIN_XPATH,
    EMAIL_SWITCH_SELECTOR,
    LOGIN_ROOT_XPATH,
    MOBILE_FORM_MARKER_TEXTS,
    STORE_LIST_XPATH,
    STORE_FIRST_NAME_XPATH,
    is_captcha_verify_failure,
)


class DouyinLoginContractTests(unittest.TestCase):
    def test_operator_confirmed_selectors_are_kept(self) -> None:
        self.assertEqual('//*[@d="root"]/div/div[1]/div/div/div/div', LOGIN_ROOT_XPATH)
        self.assertEqual('//*[@id="ecomLoginForm"]/section/div[2]/div[2]', EMAIL_LOGIN_XPATH)
        self.assertEqual(
            '//*[@id="root"]/div/div[1]/div/div/div/div/div[2]/div[4]/div[1]/label/span/input',
            AGREEMENT_XPATH,
        )
        self.assertEqual('//*[@id="captcha_container"]/iframe', CAPTCHA_IFRAME_XPATH)
        self.assertEqual(
            '//*[@id="root"]/div/div[1]/div/div/div/div/div/div/div[3]',
            STORE_LIST_XPATH,
        )
        self.assertEqual(
            '//*[@id="root"]/div/div[1]/div/div/div/div/div/div/div[3]/div[1]/div[2]/div[1]',
            STORE_FIRST_NAME_XPATH,
        )

    def test_captcha_http_500_is_failure_but_other_statuses_are_not(self) -> None:
        self.assertTrue(is_captcha_verify_failure("https://verify.zijieapi.com/captcha/verify", 500))
        self.assertFalse(is_captcha_verify_failure("https://verify.zijieapi.com/captcha/verify", 200))
        self.assertFalse(is_captcha_verify_failure("https://fxg.jinritemai.com/login", 500))

    def test_current_captcha_iframe_hosts_are_supported(self) -> None:
        self.assertIn('iframe[src*="rmc.bytedance.com"]', CAPTCHA_IFRAME_SELECTORS)
        self.assertIn('iframe[src*="/verifycenter/captcha/"]', CAPTCHA_IFRAME_SELECTORS)

    def test_email_switch_uses_semantic_postcondition(self) -> None:
        self.assertEqual("邮箱停用或忘记", EMAIL_FORM_MARKER_TEXT)
        self.assertIn("手机号停用或忘记", MOBILE_FORM_MARKER_TEXTS)
        self.assertEqual(".account-center-switch-button.email", EMAIL_SWITCH_SELECTOR)


if __name__ == "__main__":
    unittest.main()
