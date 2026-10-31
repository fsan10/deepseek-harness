from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from psycopg2 import sql

from apps.ai_admin.config_service import ConfigurationService
from apps.ai_analysis.crypto import SecretCipher
from apps.ai_analysis.query_executor import ReadonlyQueryExecutor
from apps.ai_analysis.service import AiAnalysisService
from apps.fund_split_adjust.database import Database
from apps.feishu_ai.service import FeishuService
from apps.identity_access.authorization import AuthContext
from apps.identity_access.security import password_hash


@unittest.skipUnless(os.getenv("RUN_DB_TESTS")=="1","set RUN_DB_TESTS=1 to run PostgreSQL integration tests")
class AiDatabaseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prefix="codex_ai_"+uuid.uuid4().hex[:8]; cls.role=cls.prefix+"_ro"; cls.role_password="ReadOnly-"+uuid.uuid4().hex
        cls.db=Database(host=os.getenv("PGHOST","192.168.77.111"),port=int(os.getenv("PGPORT","5432")),dbname=os.getenv("PGDATABASE","mock_coffice"),user=os.getenv("PGUSER","postgres"),password=os.getenv("PGPASSWORD"),upload_dir=Path(tempfile.mkdtemp(prefix="ai_test_")))
        cls.cipher=SecretCipher(b"0123456789abcdef0123456789abcdef")
        with cls.db.transaction() as cursor:
            cursor.execute("INSERT INTO iam.department(department_code,department_name) VALUES (%s,'AI测试部门') RETURNING department_id",(cls.prefix,)); cls.department_id=int(cursor.fetchone()["department_id"])
            cursor.execute("INSERT INTO iam.role(role_code,role_name) VALUES (%s,'AI测试角色') RETURNING role_id",(cls.prefix,)); cls.role_id=int(cursor.fetchone()["role_id"])
            cursor.execute("INSERT INTO iam.user_account(username,display_name,password_hash,department_id) VALUES (%s,'AI测试用户',%s,%s) RETURNING user_id",(cls.prefix,password_hash("Test-password-123"),cls.department_id)); cls.user_id=int(cursor.fetchone()["user_id"])
            cursor.execute("INSERT INTO iam.user_role(user_id,role_id) VALUES (%s,%s)",(cls.user_id,cls.role_id))
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(cls.role)),(cls.role_password,))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(os.getenv("PGDATABASE","mock_coffice")),sql.Identifier(cls.role)))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA ads, dim TO {}").format(sql.Identifier(cls.role)))
            cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA ads, dim TO {}").format(sql.Identifier(cls.role)))
        cls.context=AuthContext(cls.user_id,cls.prefix,"AI测试用户",cls.department_id,"AI测试部门",True,"","",set(),{})

    @classmethod
    def tearDownClass(cls):
        with cls.db.transaction() as cursor:
            cursor.execute("DELETE FROM ai.query_audit WHERE user_id=%s",(cls.user_id,))
            cursor.execute("DELETE FROM ai.message WHERE conversation_id IN (SELECT conversation_id FROM ai.conversation WHERE user_id=%s)",(cls.user_id,))
            cursor.execute("DELETE FROM ai.conversation WHERE user_id=%s",(cls.user_id,))
            cursor.execute("DELETE FROM ai.data_source WHERE source_code LIKE %s",(cls.prefix+"%",)); cursor.execute("DELETE FROM ai.provider_config WHERE config_code LIKE %s",(cls.prefix+"%",))
            cursor.execute("DELETE FROM iam.audit_log WHERE user_id=%s",(cls.user_id,)); cursor.execute("DELETE FROM iam.user_account WHERE user_id=%s",(cls.user_id,)); cursor.execute("DELETE FROM iam.role WHERE role_id=%s",(cls.role_id,)); cursor.execute("DELETE FROM iam.department WHERE department_id=%s",(cls.department_id,))
            cursor.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(cls.role)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.role)))

    def test_model_key_is_encrypted_and_response_masked(self):
        service=ConfigurationService(self.db,self.cipher); value=service.save_model(self.context,{"config_code":self.prefix+"_model","config_name":"测试模型","api_base_url":"https://api.deepseek.com","api_key":"sk-test-secret-abcd","model_name":"deepseek-v4-flash","is_active":False,"is_default":False})
        self.assertNotIn("api_key",value); self.assertIn("****",value["api_key_masked"])
        with self.db.transaction() as cursor:
            cursor.execute("SELECT api_key_ciphertext,api_key_nonce FROM ai.provider_config WHERE provider_config_id=%s",(value["provider_config_id"],)); row=cursor.fetchone()
        self.assertNotIn(b"sk-test",bytes(row["api_key_ciphertext"])); self.assertEqual(self.cipher.decrypt(row["api_key_ciphertext"],row["api_key_nonce"],context=f"provider:{self.prefix}_model"),"sk-test-secret-abcd")

    def test_readonly_source_discovers_ads_dim_and_queries_without_saved_catalog(self):
        config=ConfigurationService(self.db,self.cipher); source=config.save_source(self.context,{"source_code":self.prefix+"_source","source_name":"测试只读源","host":os.getenv("PGHOST","192.168.77.111"),"port":int(os.getenv("PGPORT","5432")),"database_name":os.getenv("PGDATABASE","mock_coffice"),"readonly_username":self.role,"password":self.role_password,"is_active":True})
        executor=ReadonlyQueryExecutor(self.db,self.cipher)
        metadata=executor.discover_metadata(source["source_code"]); source_rows=[row for row in metadata if row["source_code"]==source["source_code"]]
        self.assertGreater(len(source_rows),0); self.assertLessEqual({row["schema_name"] for row in source_rows},{"ads","dim"})
        first=source_rows[0]
        for name in (first["schema_name"],first["object_name"],first["column_name"]): self.assertRegex(name,r"^[A-Za-z_][A-Za-z0-9_]*$")
        query=f"SELECT t.{first['column_name']} FROM {first['schema_name']}.{first['object_name']} AS t LIMIT 1"
        result=executor.execute(self.context,channel="web",source_code=self.prefix+"_source",sql=query,metadata_rows=metadata)
        self.assertTrue(result.sql_hash)

    def test_removed_tables_are_absent(self):
        with self.db.transaction() as cursor:
            cursor.execute("""SELECT to_regclass('ai.skill') AS skill,to_regclass('ai.skill_version') AS skill_version,
                to_regclass('ai.access_policy') AS access_policy,to_regclass('ai.feishu_identity_binding') AS identity_binding,
                to_regclass('ai.data_catalog') AS data_catalog,to_regclass('ai.catalog_column') AS catalog_column""")
            self.assertEqual(tuple(cursor.fetchone().values()),(None,None,None,None,None,None))
            cursor.execute("""SELECT EXISTS (SELECT 1 FROM information_schema.columns
                WHERE table_schema='ai' AND table_name='data_source' AND column_name='allowed_schemas') AS has_allowed_schemas,
                EXISTS (SELECT 1 FROM iam.permission_resource WHERE resource_code='ai.catalog.manage') AS has_catalog_permission""")
            self.assertEqual(tuple(cursor.fetchone().values()),(False,False))
            cursor.execute("""SELECT COUNT(*) AS old_model_fields FROM information_schema.columns
                WHERE table_schema='ai' AND table_name='provider_config'
                  AND column_name IN ('max_tokens','max_tool_rounds')""")
            self.assertEqual(cursor.fetchone()["old_model_fields"],0)

    def test_conversation_rename_and_soft_delete(self):
        service=AiAnalysisService(self.db,self.cipher,None,None); conversation=service.new_conversation(self.context)
        renamed=service.rename_conversation(self.context,str(conversation["conversation_uuid"]),"月度经营分析")
        self.assertEqual(renamed["title"],"月度经营分析"); self.assertTrue(service.delete_conversation(self.context,str(conversation["conversation_uuid"]))["deleted"])
        with self.db.transaction() as cursor: cursor.execute("DELETE FROM ai.conversation WHERE conversation_uuid=%s",(conversation["conversation_uuid"],))

    def test_failed_turn_is_saved_for_ui_but_excluded_from_next_model_context(self):
        service=AiAnalysisService(self.db,self.cipher,None,None); conversation=service.new_conversation(self.context)
        with self.db.transaction() as cursor:
            cursor.execute("SELECT conversation_id FROM ai.conversation WHERE conversation_uuid=%s",(conversation["conversation_uuid"],)); conversation_id=int(cursor.fetchone()["conversation_id"])
            cursor.execute("INSERT INTO ai.message(conversation_id,role,content) VALUES (%s,'user','上一条失败的分析') RETURNING message_id",(conversation_id,)); message_id=int(cursor.fetchone()["message_id"])
        service._record_failed_turn({"conversation_id":conversation_id},message_id,"failed","数据源选择失败")
        self.assertEqual(service._history(self.context,str(conversation["conversation_uuid"])),[])
        with self.db.transaction() as cursor:
            cursor.execute("SELECT role,status FROM ai.message WHERE conversation_id=%s ORDER BY message_id",(conversation_id,)); rows=cursor.fetchall()
            self.assertEqual([(row["role"],row["status"]) for row in rows],[("user","failed"),("assistant","failed")])
            cursor.execute("DELETE FROM ai.message WHERE conversation_id=%s",(conversation_id,))
            cursor.execute("DELETE FROM ai.conversation WHERE conversation_id=%s",(conversation_id,))

    def test_daily_report_schema_and_uniqueness_exist(self):
        with self.db.transaction() as cursor:
            cursor.execute("SELECT to_regclass('ai.daily_report_run') AS table_name")
            self.assertEqual(cursor.fetchone()["table_name"],"ai.daily_report_run")
            cursor.execute("SELECT daily_report_time,daily_report_timezone,daily_report_chat_ids FROM ai.feishu_app LIMIT 0")

    def test_daily_report_scheduler_is_idempotent(self):
        encrypted=self.cipher.encrypt("test-secret",context=f"feishu:{self.prefix}:app-secret")
        with self.db.transaction() as cursor:
            cursor.execute("""INSERT INTO ai.feishu_app(config_code,config_name,app_id,app_secret_ciphertext,app_secret_nonce,
                is_enabled,daily_report_enabled,daily_report_time,daily_report_timezone,daily_report_chat_ids)
                VALUES (%s,'测试飞书','cli_test',%s,%s,TRUE,TRUE,'00:00','Asia/Shanghai','[\"oc_test\"]'::jsonb)
                RETURNING feishu_app_id""",(self.prefix,self.cipher.encode(encrypted[0]),self.cipher.encode(encrypted[1])))
            app_id=int(cursor.fetchone()["feishu_app_id"])
        service=FeishuService(self.db,self.cipher); submitted=[]
        service.executor.submit=lambda fn,*args,**kwargs: submitted.append((fn,args))
        try:
            now=datetime(2026,8,11,8,0,tzinfo=timezone.utc)
            self.assertEqual(service.run_due_daily_reports(now),1)
            self.assertEqual(service.run_due_daily_reports(now),0)
            self.assertEqual(len(submitted),1)
        finally:
            service.executor.shutdown=lambda **kwargs: None
            service.close()
            with self.db.transaction() as cursor:
                cursor.execute("DELETE FROM ai.daily_report_run WHERE feishu_app_id=%s",(app_id,))
                cursor.execute("DELETE FROM ai.feishu_app WHERE feishu_app_id=%s",(app_id,))

    def test_all_ai_tables_and_columns_have_comments(self):
        with self.db.transaction() as cursor:
            cursor.execute("""SELECT c.relname,a.attname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
                WHERE n.nspname='ai' AND c.relkind='r' AND (obj_description(c.oid,'pg_class') IS NULL OR col_description(c.oid,a.attnum) IS NULL)""")
            self.assertEqual(cursor.fetchall(),[])


if __name__=="__main__":unittest.main()
