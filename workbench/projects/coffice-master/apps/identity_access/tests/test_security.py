import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from apps.ai_analysis.crypto import SecretCipher
from apps.dashboard_center.service import DashboardService
from apps.identity_access.auth_service import LoginRateLimiter
from apps.identity_access.authorization import AuthContext, AuthorizationError, RateLimitError, required_permission
from apps.identity_access.password_cipher import UserPasswordCipher
from apps.identity_access.platform_shop_company_service import PlatformShopCompanyService, _platform_code
from apps.identity_access.security import password_hash, password_matches, token_hash, validate_password
from apps.identity_access.user_service import UserService


class SecurityUnitTests(unittest.TestCase):
    def test_password_is_bcrypt_and_never_plaintext(self):
        encoded = password_hash("Test-password-123")
        self.assertTrue(encoded.startswith("$2"))
        self.assertNotIn("Test-password-123", encoded)
        self.assertTrue(password_matches("Test-password-123", encoded))
        self.assertFalse(password_matches("wrong-password", encoded))

    def test_password_length_is_validated(self):
        with self.assertRaises(ValueError):
            validate_password("short")

    def test_blank_initial_password_uses_runtime_default(self):
        default_password = "Unit-default-123"
        with patch.dict(os.environ, {"DEFAULT_INITIAL_PASSWORD": default_password}):
            self.assertEqual(UserService.initial_password(""), default_password)
            self.assertEqual(UserService.initial_password(None), default_password)

    def test_reversible_user_password_cipher_is_bound_to_user_id(self):
        cipher = UserPasswordCipher(SecretCipher(key=b"0123456789abcdef0123456789abcdef"))
        password = "Cipher-test-123"
        ciphertext, nonce = cipher.encrypt(password, 17)
        self.assertNotIn(password.encode("utf-8"), ciphertext)
        self.assertEqual(cipher.decrypt(ciphertext, nonce, 17), password)
        with self.assertRaises(Exception):
            cipher.decrypt(ciphertext, nonce, 18)

    def test_password_view_requires_explicit_permission(self):
        denied = AuthContext(1, "tester", "测试", None, None, False, "", "", set(), {})
        with self.assertRaises(AuthorizationError):
            UserService.require_password_view(denied)
        allowed = AuthContext(
            1, "tester", "测试", None, None, False, "", "",
            {"system.user.password.view"}, {},
        )
        UserService.require_password_view(allowed)

    def test_token_hash_is_one_way_digest(self):
        digest = token_hash("secret-token")
        self.assertEqual(len(digest), 64)
        self.assertNotIn("secret-token", digest)

    def test_platform_shop_company_validation_and_status(self):
        self.assertEqual(_platform_code(" Custom-Platform "), "custom-platform")
        with self.assertRaises(ValueError):
            _platform_code("中文平台")
        today = date.today()
        base = {"is_active": True, "valid_from": today, "valid_to": None}
        self.assertEqual(PlatformShopCompanyService._status(base, today), "current")
        self.assertEqual(
            PlatformShopCompanyService._status({**base, "valid_from": today + timedelta(days=1)}, today),
            "future",
        )
        self.assertEqual(
            PlatformShopCompanyService._status({**base, "valid_from": today - timedelta(days=2), "valid_to": today - timedelta(days=1)}, today),
            "expired",
        )
        self.assertEqual(PlatformShopCompanyService._status({**base, "is_active": False}, today), "inactive")

        denied = AuthContext(1, "tester", "测试", None, None, False, "", "", set(), {})
        with self.assertRaises(AuthorizationError):
            PlatformShopCompanyService.require_view(denied)

    def test_business_routes_have_central_permissions(self):
        self.assertEqual(required_permission("POST", "/api/statement/B1/submit"), "bank.statement.submit")
        self.assertEqual(required_permission("DELETE", "/api/influencer/businesses/1"), "influencer.targets.manage")
        self.assertEqual(
            required_permission("POST", "/api/influencer/influencers/toggle-status"),
            "influencer.assignments.manage",
        )
        self.assertIn(
            "influencer.products.view",
            required_permission("GET", "/api/influencer/refresh-status"),
        )
        self.assertEqual(required_permission("POST", "/api/etl/runs"), "ingest.etl.manage")
        self.assertEqual(required_permission("PUT", "/api/expense-types/1"), "bank.types.manage")
        self.assertIn("bank.statement.view", required_permission("GET", "/api/expense-types"))
        self.assertIn("platform_fee.raw.view", required_permission("GET", "/api/ingest/fee-mappings"))
        self.assertEqual('platform_fee.mappings.view',required_permission('GET','/api/ingest/fee-mappings/scene-rules'))
        self.assertEqual('platform_fee.mappings.manage',required_permission('POST','/api/ingest/fee-mappings/scene-rules/preview'))
        self.assertIn(
            "finance_budget.promotion_total.manage",
            required_permission("POST", "/api/ingest/finance-config/budgets"),
        )
        expected_finance_writes = {
            "/api/ingest/finance-config/budgets": {
                "finance_budget.gsv_total.manage",
                "finance_budget.promotion_total.manage",
                "finance_budget.marketing_budget.manage",
            },
            "/api/ingest/finance-config/shop-plans": {
                "finance_budget.gsv_detail.manage",
                "finance_budget.shop_budget.manage",
            },
            "/api/ingest/finance-config/recharges": {"finance_budget.promotion_recharge.manage"},
            "/api/ingest/finance-config/marketing-expenses": {"finance_budget.marketing_expense.manage"},
            "/api/ingest/finance-config/expense-types": {"finance_budget.expense_type.manage"},
        }
        for path, expected in expected_finance_writes.items():
            self.assertEqual(set(required_permission("POST", path)), expected)
        self.assertEqual(
            set(required_permission("POST", "/api/ingest/finance-config/adjustments")),
            {
                "finance_budget.overview.view", "finance_budget.gsv.view",
                "finance_budget.promotion.view",
                "finance_budget.adjustment.view", "finance_budget.recharge.view",
                "finance_budget.spend.view", "finance_budget.marketing.view",
                "finance_budget.expense_type.view",
            },
        )
        self.assertEqual(
            set(required_permission("PUT", "/api/ingest/finance-config/shop-plans/12")),
            {"finance_budget.gsv_detail.manage", "finance_budget.shop_budget.manage"},
        )
        self.assertEqual(
            set(required_permission("DELETE", "/api/ingest/finance-config/expense-types/12")),
            {"finance_budget.expense_type.manage"},
        )
        self.assertEqual(
            set(required_permission("GET", "/api/ingest/finance-config/summary")),
            {
                "finance_budget.overview.view", "finance_budget.gsv.view",
                "finance_budget.promotion.view",
                "finance_budget.adjustment.view", "finance_budget.recharge.view",
                "finance_budget.spend.view", "finance_budget.marketing.view",
                "finance_budget.expense_type.view",
            },
        )
        self.assertEqual(
            required_permission("GET", "/api/ingest/finance-config/marketing-budget-history"),
            ("finance_budget.adjustment.view",),
        )

    def test_dataease_public_url_allowlist(self):
        service = DashboardService(None)
        valid = "http://192.168.77.111:8100/#/de-link/I9O1mwdA"
        self.assertEqual(service.validate_url(valid), valid)
        for invalid in (
            "https://example.com/#/de-link/I9O1mwdA",
            "javascript:alert(1)",
            "http://192.168.77.111:8100/#/dashboard/1",
        ):
            with self.assertRaises(ValueError):
                service.validate_url(invalid)

    def test_login_rate_limiter_rejects_before_authentication(self):
        limiter = LoginRateLimiter(window_seconds=60, user_ip_limit=3, ip_limit=10, cooldown_seconds=12)
        for _ in range(3):
            limiter.consume("someone", "127.0.0.1")
        with self.assertRaises(RateLimitError) as caught:
            limiter.consume("someone", "127.0.0.1")
        self.assertEqual(caught.exception.http_status, 429)
        self.assertEqual(caught.exception.retry_after, 12)

    def test_login_rate_limiter_isolated_by_username_and_ip(self):
        limiter = LoginRateLimiter(window_seconds=60, user_ip_limit=3, ip_limit=20, cooldown_seconds=10)
        for _ in range(3):
            limiter.consume("first", "127.0.0.1")
        limiter.consume("second", "127.0.0.1")
        limiter.consume("first", "127.0.0.2")


if __name__ == "__main__":
    unittest.main()
