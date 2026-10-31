from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from apps.ai_analysis.crypto import SecretCipher
from apps.ai_analysis.query_executor import ReadonlyQueryExecutor
from apps.ai_analysis.service import AiAnalysisService
from apps.feishu_ai.service import FeishuService
from apps.identity_access.module import ModuleResponse

from .config_service import ConfigurationService
from .prompt_service import PromptService


APP_DIR=Path(__file__).resolve().parent
PROJECT_ROOT=APP_DIR.parents[1]
SQL_FILES=[PROJECT_ROOT/f"sql/ai/{name}" for name in (
    "374_ai_configuration_catalog_postgres.sql","375_ai_skill_permission_postgres.sql",
    "376_ai_conversation_feishu_audit_postgres.sql","377_seed_ai_permissions_defaults_postgres.sql",
    "378_simplify_ai_daily_report_postgres.sql","379_remove_ai_catalog_postgres.sql",
    "380_simplify_model_output_config_postgres.sql","381_optimize_ai_daily_report_postgres.sql",
    "382_ai_verification_relay_postgres.sql","383_ai_verification_challenge_type_postgres.sql",
    "433_ai_sms_forwarder_fallback_postgres.sql", "456_verification_answer_notice_postgres.sql")]


class AiManagementModule:
    def __init__(self,database,auth_service):
        self.database=database; self.cipher=SecretCipher()
        self.config=ConfigurationService(database,self.cipher)
        self.prompts=PromptService(database)
        self.query=ReadonlyQueryExecutor(database,self.cipher)
        self.analysis=AiAnalysisService(database,self.cipher,self.prompts,self.query)
        self.feishu=FeishuService(database,self.cipher); self.feishu.bind_analysis(self.analysis)
        self.web_static=PROJECT_ROOT/"apps/ai_web/static"; self.admin_static=APP_DIR/"static"

    def migrate(self):
        applied=[]
        with self.database.transaction() as cursor:
            for path in SQL_FILES: cursor.execute(path.read_text(encoding="utf-8")); applied.append(str(path.relative_to(PROJECT_ROOT)))
        return applied
    def close(self): self.feishu.close()

    def static_file(self,path):
        if path.startswith("/ai-assets/"): root,relative=self.web_static,path.removeprefix("/ai-assets/")
        elif path.startswith("/ai-admin-assets/"): root,relative=self.admin_static,path.removeprefix("/ai-admin-assets/")
        elif path.startswith("/ai-admin"): root,relative=self.admin_static,path.removeprefix("/ai-admin").lstrip("/") or "index.html"
        elif path.startswith("/ai"): root,relative=self.web_static,path.removeprefix("/ai").lstrip("/") or "index.html"
        else:return None
        target=(root/unquote(relative)).resolve(); return target if target.is_file() and (target==root.resolve() or root.resolve() in target.parents) else None

    def stream_response(self,handler,context,payload):
        handler.send_response(200); handler.send_header("Content-Type","text/event-stream; charset=utf-8"); handler.send_header("Cache-Control","no-cache, no-transform"); handler.send_header("Connection","close"); handler.send_header("X-Accel-Buffering","no"); handler.end_headers()
        try:
            for event,data in self.analysis.stream(context,payload,channel="web"):
                chunk=f"event: {event}\ndata: {json.dumps(data,ensure_ascii=False,default=str)}\n\n".encode("utf-8")
                try: handler.wfile.write(chunk); handler.wfile.flush()
                except (BrokenPipeError,ConnectionResetError): break
        finally:
            handler.close_connection=True

    def dispatch(self,method,path,query,payload,*,context,ip_address="",user_agent=""):
        payload=payload or {}; kwargs={"ip_address":ip_address,"user_agent":user_agent}
        if not (path.startswith("/api/ai/") or path.startswith("/api/automation/verification/")):return None
        if path=="/api/ai/conversations" and method=="GET":return ModuleResponse(self.analysis.conversations(context))
        if path=="/api/ai/conversations" and method=="POST":return ModuleResponse(self.analysis.new_conversation(context),201)
        if path=="/api/ai/prompts" and method=="GET":return ModuleResponse(self.analysis.prompt_catalog(context))
        if path=="/api/ai/messages" and method=="GET":return ModuleResponse(self.analysis.messages(context,query.get("conversation_uuid","")))
        if path=="/api/ai/stop" and method=="POST":return ModuleResponse(self.analysis.stop(context,payload.get("generation_id")))
        match=re.fullmatch(r"/api/ai/conversations/([0-9a-fA-F-]+)",path)
        if match and method=="PUT":return ModuleResponse(self.analysis.rename_conversation(context,match.group(1),payload.get("title")))
        if match and method=="DELETE":return ModuleResponse(self.analysis.delete_conversation(context,match.group(1)))

        if path=="/api/ai/admin/models" and method=="GET":return ModuleResponse(self.config.models(context))
        if path=="/api/ai/admin/models" and method=="POST":return ModuleResponse(self.config.save_model(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/models/(\d+)/status",path)
        if match and method=="PUT":return ModuleResponse(self.config.toggle_model(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/models/(\d+)(?:/(test))?",path)
        if match and method=="PUT":return ModuleResponse(self.config.save_model(context,payload,int(match.group(1)),**kwargs))
        if match and method=="POST" and match.group(2):return ModuleResponse(self.config.test_model(context,int(match.group(1)),**kwargs))
        if match and method=="DELETE":return ModuleResponse(self.config.delete_model(context,int(match.group(1)),**kwargs))

        if path=="/api/ai/admin/sources" and method=="GET":return ModuleResponse(self.config.sources(context))
        if path=="/api/ai/admin/sources" and method=="POST":return ModuleResponse(self.config.save_source(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/sources/(\d+)/status",path)
        if match and method=="PUT":return ModuleResponse(self.config.toggle_source(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/sources/(\d+)(?:/(test))?",path)
        if match and method=="PUT":return ModuleResponse(self.config.save_source(context,payload,int(match.group(1)),**kwargs))
        if match and method=="POST" and match.group(2)=="test":return ModuleResponse(self.config.test_source(context,int(match.group(1)),**kwargs))
        if match and method=="DELETE":return ModuleResponse(self.config.delete_source(context,int(match.group(1)),**kwargs))

        if path=="/api/ai/admin/prompts" and method=="GET":return ModuleResponse(self.prompts.prompts(context,admin=True))
        if path=="/api/ai/admin/prompts" and method=="POST":return ModuleResponse(self.prompts.save_prompt(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/prompts/(\d+)/status",path)
        if match and method=="PUT":return ModuleResponse(self.prompts.toggle_prompt(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/prompts/(\d+)",path)
        if match and method=="PUT":return ModuleResponse(self.prompts.save_prompt(context,payload,int(match.group(1)),**kwargs))
        if match and method=="DELETE":return ModuleResponse(self.prompts.delete_prompt(context,int(match.group(1)),**kwargs))

        if path=="/api/ai/admin/feishu-apps" and method=="GET":return ModuleResponse(self.feishu.apps(context))
        if path=="/api/ai/admin/feishu-prompt-options" and method=="GET":return ModuleResponse(self.feishu.prompt_options(context))
        if path=="/api/ai/admin/feishu-apps" and method=="POST":return ModuleResponse(self.feishu.save_app(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/feishu-apps/(\d+)/status",path)
        if match and method=="PUT":return ModuleResponse(self.feishu.toggle_app(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/feishu-apps/(\d+)(?:/(test))?",path)
        if match and method=="PUT":return ModuleResponse(self.feishu.save_app(context,payload,int(match.group(1)),**kwargs))
        if match and method=="POST" and match.group(2):return ModuleResponse(self.feishu.test_app(context,int(match.group(1)),**kwargs))
        if path=="/api/ai/admin/verification-relays" and method=="GET":return ModuleResponse(self.feishu.verification_relays(context))
        if path=="/api/ai/admin/verification-relays" and method=="POST":return ModuleResponse(self.feishu.save_verification_relay(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/verification-relays/(\d+)/status",path)
        if match and method=="PUT":return ModuleResponse(self.feishu.toggle_verification_relay(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/verification-relays/(\d+)(?:/(test))?",path)
        if match and method=="PUT":return ModuleResponse(self.feishu.save_verification_relay(context,payload,int(match.group(1)),**kwargs))
        if match and method=="POST" and match.group(2):return ModuleResponse(self.feishu.test_verification_relay(context,int(match.group(1)),**kwargs))
        match=re.fullmatch(r"/api/ai/admin/verification-relays/(\d+)",path)
        if match and method=="DELETE":return ModuleResponse(self.feishu.delete_verification_relay(context,int(match.group(1)),**kwargs))
        if path=="/api/ai/admin/sms-forwarders" and method=="GET":return ModuleResponse(self.feishu.sms.configs(context))
        if path=="/api/ai/admin/sms-forwarders" and method=="POST":return ModuleResponse(self.feishu.sms.save(context,payload,**kwargs),201)
        match=re.fullmatch(r"/api/ai/admin/sms-forwarders/(\d+)(?:/(test|status))?",path)
        if match and method=="PUT" and match.group(2)=="status":return ModuleResponse(self.feishu.sms.toggle(context,int(match.group(1)),**kwargs))
        if match and method=="PUT" and not match.group(2):return ModuleResponse(self.feishu.sms.save(context,payload,int(match.group(1)),**kwargs))
        if match and method=="POST" and match.group(2)=="test":return ModuleResponse(self.feishu.sms.test(context,int(match.group(1)),**kwargs))
        if match and method=="DELETE" and not match.group(2):return ModuleResponse(self.feishu.sms.delete(context,int(match.group(1)),**kwargs))
        if path=="/api/automation/verification/notices" and method=="POST":return ModuleResponse(self.feishu.send_automation_notice(payload),201)
        if path=="/api/automation/verification/challenges" and method=="POST":return ModuleResponse(self.feishu.create_verification_challenge(payload),201)
        match=re.fullmatch(r"/api/automation/verification/challenges/([0-9a-fA-F-]{36})",path)
        if match and method=="GET":return ModuleResponse(self.feishu.get_verification_challenge(match.group(1)))
        match=re.fullmatch(r"/api/automation/verification/challenges/([0-9a-fA-F-]{36})/(reject|resume|cancel)",path)
        if match and method=="POST":return ModuleResponse(getattr(self.feishu.sms,match.group(2))(match.group(1)))
        if path=="/api/ai/admin/audit" and method=="GET":return ModuleResponse(self.audit(context,query))
        return ModuleResponse(None,404)

    def audit(self,context,query):
        from .base import require
        require(context,"ai.audit.view"); keyword=str(query.get("keyword") or "")
        date_from=str(query.get("date_from") or "").strip(); date_to=str(query.get("date_to") or "").strip()
        for value,label in ((date_from,"开始日期"),(date_to,"结束日期")):
            if value:
                try: date.fromisoformat(value)
                except ValueError as exc: raise ValueError(f"{label}格式必须为YYYY-MM-DD") from exc
        query_dates="".join([" AND (q.created_at AT TIME ZONE 'Asia/Shanghai')::date >= %s" if date_from else "", " AND (q.created_at AT TIME ZONE 'Asia/Shanghai')::date <= %s" if date_to else ""])
        conversation_dates="".join([" AND (c.updated_at AT TIME ZONE 'Asia/Shanghai')::date >= %s" if date_from else "", " AND (c.updated_at AT TIME ZONE 'Asia/Shanghai')::date <= %s" if date_to else ""])
        feishu_dates="".join([" AND (f.occurred_at AT TIME ZONE 'Asia/Shanghai')::date >= %s" if date_from else "", " AND (f.occurred_at AT TIME ZONE 'Asia/Shanghai')::date <= %s" if date_to else ""])
        date_params=tuple(value for value in (date_from,date_to) if value)
        def page(name):
            try: value=int(query.get(name) or 1)
            except ValueError: value=1
            return max(1,value)
        def page_size(name):
            try: value=int(query.get(name) or 10)
            except ValueError: value=10
            return min(max(value,5),100)
        cp,cps,qp,qps=page("conversation_page"),page_size("conversation_page_size"),page("query_page"),page_size("query_page_size")
        fp,fps=page("feishu_page"),page_size("feishu_page_size")
        with self.database.transaction() as cursor:
            cursor.execute(f"""SELECT COUNT(*) AS total FROM ai.query_audit q LEFT JOIN iam.user_account u ON u.user_id=q.user_id
                JOIN ai.data_source s ON s.data_source_id=q.data_source_id
                WHERE (%s='' OR COALESCE(u.username,q.external_actor_id,'') ILIKE %s OR q.sql_hash ILIKE %s){query_dates}""",(keyword,f"%{keyword}%",f"%{keyword}%",*date_params))
            query_total=int(cursor.fetchone()["total"])
            cursor.execute(f"""SELECT q.*,COALESCE(u.username,q.external_actor_id,'system') AS username,
                COALESCE(u.display_name,q.external_actor_id,'系统任务') AS display_name,d.department_name,s.source_name FROM ai.query_audit q
                LEFT JOIN iam.user_account u ON u.user_id=q.user_id LEFT JOIN iam.department d ON d.department_id=q.department_id
                JOIN ai.data_source s ON s.data_source_id=q.data_source_id WHERE (%s='' OR COALESCE(u.username,q.external_actor_id,'') ILIKE %s OR q.sql_hash ILIKE %s){query_dates}
                ORDER BY q.created_at DESC LIMIT %s OFFSET %s""",(keyword,f"%{keyword}%",f"%{keyword}%",*date_params,qps,(qp-1)*qps)); queries=[dict(row) for row in cursor.fetchall()]
            cursor.execute(f"""SELECT COUNT(*) AS total FROM ai.conversation c LEFT JOIN iam.user_account u ON u.user_id=c.user_id
                WHERE (%s='' OR COALESCE(u.username,c.external_actor_id,'') ILIKE %s OR c.title ILIKE %s){conversation_dates}""",(keyword,f"%{keyword}%",f"%{keyword}%",*date_params))
            conversation_total=int(cursor.fetchone()["total"])
            cursor.execute(f"""SELECT c.conversation_uuid,c.user_id,COALESCE(u.username,c.external_actor_id,'system') AS username,
                COALESCE(u.display_name,c.external_actor_id,'系统任务') AS display_name,c.channel,c.title,c.status,c.created_at,c.updated_at,
                COUNT(m.message_id) AS message_count FROM ai.conversation c LEFT JOIN iam.user_account u ON u.user_id=c.user_id
                LEFT JOIN ai.message m ON m.conversation_id=c.conversation_id
                 WHERE (%s='' OR COALESCE(u.username,c.external_actor_id,'') ILIKE %s OR c.title ILIKE %s){conversation_dates}
                 GROUP BY c.conversation_id,u.username,u.display_name ORDER BY c.updated_at DESC LIMIT %s OFFSET %s""",(keyword,f"%{keyword}%",f"%{keyword}%",*date_params,cps,(cp-1)*cps)); conversations=[dict(row) for row in cursor.fetchall()]
            pattern=f"%{keyword}%"
            feishu_union="""SELECT e.event_id AS record_id,'message' AS record_type,a.config_name,e.chat_id,
                    e.processing_status AS status,e.error_category,e.received_at AS occurred_at
                FROM ai.feishu_event_dedup e JOIN ai.feishu_app a ON a.feishu_app_id=e.feishu_app_id
                UNION ALL
                SELECT r.daily_report_run_id::text,'daily_report',a.config_name,r.chat_id,r.status,r.error_category,r.started_at
                FROM ai.daily_report_run r JOIN ai.feishu_app a ON a.feishu_app_id=r.feishu_app_id"""
            cursor.execute(f"""SELECT COUNT(*) AS total FROM ({feishu_union}) f
                WHERE (%s='' OR f.config_name ILIKE %s OR COALESCE(f.chat_id,'') ILIKE %s OR f.status ILIKE %s){feishu_dates}""",
                (keyword,pattern,pattern,pattern,*date_params)); feishu_total=int(cursor.fetchone()["total"])
            cursor.execute(f"""SELECT * FROM ({feishu_union}) f
                 WHERE (%s='' OR f.config_name ILIKE %s OR COALESCE(f.chat_id,'') ILIKE %s OR f.status ILIKE %s){feishu_dates}
                 ORDER BY f.occurred_at DESC LIMIT %s OFFSET %s""",
                 (keyword,pattern,pattern,pattern,*date_params,fps,(fp-1)*fps)); feishu=[dict(row) for row in cursor.fetchall()]
        def wrap(items,total,current,size): return {"items":items,"total":total,"page":current,"page_size":size,"pages":max(1,-(-total//size))}
        return {"queries":wrap(queries,query_total,qp,qps),"conversations":wrap(conversations,conversation_total,cp,cps),
                "feishu":wrap(feishu,feishu_total,fp,fps)}
