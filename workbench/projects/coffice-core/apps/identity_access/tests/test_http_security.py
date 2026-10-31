from __future__ import annotations

import http.cookiejar
import json
import os
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

from apps.fund_split_adjust.database import Database
from apps.identity_access.security import password_hash


@unittest.skipUnless(os.getenv("RUN_HTTP_TESTS") == "1", "set RUN_HTTP_TESTS=1 with a running local test server")
class HttpSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = os.getenv("HTTP_TEST_BASE", "http://localhost:8771")
        cls.admin_username = os.environ["HTTP_TEST_USERNAME"]
        cls.admin_password = os.environ["HTTP_TEST_PASSWORD"]
        cls.restricted_username = "http_" + uuid.uuid4().hex[:10]
        cls.restricted_password = "Restricted-12345"
        cls.db = Database(
            host=os.getenv("PGHOST", "192.168.77.111"), port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"), user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"), upload_dir=__import__("pathlib").Path(os.getenv("TEMP", ".")) / "iam_http_test",
        )
        with cls.db.transaction() as cursor:
            cursor.execute(
                "SELECT user_id,NOW() AS test_started_at FROM iam.user_account WHERE username=%s AND deleted_at IS NULL",
                (cls.admin_username,),
            )
            admin = cursor.fetchone()
            cls.admin_user_id = int(admin["user_id"])
            cls.test_started_at = admin["test_started_at"]
            cursor.execute(
                "INSERT INTO iam.user_account(username,display_name,password_hash) VALUES (%s,'HTTP受限用户',%s) RETURNING user_id",
                (cls.restricted_username, password_hash(cls.restricted_password)),
            )
            cls.restricted_user_id = int(cursor.fetchone()["user_id"])

    @classmethod
    def tearDownClass(cls):
        with cls.db.transaction() as cursor:
            cursor.execute(
                """DELETE FROM iam.audit_log
                   WHERE user_id=%s AND user_agent LIKE 'Python-urllib/%%' AND created_at>=%s""",
                (cls.admin_user_id, cls.test_started_at),
            )
            cursor.execute(
                """DELETE FROM iam.user_session
                   WHERE user_id=%s AND user_agent LIKE 'Python-urllib/%%' AND created_at>=%s""",
                (cls.admin_user_id, cls.test_started_at),
            )
            cursor.execute(
                "DELETE FROM iam.login_attempt WHERE username=%s AND attempted_at>=%s",
                (cls.admin_username, cls.test_started_at),
            )
            cursor.execute("DELETE FROM iam.audit_log WHERE user_id=%s OR username=%s", (cls.restricted_user_id, cls.restricted_username))
            cursor.execute("DELETE FROM iam.login_attempt WHERE username=%s", (cls.restricted_username,))
            cursor.execute("DELETE FROM iam.user_account WHERE user_id=%s", (cls.restricted_user_id,))
        with cls.db.transaction() as cursor:
            cursor.execute(
                """SELECT
                       (SELECT COUNT(*) FROM iam.audit_log WHERE user_id=%s AND user_agent LIKE 'Python-urllib/%%' AND created_at>=%s) AS audits,
                       (SELECT COUNT(*) FROM iam.user_session WHERE user_id=%s AND user_agent LIKE 'Python-urllib/%%' AND created_at>=%s) AS sessions,
                       (SELECT COUNT(*) FROM iam.login_attempt WHERE username=%s AND attempted_at>=%s) AS attempts,
                       (SELECT COUNT(*) FROM iam.user_account WHERE user_id=%s) AS restricted_users""",
                (
                    cls.admin_user_id, cls.test_started_at,
                    cls.admin_user_id, cls.test_started_at,
                    cls.admin_username, cls.test_started_at,
                    cls.restricted_user_id,
                ),
            )
            remaining = dict(cursor.fetchone())
        if any(remaining.values()):
            raise AssertionError(f"HTTP测试数据清理不完整: {remaining}")

    @staticmethod
    def opener():
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar

    def request(self, opener, path, *, method="GET", payload=None, csrf=None):
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if csrf:
            headers["X-CSRF-Token"] = csrf
        request = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            response = opener.open(request, timeout=10)
            return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def login(self, username, password):
        opener, jar = self.opener()
        status, result = self.request(opener, "/api/auth/login", method="POST", payload={"username": username, "password": password})
        self.assertEqual(status, 200, result)
        csrf = next(cookie.value for cookie in jar if cookie.name == "mocc_csrf")
        return opener, csrf

    def test_unauthenticated_forbidden_csrf_allowlist_and_logout(self):
        anonymous, _ = self.opener()
        status, _ = self.request(anonymous, "/api/health")
        self.assertEqual(status, 401)

        admin, csrf = self.login(self.admin_username, self.admin_password)
        status, _ = self.request(admin, "/api/dashboards/admin/test", method="POST", payload={
            "share_url": "http://192.168.77.111:8100/#/de-link/TEST1234",
        })
        self.assertEqual(status, 403)
        status, result = self.request(admin, "/api/dashboards/admin/test", method="POST", csrf=csrf, payload={
            "share_url": "https://example.com/#/de-link/TEST1234",
        })
        self.assertEqual(status, 400, result)
        status, result = self.request(admin, "/api/dashboards/admin/test", method="POST", csrf=csrf, payload={
            "share_url": "http://192.168.77.111:8100/#/de-link/TEST1234",
        })
        self.assertEqual(status, 200, result)
        status, result = self.request(admin, "/api/health")
        self.assertEqual(status, 200, result)
        self.assertEqual(set(result["data"]["modules"]), {"bank", "influencer", "ingest", "worker", "dashboard"})
        status, result = self.request(admin, "/api/ingest/health")
        self.assertEqual(status, 200, result)
        self.assertTrue(result["data"]["deprecated"])
        self.assertEqual(result["data"]["replacement"], "/api/health")
        status, _ = self.request(admin, "/api/auth/logout", method="POST", csrf=csrf, payload={})
        self.assertEqual(status, 200)
        status, _ = self.request(admin, "/api/health")
        self.assertEqual(status, 401)

    def test_restricted_user_gets_403_for_api_and_manual_page(self):
        restricted, _ = self.login(self.restricted_username, self.restricted_password)
        status, _ = self.request(restricted, "/api/import/records")
        self.assertEqual(status, 403)
        status, _ = self.request(restricted, "/system/")
        self.assertEqual(status, 403)
        response = restricted.open(self.base + "/", timeout=10)
        body = response.read().decode("utf-8")
        self.assertTrue(response.geturl().endswith("/welcome/"), response.geturl())
        self.assertIn("欢迎登录经营配置中心", body)

    def test_platform_shop_company_page_list_and_crud(self):
        admin, csrf = self.login(self.admin_username, self.admin_password)
        platform_code = "http_map_" + uuid.uuid4().hex[:10]
        created_ids: list[int] = []
        payload = {
            "platform_code": platform_code,
            "platform_name": "HTTP测试平台",
            "company_code": "http_company",
            "company_name": "HTTP测试公司",
            "shop_code": "http_shop",
            "shop_name": "HTTP测试店铺",
            "shop_type": "测试店",
            "account_id": "http_account",
            "valid_from": (date.today() - timedelta(days=3)).isoformat(),
        }
        try:
            response = admin.open(self.base + "/system/", timeout=10)
            page = response.read().decode("utf-8")
            self.assertIn('data-page="platformShopCompany"', page)
            self.assertIn("system-platform-shop-company.js", page)

            status, result = self.request(
                admin, "/api/system/platform-shop-companies", method="POST", payload=payload, csrf=csrf,
            )
            self.assertEqual(status, 201, result)
            created_ids.append(result["data"]["shop_company_sk"])

            status, result = self.request(
                admin, f"/api/system/platform-shop-companies?platform={platform_code}&status=all",
            )
            self.assertEqual(status, 200, result)
            self.assertEqual(result["data"]["total"], 1)

            status, result = self.request(
                admin, f"/api/system/platform-shop-companies/{created_ids[0]}", method="PUT",
                payload={"shop_name": "HTTP测试店铺已编辑"}, csrf=csrf,
            )
            self.assertEqual(status, 200, result)
            self.assertEqual(result["data"]["shop_name"], "HTTP测试店铺已编辑")

            version_payload = {
                **payload,
                "company_code": "http_company_v2",
                "company_name": "HTTP测试公司二",
                "valid_from": (date.today() + timedelta(days=3)).isoformat(),
                "create_version": True,
            }
            status, result = self.request(
                admin, f"/api/system/platform-shop-companies/{created_ids[0]}", method="PUT",
                payload=version_payload, csrf=csrf,
            )
            self.assertEqual(status, 200, result)
            created_ids.append(result["data"]["shop_company_sk"])
            self.assertEqual(result["data"]["mapping_status"], "future")

            status, result = self.request(
                admin, f"/api/system/platform-shop-companies/{created_ids[1]}", method="DELETE", csrf=csrf,
            )
            self.assertEqual(status, 200, result)
            self.assertEqual(result["data"]["mapping_status"], "inactive")
            self.assertEqual(result["data"]["reopened_shop_company_sk"], created_ids[0])
        finally:
            with self.db.transaction() as cursor:
                cursor.execute(
                    "SELECT shop_company_sk::text FROM dim.dim_platform_shop_company WHERE platform_code=%s",
                    (platform_code,),
                )
                target_ids = [row["shop_company_sk"] for row in cursor.fetchall()]
                if target_ids:
                    cursor.execute(
                        "DELETE FROM iam.audit_log WHERE target_type='platform_shop_company' AND target_id=ANY(%s)",
                        (target_ids,),
                    )
                cursor.execute(
                    "DELETE FROM dim.dim_platform_shop_company WHERE platform_code=%s",
                    (platform_code,),
                )

    def test_login_error_messages_and_request_rate_limit(self):
        anonymous, _ = self.opener()
        username = "missing_" + uuid.uuid4().hex[:10]
        try:
            for attempt in range(1, 7):
                status, result = self.request(anonymous, "/api/auth/login", method="POST", payload={
                    "username": username, "password": "Unknown-password-123",
                })
                if attempt <= 5:
                    self.assertEqual(status, 401, result)
                    self.assertIn("没有该用户", result["message"])
                else:
                    self.assertEqual(status, 429, result)
                    self.assertIn("登录请求过于频繁", result["message"])
        finally:
            with self.db.transaction() as cursor:
                cursor.execute("DELETE FROM iam.audit_log WHERE username IS NULL AND target_id=%s", (username,))
                cursor.execute("DELETE FROM iam.login_attempt WHERE username=%s", (username,))


if __name__ == "__main__":
    unittest.main()
