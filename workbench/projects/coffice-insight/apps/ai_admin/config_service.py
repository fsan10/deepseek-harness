from __future__ import annotations

from urllib.parse import urlparse

from apps.ai_analysis.deepseek import DeepSeekClient
from .base import audit, code, require, text


class ConfigurationService:
    MODEL_PUBLIC_FIELDS = """provider_config_id,config_code,config_name,provider_code,api_base_url,model_name,
        temperature,request_timeout_seconds,thinking_enabled,is_active,is_default,
        last_test_status,last_tested_at,last_test_error,created_at,updated_at"""
    SOURCE_PUBLIC_FIELDS = """data_source_id,source_code,source_name,source_type,host,port,database_name,
        readonly_username,ssl_mode,connect_timeout_seconds,statement_timeout_ms,lock_timeout_ms,
        idle_transaction_timeout_ms,is_active,description,last_test_status,
        last_tested_at,last_test_error,created_at,updated_at"""

    def __init__(self, database, cipher):
        self.database, self.cipher = database, cipher
        self.deepseek = DeepSeekClient(cipher)

    def models(self, context):
        require(context, "ai.model.manage")
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT {self.MODEL_PUBLIC_FIELDS},api_key_ciphertext,api_key_nonce,api_key_ciphertext IS NOT NULL AS has_api_key FROM ai.provider_config WHERE deleted_at IS NULL ORDER BY is_default DESC,provider_config_id")
            return [self._model_public(dict(row)) for row in cursor.fetchall()]

    def save_model(self, context, payload, model_id=None, *, ip_address="", user_agent=""):
        require(context, "ai.model.manage")
        config_code = code(payload.get("config_code"))
        values = {
            "config_name": text(payload.get("config_name"), "配置名称", maximum=100),
            "api_base_url": text(payload.get("api_base_url"), "API Base URL", maximum=500).rstrip("/"),
            "model_name": text(payload.get("model_name"), "模型名称", maximum=128),
            "temperature": float(payload.get("temperature", .2)),
            "request_timeout_seconds": int(payload.get("request_timeout_seconds", 120)),
            "thinking_enabled": bool(payload.get("thinking_enabled", False)),
            "is_active": bool(payload.get("is_active", False)), "is_default": bool(payload.get("is_default", False)),
        }
        parsed = urlparse(values["api_base_url"])
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("DeepSeek API Base URL必须是HTTPS地址")
        new_key = str(payload.get("api_key") or "").strip()
        with self.database.transaction() as cursor:
            before = None
            if model_id:
                cursor.execute("SELECT * FROM ai.provider_config WHERE provider_config_id=%s AND deleted_at IS NULL FOR UPDATE", (model_id,))
                row = cursor.fetchone()
                if not row: raise ValueError("模型配置不存在")
                before = self._model_public(dict(row))
            if values["is_default"]:
                cursor.execute("UPDATE ai.provider_config SET is_default=FALSE,updated_at=NOW() WHERE deleted_at IS NULL AND provider_config_id<>COALESCE(%s,-1)", (model_id,))
            secret = self.cipher.encrypt(new_key, context=f"provider:{config_code}") if new_key else None
            if model_id:
                cursor.execute(
                    """UPDATE ai.provider_config SET config_code=%s,config_name=%s,api_base_url=%s,model_name=%s,
                       temperature=%s,request_timeout_seconds=%s,thinking_enabled=%s,
                       is_active=%s,is_default=%s,updated_by=%s,updated_at=NOW(),
                       api_key_ciphertext=COALESCE(%s,api_key_ciphertext),api_key_nonce=COALESCE(%s,api_key_nonce)
                       WHERE provider_config_id=%s RETURNING provider_config_id""",
                    (config_code,*values.values(),context.user_id,secret[0] if secret else None,secret[1] if secret else None,model_id),
                )
                saved_id=model_id
            else:
                cursor.execute(
                    """INSERT INTO ai.provider_config
                       (config_code,config_name,api_base_url,model_name,temperature,request_timeout_seconds,
                        thinking_enabled,is_active,is_default,created_by,updated_by,api_key_ciphertext,api_key_nonce)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING provider_config_id""",
                    (config_code,*values.values(),context.user_id,context.user_id,secret[0] if secret else None,secret[1] if secret else None),
                )
                saved_id=int(cursor.fetchone()["provider_config_id"])
            audit(cursor,context=context,action="ai.model.update" if model_id else "ai.model.create",target_type="ai.provider_config",
                  target_id=saved_id,before=before,after={"config_code":config_code,**values,"api_key_changed":bool(new_key)},ip_address=ip_address,user_agent=user_agent)
        return self.model(context,saved_id)

    def model(self, context, model_id):
        require(context,"ai.model.manage")
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT {self.MODEL_PUBLIC_FIELDS},api_key_ciphertext,api_key_nonce,api_key_ciphertext IS NOT NULL AS has_api_key FROM ai.provider_config WHERE provider_config_id=%s AND deleted_at IS NULL",(model_id,))
            row=cursor.fetchone()
            if not row: raise ValueError("模型配置不存在")
            return self._model_public(dict(row))

    def test_model(self, context, model_id, *, ip_address="", user_agent=""):
        require(context,"ai.model.manage")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.provider_config WHERE provider_config_id=%s AND deleted_at IS NULL",(model_id,)); row=cursor.fetchone()
        if not row: raise ValueError("模型配置不存在")
        status,error,result="success",None,None
        try: result=self.deepseek.test(dict(row))
        except Exception as exc: status,error="failed",str(exc)[:500]
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.provider_config SET last_test_status=%s,last_tested_at=NOW(),last_test_error=%s WHERE provider_config_id=%s",(status,error,model_id))
            audit(cursor,context=context,action="ai.model.test",target_type="ai.provider_config",target_id=model_id,after={"status":status,"error":error},ip_address=ip_address,user_agent=user_agent)
        if error: raise ValueError(error)
        return result

    def toggle_model(self,context,model_id,*,ip_address="",user_agent=""):
        require(context,"ai.model.manage")
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.provider_config SET is_active=NOT is_active,updated_by=%s,updated_at=NOW() WHERE provider_config_id=%s AND deleted_at IS NULL RETURNING config_code,is_active",(context.user_id,model_id)); row=cursor.fetchone()
            if not row: raise ValueError("模型配置不存在")
            audit(cursor,context=context,action="ai.model.toggle",target_type="ai.provider_config",target_id=model_id,after={"config_code":row["config_code"],"is_active":row["is_active"]},ip_address=ip_address,user_agent=user_agent)
        return self.model(context,model_id)

    def delete_model(self,context,model_id,*,ip_address="",user_agent=""):
        require(context,"ai.model.manage")
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.provider_config SET deleted_at=NOW(),is_active=FALSE,is_default=FALSE,updated_by=%s,updated_at=NOW() WHERE provider_config_id=%s AND deleted_at IS NULL RETURNING config_code",(context.user_id,model_id)); row=cursor.fetchone()
            if not row: raise ValueError("模型配置不存在")
            audit(cursor,context=context,action="ai.model.delete",target_type="ai.provider_config",target_id=model_id,before={"config_code":row["config_code"]},ip_address=ip_address,user_agent=user_agent)
        return {"deleted":True}

    def sources(self, context):
        require(context,"ai.datasource.manage")
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT {self.SOURCE_PUBLIC_FIELDS},TRUE AS has_password FROM ai.data_source WHERE deleted_at IS NULL ORDER BY data_source_id")
            return [dict(row) for row in cursor.fetchall()]

    def source(self, context, source_id):
        require(context,"ai.datasource.manage")
        with self.database.transaction() as cursor:
            cursor.execute(f"SELECT {self.SOURCE_PUBLIC_FIELDS},TRUE AS has_password FROM ai.data_source WHERE data_source_id=%s AND deleted_at IS NULL",(source_id,)); row=cursor.fetchone()
            if not row: raise ValueError("数据源不存在")
            return dict(row)

    def save_source(self, context, payload, source_id=None, *, ip_address="", user_agent=""):
        require(context,"ai.datasource.manage")
        source_code=code(payload.get("source_code"),"数据源编码")
        fields=(text(payload.get("source_name"),"数据源名称",maximum=100),text(payload.get("host"),"主机",maximum=255),
                int(payload.get("port",5432)),text(payload.get("database_name"),"数据库名",maximum=128),
                text(payload.get("readonly_username"),"只读用户名",maximum=128),str(payload.get("ssl_mode") or "prefer"),
                int(payload.get("connect_timeout_seconds",10)),int(payload.get("statement_timeout_ms",15000)),
                int(payload.get("lock_timeout_ms",2000)),int(payload.get("idle_transaction_timeout_ms",15000)),
                bool(payload.get("is_active",True)),
                text(payload.get("description"),"描述",maximum=1000,required=False))
        password=str(payload.get("password") or "")
        with self.database.transaction() as cursor:
            before=None
            if source_id:
                cursor.execute("SELECT * FROM ai.data_source WHERE data_source_id=%s AND deleted_at IS NULL FOR UPDATE",(source_id,)); old=cursor.fetchone()
                if not old: raise ValueError("数据源不存在")
                before={k:v for k,v in dict(old).items() if "password" not in k}
            elif not password: raise ValueError("新数据源必须填写只读密码")
            secret=self.cipher.encrypt(password,context=f"data-source:{source_code}") if password else None
            if source_id:
                cursor.execute("""UPDATE ai.data_source SET source_code=%s,source_name=%s,host=%s,port=%s,database_name=%s,
                    readonly_username=%s,ssl_mode=%s,connect_timeout_seconds=%s,statement_timeout_ms=%s,lock_timeout_ms=%s,
                    idle_transaction_timeout_ms=%s,is_active=%s,description=%s,
                    password_ciphertext=COALESCE(%s,password_ciphertext),password_nonce=COALESCE(%s,password_nonce),updated_by=%s,updated_at=NOW()
                    WHERE data_source_id=%s""",(source_code,*fields,secret[0] if secret else None,secret[1] if secret else None,context.user_id,source_id)); saved_id=source_id
            else:
                cursor.execute("""INSERT INTO ai.data_source(source_code,source_name,host,port,database_name,readonly_username,ssl_mode,
                    connect_timeout_seconds,statement_timeout_ms,lock_timeout_ms,idle_transaction_timeout_ms,
                    is_active,description,password_ciphertext,password_nonce,created_by,updated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING data_source_id""",
                    (source_code,*fields,secret[0],secret[1],context.user_id,context.user_id)); saved_id=int(cursor.fetchone()["data_source_id"])
            audit(cursor,context=context,action="ai.datasource.update" if source_id else "ai.datasource.create",target_type="ai.data_source",target_id=saved_id,before=before,after={"source_code":source_code,"password_changed":bool(password)},ip_address=ip_address,user_agent=user_agent)
        return self.source(context,saved_id)

    def test_source(self, context, source_id, *, ip_address="", user_agent=""):
        require(context,"ai.datasource.manage")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.data_source WHERE data_source_id=%s AND deleted_at IS NULL",(source_id,)); source=cursor.fetchone()
        if not source: raise ValueError("数据源不存在")
        error=None
        try:
            import psycopg2
            password=self.cipher.decrypt(source["password_ciphertext"],source["password_nonce"],context=f"data-source:{source['source_code']}")
            connection=psycopg2.connect(host=source["host"],port=source["port"],dbname=source["database_name"],user=source["readonly_username"],password=password,sslmode=source["ssl_mode"],connect_timeout=source["connect_timeout_seconds"])
            connection.set_session(readonly=True); cursor=connection.cursor(); cursor.execute("SELECT current_database(), current_user, current_setting('transaction_read_only')"); result=cursor.fetchone(); connection.rollback(); connection.close()
            if result[2] != "on": raise ValueError("连接未处于只读事务")
        except Exception as exc: error=f"连接失败：{type(exc).__name__}"[:500]
        status="failed" if error else "success"
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.data_source SET last_test_status=%s,last_tested_at=NOW(),last_test_error=%s WHERE data_source_id=%s",(status,error,source_id))
            audit(cursor,context=context,action="ai.datasource.test",target_type="ai.data_source",target_id=source_id,after={"status":status,"error":error},ip_address=ip_address,user_agent=user_agent)
        if error: raise ValueError(error)
        return {"ok":True,"database":result[0],"user":result[1],"transaction_read_only":result[2]}

    def toggle_source(self,context,source_id,*,ip_address="",user_agent=""):
        require(context,"ai.datasource.manage")
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.data_source SET is_active=NOT is_active,updated_by=%s,updated_at=NOW() WHERE data_source_id=%s AND deleted_at IS NULL RETURNING source_code,is_active",(context.user_id,source_id)); row=cursor.fetchone()
            if not row: raise ValueError("数据源不存在")
            audit(cursor,context=context,action="ai.datasource.toggle",target_type="ai.data_source",target_id=source_id,after={"source_code":row["source_code"],"is_active":row["is_active"]},ip_address=ip_address,user_agent=user_agent)
        return self.source(context,source_id)

    def delete_source(self,context,source_id,*,ip_address="",user_agent=""):
        require(context,"ai.datasource.manage")
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.data_source SET deleted_at=NOW(),is_active=FALSE,updated_by=%s,updated_at=NOW() WHERE data_source_id=%s AND deleted_at IS NULL RETURNING source_code",(context.user_id,source_id)); row=cursor.fetchone()
            if not row: raise ValueError("数据源不存在")
            audit(cursor,context=context,action="ai.datasource.delete",target_type="ai.data_source",target_id=source_id,before={"source_code":row["source_code"]},ip_address=ip_address,user_agent=user_agent)
        return {"deleted":True}

    def _model_public(self,row):
        ciphertext=row.pop("api_key_ciphertext",None); nonce=row.pop("api_key_nonce",None); has_key=row.pop("has_api_key",bool(ciphertext))
        if has_key:
            try: row["api_key_masked"]=self.cipher.mask(self.cipher.decrypt(ciphertext,nonce,context=f"provider:{row['config_code']}"))
            except Exception: row["api_key_masked"]="已配置（****）"
        else: row["api_key_masked"]="未配置"
        return row
