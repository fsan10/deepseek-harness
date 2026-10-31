from __future__ import annotations

import base64
import os
import re
import shutil
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path

from apps.dashboard_center.service import DashboardService
from apps.fund_split_adjust.database import Database
from apps.identity_access.auth_service import AuthService, SESSION_COOKIE
from apps.identity_access.authorization import AuthContext, AuthenticationError
from apps.identity_access.organization_service import OrganizationService
from apps.identity_access.platform_shop_company_service import (
    PlatformShopCompanyConflictError,
    PlatformShopCompanyService,
)
from apps.identity_access.role_service import RoleService
from apps.identity_access.security import password_hash
from apps.identity_access.user_service import UserService


@unittest.skipUnless(os.getenv("RUN_DB_TESTS") == "1", "set RUN_DB_TESTS=1 to run PostgreSQL integration tests")
class IdentityDatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("AUTH_BCRYPT_ROUNDS", "10")
        os.environ.setdefault(
            "AI_CONFIG_ENCRYPTION_KEY",
            base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii"),
        )
        cls.prefix = "codex_" + uuid.uuid4().hex[:10]
        cls.db = Database(
            host=os.getenv("PGHOST", "192.168.77.111"), port=int(os.getenv("PGPORT", "5432")),
            dbname=os.getenv("PGDATABASE", "mock_coffice"), user=os.getenv("PGUSER", "postgres"),
            password=os.getenv("PGPASSWORD"), upload_dir=Path(tempfile.mkdtemp(prefix="iam_test_")),
        )
        with cls.db.transaction() as cursor:
            cursor.execute("INSERT INTO iam.department(department_code,department_name) VALUES (%s,'测试上级') RETURNING department_id", (cls.prefix + "_p",))
            cls.parent_id = int(cursor.fetchone()["department_id"])
            cursor.execute("INSERT INTO iam.department(department_code,department_name,parent_department_id) VALUES (%s,'测试子级',%s) RETURNING department_id", (cls.prefix + "_c", cls.parent_id))
            cls.child_id = int(cursor.fetchone()["department_id"])
            cursor.execute("INSERT INTO iam.role(role_code,role_name) VALUES (%s,'测试角色') RETURNING role_id", (cls.prefix + "_r",))
            cls.role_id = int(cursor.fetchone()["role_id"])
            cursor.execute("INSERT INTO iam.user_account(username,display_name,password_hash,department_id) VALUES (%s,'测试用户',%s,%s) RETURNING user_id", (cls.prefix, password_hash("Integration-12345"), cls.child_id))
            cls.user_id = int(cursor.fetchone()["user_id"])
            cursor.execute("INSERT INTO iam.user_role(user_id,role_id) VALUES (%s,%s)", (cls.user_id, cls.role_id))
            cursor.execute("INSERT INTO iam.role_permission(role_id,resource_id) SELECT %s,resource_id FROM iam.permission_resource WHERE resource_code='bank.statement.view'", (cls.role_id,))
            cursor.execute("INSERT INTO iam.department_permission(department_id,resource_id) SELECT %s,resource_id FROM iam.permission_resource WHERE resource_code='bank.types.view'", (cls.parent_id,))
            cursor.execute("INSERT INTO iam.user_permission(user_id,resource_id,permission_effect) SELECT %s,resource_id,'allow' FROM iam.permission_resource WHERE resource_code='bank.accounts.view'", (cls.user_id,))
            cursor.execute("INSERT INTO iam.user_permission(user_id,resource_id,permission_effect) SELECT %s,resource_id,'deny' FROM iam.permission_resource WHERE resource_code='bank.statement.view'", (cls.user_id,))

    @classmethod
    def tearDownClass(cls):
        with cls.db.transaction() as cursor:
            cursor.execute("DELETE FROM iam.audit_log WHERE user_id=%s OR username=%s", (cls.user_id, cls.prefix))
            cursor.execute("DELETE FROM iam.login_attempt WHERE username=%s", (cls.prefix,))
            cursor.execute("DELETE FROM iam.user_account WHERE user_id=%s", (cls.user_id,))
            cursor.execute("DELETE FROM iam.role WHERE role_id=%s", (cls.role_id,))
            cursor.execute("DELETE FROM iam.department WHERE department_id IN (%s,%s)", (cls.child_id, cls.parent_id))
        shutil.rmtree(cls.db.upload_dir, ignore_errors=True)

    def setUp(self):
        with self.db.transaction() as cursor:
            cursor.execute("UPDATE iam.user_account SET is_active=TRUE,failed_login_count=0,locked_until=NULL,session_version=session_version+1 WHERE user_id=%s", (self.user_id,))
            cursor.execute("DELETE FROM iam.user_session WHERE user_id=%s", (self.user_id,))

    def test_permission_priority_and_parent_department_inheritance(self):
        auth = AuthService(self.db)
        with self.db.transaction() as cursor:
            allowed, sources = auth._effective_permissions(cursor, self.user_id, False)
        self.assertNotIn("bank.statement.view", allowed)
        self.assertEqual(sources["bank.statement.view"], "user_deny")
        self.assertEqual(sources["bank.accounts.view"], "user_allow")
        self.assertEqual(sources["bank.types.view"], "department")

    def test_login_csrf_session_and_disabled_user_invalidation(self):
        auth = AuthService(self.db)
        with self.assertRaisesRegex(AuthenticationError, "密码错误"):
            auth.login({"username": self.prefix, "password": "wrong-password"}, ip_address="127.0.0.1", user_agent="test")
        with self.db.transaction() as cursor:
            cursor.execute("SELECT failed_login_count FROM iam.user_account WHERE user_id=%s", (self.user_id,))
            self.assertEqual(cursor.fetchone()["failed_login_count"], 1)
        data, raw_token = auth.login({"username": self.prefix, "password": "Integration-12345"}, ip_address="127.0.0.1", user_agent="test")
        headers = {"Cookie": f"{SESSION_COOKIE}={raw_token}; mocc_csrf={data['csrf_token']}", "X-CSRF-Token": data["csrf_token"]}
        context = auth.authenticate(headers)
        auth.verify_csrf(context, headers)
        with self.db.transaction() as cursor:
            cursor.execute("UPDATE iam.user_account SET is_active=FALSE,session_version=session_version+1 WHERE user_id=%s", (self.user_id,))
        with self.assertRaises(AuthenticationError):
            auth.authenticate(headers)

    def test_unknown_user_has_specific_message(self):
        username = self.prefix + "_missing"
        with self.assertRaisesRegex(AuthenticationError, "没有该用户"):
            AuthService(self.db).login(
                {"username": username, "password": "Unknown-password-123"},
                ip_address="127.0.0.9", user_agent="test",
            )
        with self.db.transaction() as cursor:
            cursor.execute("DELETE FROM iam.audit_log WHERE username IS NULL AND target_id=%s", (username,))
            cursor.execute("DELETE FROM iam.login_attempt WHERE username=%s", (username,))

    def test_department_cycle_is_rejected(self):
        service = OrganizationService(self.db)
        context = AuthContext(0,"tester","tester",None,None,True,"","",set(),{})
        with self.assertRaises(ValueError):
            service.update(context, self.parent_id, {"parent_department_id": self.child_id}, ip_address="127.0.0.1", user_agent="test")

    def test_super_admin_can_see_seeded_dashboards(self):
        context = AuthContext(0,"tester","tester",None,None,True,"","",set(),{})
        items = DashboardService(self.db).permitted(context)["items"]
        seeded_urls = {
            "http://192.168.77.111:8100/#/de-link/I9O1mwdA",
            "http://192.168.77.111:8100/#/de-link/D7Yoez1x",
        }
        self.assertTrue(seeded_urls.issubset({item["share_url"] for item in items}))
        self.assertTrue(all(re.fullmatch(r"dashboard_[0-9a-f]{32}", item["dashboard_code"]) for item in items))

    def test_platform_shop_company_crud_versioning_and_expiry(self):
        service = PlatformShopCompanyService(self.db)
        actor = AuthContext(
            self.user_id, self.prefix, "测试用户", self.child_id, "测试子级", False, "", "",
            {"system.platform_shop_company.view", "system.platform_shop_company.manage"}, {},
        )
        platform_code = f"codex_{uuid.uuid4().hex[:10]}"
        today = date.today()
        created_ids: list[int] = []

        def payload(shop_code: str, company_code: str, valid_from: date) -> dict:
            return {
                "platform_code": platform_code.upper(),
                "platform_name": "集成测试平台",
                "company_code": company_code,
                "company_name": f"{company_code}测试公司",
                "shop_code": shop_code,
                "shop_name": f"{shop_code}测试店铺",
                "shop_type": "测试店",
                "account_id": f"account_{shop_code}",
                "valid_from": valid_from.isoformat(),
            }

        try:
            first = service.create(
                actor, payload("shop_a", "company_a", today - timedelta(days=30)),
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            created_ids.append(first["shop_company_sk"])
            self.assertEqual(first["platform_code"], platform_code)
            self.assertEqual(first["mapping_status"], "current")

            second_payload = payload("shop_a", "company_b", today - timedelta(days=10))
            second_payload["create_version"] = True
            second = service.update(
                actor, first["shop_company_sk"], second_payload,
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            created_ids.append(second["shop_company_sk"])
            self.assertEqual(second["closed_shop_company_sk"], first["shop_company_sk"])
            with self.db.transaction() as cursor:
                cursor.execute(
                    "SELECT valid_to FROM dim.dim_platform_shop_company WHERE shop_company_sk=%s",
                    (first["shop_company_sk"],),
                )
                self.assertEqual(cursor.fetchone()["valid_to"], today - timedelta(days=11))

            updated = service.update(
                actor, second["shop_company_sk"], {"shop_name": "已编辑测试店铺"},
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            self.assertEqual(updated["shop_name"], "已编辑测试店铺")
            with self.assertRaises(PlatformShopCompanyConflictError):
                service.create(
                    actor, payload("shop_a", "company_c", today - timedelta(days=20)),
                    ip_address="127.0.0.1", user_agent="integration-test",
                )

            listed = service.list(actor, {"platform": platform_code, "shop": "shop_a", "status": "all"})
            self.assertEqual(listed["total"], 2)
            self.assertEqual({item["company_code"] for item in listed["items"]}, {"company_a", "company_b"})

            expired = service.expire(
                actor, second["shop_company_sk"], ip_address="127.0.0.1", user_agent="integration-test",
            )
            self.assertEqual(expired["mapping_status"], "expired")
            self.assertEqual(expired["valid_to"], today - timedelta(days=1))

            current = service.create(
                actor, payload("shop_future", "company_a", today - timedelta(days=20)),
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            created_ids.append(current["shop_company_sk"])
            future_payload = payload("shop_future", "company_b", today + timedelta(days=10))
            future_payload["create_version"] = True
            future = service.update(
                actor, current["shop_company_sk"], future_payload,
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            created_ids.append(future["shop_company_sk"])
            self.assertEqual(future["mapping_status"], "future")
            disabled = service.expire(
                actor, future["shop_company_sk"], ip_address="127.0.0.1", user_agent="integration-test",
            )
            self.assertEqual(disabled["mapping_status"], "inactive")
            self.assertEqual(disabled["reopened_shop_company_sk"], current["shop_company_sk"])
            with self.db.transaction() as cursor:
                cursor.execute(
                    "SELECT valid_to FROM dim.dim_platform_shop_company WHERE shop_company_sk=%s",
                    (current["shop_company_sk"],),
                )
                self.assertIsNone(cursor.fetchone()["valid_to"])

            renamed_source = service.create(
                actor, payload("shop_old_code", "company_a", today - timedelta(days=5)),
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            renamed_payload = payload("shop_new_code", "company_a", today + timedelta(days=1))
            renamed_payload["create_version"] = True
            renamed = service.update(
                actor, renamed_source["shop_company_sk"], renamed_payload,
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            self.assertEqual(renamed["closed_shop_company_sk"], renamed_source["shop_company_sk"])
            with self.db.transaction() as cursor:
                cursor.execute(
                    "SELECT valid_to FROM dim.dim_platform_shop_company WHERE shop_company_sk=%s",
                    (renamed_source["shop_company_sk"],),
                )
                self.assertEqual(cursor.fetchone()["valid_to"], today)

            chain_current = service.create(
                actor, payload("shop_chain", "company_a", today - timedelta(days=20)),
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            chain_middle_payload = payload("shop_chain", "company_b", today + timedelta(days=5))
            chain_middle_payload["create_version"] = True
            chain_middle = service.update(
                actor, chain_current["shop_company_sk"], chain_middle_payload,
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            chain_latest_payload = payload("shop_chain", "company_c", today + timedelta(days=10))
            chain_latest_payload["create_version"] = True
            chain_latest = service.update(
                actor, chain_middle["shop_company_sk"], chain_latest_payload,
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            disabled_middle = service.expire(
                actor, chain_middle["shop_company_sk"],
                ip_address="127.0.0.1", user_agent="integration-test",
            )
            self.assertEqual(disabled_middle["mapping_status"], "inactive")
            self.assertEqual(disabled_middle["reopened_shop_company_sk"], chain_current["shop_company_sk"])
            with self.db.transaction() as cursor:
                cursor.execute(
                    """SELECT shop_company_sk,valid_to FROM dim.dim_platform_shop_company
                       WHERE shop_company_sk IN (%s,%s) ORDER BY shop_company_sk""",
                    (chain_current["shop_company_sk"], chain_latest["shop_company_sk"]),
                )
                periods = {row["shop_company_sk"]: row["valid_to"] for row in cursor.fetchall()}
                self.assertEqual(periods[chain_current["shop_company_sk"]], today + timedelta(days=9))
                self.assertIsNone(periods[chain_latest["shop_company_sk"]])

            with self.db.transaction() as cursor:
                cursor.execute(
                    """SELECT action_code FROM iam.audit_log
                       WHERE username=%s AND target_type='platform_shop_company'""",
                    (self.prefix,),
                )
                actions = {row["action_code"] for row in cursor.fetchall()}
                self.assertIn("platform_shop_company.version_close", actions)
                self.assertIn("platform_shop_company.version_relink", actions)
        finally:
            with self.db.transaction() as cursor:
                cursor.execute(
                    "DELETE FROM iam.audit_log WHERE username=%s AND target_type='platform_shop_company'",
                    (self.prefix,),
                )
                cursor.execute(
                    "DELETE FROM dim.dim_platform_shop_company WHERE platform_code=%s",
                    (platform_code,),
                )

    def test_user_department_role_and_dashboard_crud(self):
        actor = AuthContext(self.user_id,self.prefix,"测试用户",self.child_id,"测试子级",True,"","",set(),{})
        suffix = uuid.uuid4().hex[:6]
        dept_code, role_code, username = (
            f"{self.prefix}_{suffix}d", f"{self.prefix}_{suffix}r",
            f"{self.prefix}.{suffix}",
        )
        department = role = user = dashboard = None
        try:
            department = OrganizationService(self.db).create(actor, {
                "department_code": dept_code, "department_name": "CRUD部门", "display_order": 8,
            }, ip_address="127.0.0.1", user_agent="test")
            role = RoleService(self.db).save(actor, {
                "role_code": role_code, "role_name": "CRUD角色", "role_description": "integration", "is_active": True,
            }, None, ip_address="127.0.0.1", user_agent="test")
            user_service = UserService(self.db)
            user = user_service.create(actor, {
                "username": username, "display_name": "CRUD用户", "password": "Crud-password-123",
                "department_id": department["department_id"], "role_ids": [role["role_id"]], "is_super_admin": False,
            }, ip_address="127.0.0.1", user_agent="test")
            viewed = user_service.view_password(
                actor, user["user_id"], ip_address="127.0.0.1", user_agent="test-view-password",
            )
            self.assertEqual(viewed["password"], "Crud-password-123")
            updated = user_service.update(actor, user["user_id"], {
                "display_name": "CRUD用户已编辑", "department_id": department["department_id"],
                "role_ids": [role["role_id"]], "is_active": True, "is_super_admin": False,
            }, ip_address="127.0.0.1", user_agent="test")
            self.assertEqual(updated["display_name"], "CRUD用户已编辑")
            dashboard = DashboardService(self.db).save(actor, {
                "dashboard_name": "CRUD看板",
                "share_url": "http://192.168.77.111:8100/#/de-link/CRUD1234",
                "icon_name": "dashboard", "display_order": 88, "allow_fullscreen": True, "is_active": True,
            }, None, ip_address="127.0.0.1", user_agent="test")
            self.assertRegex(dashboard["dashboard_code"], r"^dashboard_[0-9a-f]{32}$")
            updated_dashboard = DashboardService(self.db).save(actor, {
                "dashboard_name": "CRUD看板已编辑",
                "share_url": "http://192.168.77.111:8100/#/de-link/CRUD5678",
                "icon_name": "dashboard", "display_order": 88, "allow_fullscreen": True, "is_active": True,
                "dashboard_code": "manually_supplied_code",
            }, dashboard["dashboard_id"], ip_address="127.0.0.1", user_agent="test")
            self.assertEqual(updated_dashboard["dashboard_code"], dashboard["dashboard_code"])
            DashboardService(self.db).delete(actor, dashboard["dashboard_id"], ip_address="127.0.0.1", user_agent="test")
            with self.db.transaction() as cursor:
                cursor.execute("SELECT deleted_at FROM config.dashboard WHERE dashboard_id=%s", (dashboard["dashboard_id"],))
                self.assertIsNotNone(cursor.fetchone()["deleted_at"])
        finally:
            with self.db.transaction() as cursor:
                if dashboard:
                    cursor.execute("DELETE FROM iam.role_permission WHERE resource_id=%s", (dashboard["permission_resource_id"],))
                    cursor.execute("DELETE FROM iam.department_permission WHERE resource_id=%s", (dashboard["permission_resource_id"],))
                    cursor.execute("DELETE FROM iam.user_permission WHERE resource_id=%s", (dashboard["permission_resource_id"],))
                    cursor.execute("DELETE FROM config.dashboard WHERE dashboard_id=%s", (dashboard["dashboard_id"],))
                    cursor.execute("DELETE FROM iam.permission_resource WHERE resource_id=%s", (dashboard["permission_resource_id"],))
                if user:
                    cursor.execute(
                        "DELETE FROM iam.audit_log WHERE target_type='user' AND target_id=%s",
                        (str(user["user_id"]),),
                    )
                    cursor.execute("DELETE FROM iam.user_account WHERE user_id=%s", (user["user_id"],))
                if role:
                    cursor.execute("DELETE FROM iam.role WHERE role_id=%s", (role["role_id"],))
                if department:
                    cursor.execute("DELETE FROM iam.department WHERE department_id=%s", (department["department_id"],))


if __name__ == "__main__":
    unittest.main()
