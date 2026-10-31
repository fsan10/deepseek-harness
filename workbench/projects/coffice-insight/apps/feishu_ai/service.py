from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from apps.identity_access.authorization import AuthContext
from apps.ai_admin.base import audit, code, require, text
from .long_connection import FeishuLongConnectionManager
from .sms import normalize_event, visible_text
from .sms_relay import SmsRelay


class FeishuService:
    def __init__(self, database, cipher):
        self.database, self.cipher = database, cipher
        self.analysis = None
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="feishu-ai")
        self._token_cache = {}
        self._lock = threading.Lock()
        self._scheduler_stop = threading.Event()
        self._scheduler_thread = None
        self.long_connections = FeishuLongConnectionManager(self)
        self.sms = SmsRelay(self)

    def bind_analysis(self, analysis):
        self.analysis = analysis

    def close(self):
        self._scheduler_stop.set()
        self.sms.close()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=3)
        self.long_connections.close()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def start_long_connections(self):
        self._start_scheduler()
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.feishu_app WHERE is_enabled AND connection_mode='long_connection' AND deleted_at IS NULL")
            configs = [dict(row) for row in cursor.fetchall()]
        if configs:
            self.long_connections.start(configs)

    def start_daily_report_scheduler(self):
        self._start_scheduler()

    def _start_scheduler(self):
        self.sms.start()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._scheduler_stop.clear()
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, name="feishu-daily-report", daemon=True)
        self._scheduler_thread.start()

    def _scheduler_loop(self):
        while not self._scheduler_stop.wait(30):
            try:
                self.cleanup_verification_challenges()
                self.dispatch_automation_notifications()
                self.run_due_daily_reports()
            except Exception:
                # Individual runs are audited; scheduler must stay alive without leaking credentials.
                pass

    @staticmethod
    def _automation_run_notification_message(relay, run):
        status = str(run.get("status") or "")
        labels = {
            "failed": "失败",
            "needs_human": "等待人工",
            "success_with_warnings": "成功（有提醒）",
            "success": "成功",
            "no_data": "无数据",
            "cancelled": "已取消",
            "stalled": "长时间运行",
        }
        title = f"自动化任务 · {labels.get(status, status)}"
        lines = [
            f"任务：{run.get('job_name') or '自动化任务'}",
            f"状态：{labels.get(status, status)}",
            f"业务日期：{run.get('business_date') or '—'}",
            f"Run：{str(run.get('automation_run_id') or '')[:8]}",
        ]
        if run.get("platform_name"):
            lines.append(f"平台：{run['platform_name']}")
        if run.get("shop_name"):
            lines.append(f"店铺：{run['shop_name']}")
        if run.get("flow_version"):
            lines.append(f"Flow Version：v{run['flow_version']}")
        if run.get("resume_count"):
            lines.append(f"恢复次数：{run['resume_count']}")
        message = run.get("error_message") or run.get("warning_message")
        if message:
            lines.append(f"信息：{str(message)[:500]}")
        if status == "needs_human":
            lines.append("负责人处理完成后，已回复的 Challenge 会自动恢复同一个 Run；无 Challenge 的滑块类任务可在自动化工作台手工点击“继续”。")
        content = [{"tag": "text", "text": "\n".join(lines)}]
        if status in {"failed", "needs_human", "success_with_warnings"}:
            for open_id in list(relay.get("mention_open_ids") or []):
                content.append({"tag": "at", "user_id": str(open_id), "user_name": "负责人"})
        return {"zh_cn": {"title": title, "content": [content]}}

    def dispatch_automation_notifications(self, limit=20):
        """Deliver Automation outbox events through existing Feishu relay configs.

        The Automation domain only writes an outbox row.  Credentials remain in
        FeishuService, so Worker/Scheduler never need Feishu secrets.
        """

        limit = max(1, min(int(limit), 100))
        with self.database.transaction() as cursor:
            cursor.execute("SELECT to_regclass('ops.automation_notification_outbox') AS outbox")
            if not cursor.fetchone()["outbox"]:
                return {"processed": 0, "sent": 0, "failed": 0}
            cursor.execute(
                """SELECT enabled,event_types FROM ops.automation_notification_policy
                   WHERE policy_code='default'"""
            )
            policy = cursor.fetchone()
            if not policy or not policy["enabled"]:
                return {"processed": 0, "sent": 0, "failed": 0}
            event_types = [str(item) for item in (policy.get("event_types") or [])]
            if not event_types:
                return {"processed": 0, "sent": 0, "failed": 0}
            cursor.execute(
                """SELECT notification_id FROM ops.automation_notification_outbox
                   WHERE status='pending' AND next_attempt_at<=NOW()
                     AND event_type=ANY(%s)
                   ORDER BY notification_id
                   FOR UPDATE SKIP LOCKED LIMIT %s""",
                (event_types, limit),
            )
            ids = [int(row["notification_id"]) for row in cursor.fetchall()]
            leased = []
            for notification_id in ids:
                cursor.execute(
                    """UPDATE ops.automation_notification_outbox
                       SET attempt_count=attempt_count+1,next_attempt_at=NOW()+INTERVAL '5 minutes'
                       WHERE notification_id=%s AND status='pending'
                       RETURNING notification_id,automation_run_id,event_type,attempt_count""",
                    (notification_id,),
                )
                row = cursor.fetchone()
                if row:
                    leased.append(dict(row))

        sent = 0
        failed = 0
        for item in leased:
            error = None
            try:
                with self.database.transaction() as cursor:
                    cursor.execute(
                        """SELECT r.automation_run_id,r.status,r.business_date,r.error_message,r.warning_message,r.resume_count,
                                  COALESCE(fv.flow_name,f.flow_name,j.job_name) AS job_name,
                                  COALESCE(fv.version,f.version) AS flow_version,
                                  latest.platform_name,latest.company_name,latest.shop_name
                           FROM ops.automation_run r
                           JOIN ops.automation_job j ON j.job_id=r.job_id
                           LEFT JOIN ops.automation_flow f ON f.flow_id=r.flow_id
                           LEFT JOIN ops.automation_flow_version fv ON fv.flow_version_id=r.flow_version_id
                           LEFT JOIN LATERAL (
                               SELECT platform_name,company_name,shop_name
                               FROM ops.automation_step_run s
                               WHERE s.automation_run_id=r.automation_run_id
                               ORDER BY sequence_no DESC LIMIT 1
                           ) latest ON TRUE
                           WHERE r.automation_run_id=%s""",
                        (str(item["automation_run_id"]),),
                    )
                    run = cursor.fetchone()
                if not run:
                    raise ValueError("Automation Run 不存在")
                run = dict(run)
                relay = self._select_verification_relay(str(run.get("platform_name") or ""))
                if not relay:
                    raise ValueError("没有匹配的飞书转发配置；请配置平台范围或一个全局 relay")
                app = self._app(relay["feishu_app_id"])
                self._send_post_to_chat(
                    app,
                    relay["chat_id"],
                    self._automation_run_notification_message(relay, run),
                )
            except Exception as exc:
                error = self._safe_error(exc)[:500]
            with self.database.transaction() as cursor:
                if error:
                    cursor.execute(
                        """UPDATE ops.automation_notification_outbox
                           SET status=CASE WHEN attempt_count>=5 THEN 'failed' ELSE 'pending' END,
                               last_error=%s,
                               next_attempt_at=NOW()+(LEAST(60,attempt_count*5)*INTERVAL '1 minute')
                           WHERE notification_id=%s""",
                        (error, item["notification_id"]),
                    )
                    failed += 1
                else:
                    cursor.execute(
                        """UPDATE ops.automation_notification_outbox
                           SET status='sent',sent_at=NOW(),last_error=NULL
                           WHERE notification_id=%s""",
                        (item["notification_id"],),
                    )
                    sent += 1
        return {"processed": len(leased), "sent": sent, "failed": failed}

    def cleanup_verification_challenges(self):
        """使过期请求失效并清理超过保留期的验证码密文。"""

        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.verification_challenge SET status='expired' WHERE status='pending' AND expires_at<=NOW()")
            cursor.execute("UPDATE ai.verification_challenge SET answer_ciphertext=NULL,answer_nonce=NULL WHERE auto_until IS NOT NULL AND expires_at<=NOW() AND answer_ciphertext IS NOT NULL")
            cursor.execute("DELETE FROM ai.verification_challenge WHERE retention_until<NOW()")

    def apps(self, context):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT feishu_app_id,config_code,config_name,app_id,connection_mode,is_enabled,group_require_mention,
                allow_private_chat,allowed_chat_ids,default_prompt_template_id,daily_report_enabled,daily_report_time,
                daily_report_timezone,daily_report_chat_ids,daily_report_prompt_template_id,last_daily_report_date,
                last_test_status,last_tested_at,last_error_summary,created_at,updated_at,
                verification_token_ciphertext IS NOT NULL AS has_verification_token,
                encrypt_key_ciphertext IS NOT NULL AS has_encrypt_key
                FROM ai.feishu_app WHERE deleted_at IS NULL ORDER BY feishu_app_id""")
            rows = []
            for row in cursor.fetchall():
                item = dict(row)
                item.update({"app_secret_masked":"已配置（****）",
                             "verification_token_masked":"已配置（****）" if item.pop("has_verification_token") else "未配置",
                             "encrypt_key_masked":"已配置（****）" if item.pop("has_encrypt_key") else "未配置"})
                if item.get("daily_report_time") is not None:
                    item["daily_report_time"] = str(item["daily_report_time"])[:5]
                item["runtime"] = self.long_connections.status(item["config_code"])
                rows.append(item)
            return rows

    def prompt_options(self, context):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT prompt_template_id,template_code,template_name,is_default
                FROM ai.prompt_template WHERE is_enabled AND feishu_available AND deleted_at IS NULL
                ORDER BY is_default DESC,sort_order,prompt_template_id""")
            return [dict(row) for row in cursor.fetchall()]

    def save_app(self, context, payload, app_id=None, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        config_code = code(payload.get("config_code"))
        connection_mode = str(payload.get("connection_mode") or "long_connection")
        if connection_mode not in {"long_connection", "webhook"}:
            raise ValueError("连接模式无效")
        timezone = str(payload.get("daily_report_timezone") or "Asia/Shanghai")
        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise ValueError("每日报告时区无效") from exc
        report_time = str(payload.get("daily_report_time") or "09:00")
        try:
            datetime.strptime(report_time, "%H:%M")
        except ValueError as exc:
            raise ValueError("每日报告时间必须为 HH:MM") from exc
        app_secret = str(payload.get("app_secret") or "")
        verification = str(payload.get("verification_token") or "")
        encrypt_key = str(payload.get("encrypt_key") or "")
        allowed = payload.get("allowed_chat_ids") or []
        report_chats = payload.get("daily_report_chat_ids") or []
        allowed = self._normalize_chat_ids(allowed, "响应群聊白名单")
        report_chats = self._normalize_chat_ids(report_chats, "报告接收群聊 ID")
        prompt_ids = [value for value in (payload.get("default_prompt_template_id"),
                                           payload.get("daily_report_prompt_template_id")) if value]
        if bool(payload.get("daily_report_enabled")) and not report_chats:
            raise ValueError("启用每日报告时至少填写一个接收群聊 ID")
        with self.database.transaction() as cursor:
            if prompt_ids:
                cursor.execute("""SELECT COUNT(*) AS total FROM ai.prompt_template
                    WHERE prompt_template_id=ANY(%s) AND is_enabled AND feishu_available AND deleted_at IS NULL""",
                    (prompt_ids,))
                if int(cursor.fetchone()["total"]) != len(set(prompt_ids)):
                    raise ValueError("所选飞书提示词不存在、已停用或未开放给飞书")
            old = None
            if app_id:
                cursor.execute("SELECT * FROM ai.feishu_app WHERE feishu_app_id=%s AND deleted_at IS NULL FOR UPDATE", (app_id,))
                old = cursor.fetchone()
                if not old:
                    raise ValueError("飞书配置不存在")
            elif not app_secret:
                raise ValueError("新配置必须填写App Secret")

            def secret_values(value, label):
                if not value:
                    return None, None
                encrypted = self.cipher.encrypt(value, context=f"feishu:{config_code}:{label}")
                return self.cipher.encode(encrypted[0]), self.cipher.encode(encrypted[1])

            app_pair = secret_values(app_secret, "app-secret")
            verify_pair = secret_values(verification, "verification-token")
            encrypt_pair = secret_values(encrypt_key, "encrypt-key")
            values = (config_code, text(payload.get("config_name"), "配置名称", maximum=120),
                      text(payload.get("app_id"), "App ID", maximum=160), connection_mode,
                      bool(payload.get("is_enabled", False)), bool(payload.get("group_require_mention", True)),
                      bool(payload.get("allow_private_chat", True)), json.dumps(allowed, ensure_ascii=False),
                      payload.get("default_prompt_template_id") or None, bool(payload.get("daily_report_enabled", False)),
                      report_time, timezone, json.dumps(report_chats, ensure_ascii=False),
                      payload.get("daily_report_prompt_template_id") or None)
            if app_id:
                cursor.execute("""UPDATE ai.feishu_app SET config_code=%s,config_name=%s,app_id=%s,connection_mode=%s,is_enabled=%s,
                    group_require_mention=%s,allow_private_chat=%s,allowed_chat_ids=%s::jsonb,default_prompt_template_id=%s,
                    daily_report_enabled=%s,daily_report_time=%s::time,daily_report_timezone=%s,daily_report_chat_ids=%s::jsonb,
                    daily_report_prompt_template_id=%s,app_secret_ciphertext=COALESCE(%s,app_secret_ciphertext),
                    app_secret_nonce=COALESCE(%s,app_secret_nonce),verification_token_ciphertext=COALESCE(%s,verification_token_ciphertext),
                    verification_token_nonce=COALESCE(%s,verification_token_nonce),encrypt_key_ciphertext=COALESCE(%s,encrypt_key_ciphertext),
                    encrypt_key_nonce=COALESCE(%s,encrypt_key_nonce),updated_by=%s,updated_at=NOW() WHERE feishu_app_id=%s""",
                    (*values, *app_pair, *verify_pair, *encrypt_pair, context.user_id, app_id))
                saved = app_id
            else:
                cursor.execute("""INSERT INTO ai.feishu_app(config_code,config_name,app_id,connection_mode,is_enabled,group_require_mention,
                    allow_private_chat,allowed_chat_ids,default_prompt_template_id,daily_report_enabled,daily_report_time,daily_report_timezone,
                    daily_report_chat_ids,daily_report_prompt_template_id,app_secret_ciphertext,app_secret_nonce,
                    verification_token_ciphertext,verification_token_nonce,encrypt_key_ciphertext,encrypt_key_nonce,created_by,updated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::time,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING feishu_app_id""", (*values, *app_pair, *verify_pair, *encrypt_pair, context.user_id, context.user_id))
                saved = int(cursor.fetchone()["feishu_app_id"])
            audit(cursor, context=context, action="ai.feishu_app.update" if app_id else "ai.feishu_app.create",
                  target_type="ai.feishu_app", target_id=saved,
                  after={"config_code":config_code, "connection_mode":connection_mode,
                         "daily_report_enabled":bool(payload.get("daily_report_enabled")),
                         "app_secret_changed":bool(app_secret), "verification_token_changed":bool(verification),
                         "encrypt_key_changed":bool(encrypt_key)}, ip_address=ip_address, user_agent=user_agent)
        return {"feishu_app_id":saved}

    def toggle_app(self, context, app_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                """UPDATE ai.feishu_app SET is_enabled=NOT is_enabled,updated_by=%s,updated_at=NOW()
                   WHERE feishu_app_id=%s AND deleted_at IS NULL RETURNING config_code,is_enabled""",
                (context.user_id, app_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("飞书应用配置不存在")
            audit(cursor, context=context, action="ai.feishu_app.toggle", target_type="ai.feishu_app", target_id=app_id,
                  after={"config_code": row["config_code"], "is_enabled": row["is_enabled"]},
                  ip_address=ip_address, user_agent=user_agent)
        return {"feishu_app_id": app_id, "is_enabled": row["is_enabled"]}

    def test_app(self, context, app_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        config, error, target = self._app(app_id), None, None
        try:
            self._tenant_token(config, force=True)
            targets = list(config.get("daily_report_chat_ids") or []) or list(config.get("allowed_chat_ids") or [])
            if not targets:
                raise ValueError("请先填写报告接收群聊 ID 或响应群聊白名单，端到端测试需要一个目标群 chat_id")
            target = str(targets[0])
            self._send_to_chat(config, target, "经营配置中心：飞书机器人端到端连接测试成功。")
        except Exception as exc:
            error = f"飞书连接失败：{self._safe_error(exc)}"[:500]
        status = "success" if not error else "failed"
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.feishu_app SET last_test_status=%s,last_tested_at=NOW(),last_error_summary=%s WHERE feishu_app_id=%s", (status, error, app_id))
            audit(cursor, context=context, action="ai.feishu_app.test", target_type="ai.feishu_app", target_id=app_id,
                  after={"status":status, "error":error}, ip_address=ip_address, user_agent=user_agent)
        if error:
            raise ValueError(error)
        return {"ok":True, "message":f"测试消息已发送至群聊 {self._mask_id(target)}",
                "credential":"tenant_access_token由后端自动申请、缓存并刷新，未持久化"}

    def verification_relays(self, context):
        """返回验证码转发配置，不返回任何长期凭据或验证码明文。"""

        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT r.verification_relay_config_id,r.config_code,r.config_name,r.feishu_app_id,
                a.config_name AS feishu_app_name,r.chat_id,r.mention_open_ids,r.platform_scopes,r.timeout_seconds,
                r.is_enabled,r.last_test_status,r.last_tested_at,r.last_error_summary,r.created_at,r.updated_at,
                a.is_enabled AS feishu_app_enabled
                FROM ai.verification_relay_config r JOIN ai.feishu_app a ON a.feishu_app_id=r.feishu_app_id
                ORDER BY r.verification_relay_config_id""")
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _normalize_string_list(values, label):
        if isinstance(values, str):
            values = values.split(",")
        normalized = []
        for value in values or []:
            item = str(value).strip()
            if item and item not in normalized:
                normalized.append(item)
        if len(normalized) > 50:
            raise ValueError(f"{label}最多填写50项")
        return normalized

    def save_verification_relay(self, context, payload, relay_id=None, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        config_code = code(payload.get("config_code"))
        config_name = text(payload.get("config_name"), "配置名称", maximum=120)
        try:
            feishu_app_id = int(payload.get("feishu_app_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("必须选择一个飞书应用配置") from exc
        chat_ids = self._normalize_chat_ids([payload.get("chat_id")], "验证码转发群聊")
        if not chat_ids:
            raise ValueError("验证码转发群聊必须填写一个 oc_ 开头的群聊 ID")
        mention_ids = self._normalize_string_list(payload.get("mention_open_ids"), "负责人 open_id")
        platforms = self._normalize_string_list(payload.get("platform_scopes"), "平台范围")
        try:
            timeout_seconds = int(payload.get("timeout_seconds") or 300)
        except (TypeError, ValueError) as exc:
            raise ValueError("验证码等待时长必须是整数秒") from exc
        if not 30 <= timeout_seconds <= 900:
            raise ValueError("验证码等待时长必须在30到900秒之间")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT feishu_app_id,config_name FROM ai.feishu_app WHERE feishu_app_id=%s AND deleted_at IS NULL", (feishu_app_id,))
            app = cursor.fetchone()
            if not app:
                raise ValueError("所选飞书应用配置不存在")
            old = None
            if relay_id:
                cursor.execute("SELECT verification_relay_config_id FROM ai.verification_relay_config WHERE verification_relay_config_id=%s FOR UPDATE", (relay_id,))
                old = cursor.fetchone()
                if not old:
                    raise ValueError("验证码转发配置不存在")
            values = (config_code, config_name, feishu_app_id, chat_ids[0], json.dumps(mention_ids, ensure_ascii=False),
                      json.dumps(platforms, ensure_ascii=False), timeout_seconds, bool(payload.get("is_enabled", False)))
            if relay_id:
                cursor.execute("""UPDATE ai.verification_relay_config SET config_code=%s,config_name=%s,feishu_app_id=%s,
                    chat_id=%s,mention_open_ids=%s::jsonb,platform_scopes=%s::jsonb,timeout_seconds=%s,is_enabled=%s,
                    updated_by=%s,updated_at=NOW() WHERE verification_relay_config_id=%s""",
                    (*values, context.user_id, relay_id))
                saved = relay_id
            else:
                cursor.execute("""INSERT INTO ai.verification_relay_config(config_code,config_name,feishu_app_id,chat_id,
                    mention_open_ids,platform_scopes,timeout_seconds,is_enabled,created_by,updated_by)
                    VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s) RETURNING verification_relay_config_id""",
                    (*values, context.user_id, context.user_id))
                saved = int(cursor.fetchone()["verification_relay_config_id"])
            audit(cursor, context=context, action="ai.verification_relay.update" if relay_id else "ai.verification_relay.create",
                  target_type="ai.verification_relay_config", target_id=saved,
                  after={"config_code":config_code,"feishu_app_id":feishu_app_id,"platform_scopes":platforms,
                         "is_enabled":bool(payload.get("is_enabled", False))}, ip_address=ip_address, user_agent=user_agent)
        return {"verification_relay_config_id": saved}

    def toggle_verification_relay(self, context, relay_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("""UPDATE ai.verification_relay_config SET is_enabled=NOT is_enabled,updated_by=%s,updated_at=NOW()
                WHERE verification_relay_config_id=%s RETURNING config_code,is_enabled""", (context.user_id, relay_id))
            row = cursor.fetchone()
            if not row:
                raise ValueError("验证码转发配置不存在")
            audit(cursor, context=context, action="ai.verification_relay.toggle", target_type="ai.verification_relay_config",
                  target_id=relay_id, after={"config_code":row["config_code"],"is_enabled":row["is_enabled"]},
                  ip_address=ip_address, user_agent=user_agent)
        return {"verification_relay_config_id": relay_id, "is_enabled": row["is_enabled"]}

    def delete_verification_relay(self, context, relay_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("DELETE FROM ai.verification_relay_config WHERE verification_relay_config_id=%s RETURNING config_code", (relay_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("验证码转发配置不存在")
            audit(cursor, context=context, action="ai.verification_relay.delete", target_type="ai.verification_relay_config",
                  target_id=relay_id, after={"config_code":row["config_code"]}, ip_address=ip_address, user_agent=user_agent)
        return {"verification_relay_config_id": relay_id, "deleted": True}

    def _verification_relay(self, relay_id):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT r.*,a.config_code AS feishu_config_code,a.config_name AS feishu_config_name,
                a.app_id,a.app_secret_ciphertext,a.app_secret_nonce,a.is_enabled AS feishu_app_enabled
                FROM ai.verification_relay_config r JOIN ai.feishu_app a ON a.feishu_app_id=r.feishu_app_id
                WHERE r.verification_relay_config_id=%s""", (relay_id,))
            row = cursor.fetchone()
        if not row:
            raise ValueError("验证码转发配置不存在")
        return dict(row)

    def test_verification_relay(self, context, relay_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        relay = self._verification_relay(relay_id)
        error = None
        try:
            if not relay["feishu_app_enabled"]:
                raise ValueError("关联的飞书应用未启用")
            app = self._app(relay["feishu_app_id"])
            self._send_post_to_chat(app, relay["chat_id"], self._verification_message(relay, test=True))
        except Exception as exc:
            error = f"验证码转发测试失败：{self._safe_error(exc)}"[:500]
        status = "success" if not error else "failed"
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.verification_relay_config SET last_test_status=%s,last_tested_at=NOW(),last_error_summary=%s WHERE verification_relay_config_id=%s",
                           (status, error, relay_id))
            audit(cursor, context=context, action="ai.verification_relay.test", target_type="ai.verification_relay_config",
                  target_id=relay_id, after={"status":status,"error":error}, ip_address=ip_address, user_agent=user_agent)
        if error:
            raise ValueError(error)
        return {"ok": True, "message": f"验证码转发测试消息已发送至群聊 {self._mask_id(relay['chat_id'])}"}

    def _select_verification_relay(self, platform):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT r.*,a.config_code AS feishu_config_code,a.app_id,a.app_secret_ciphertext,
                a.app_secret_nonce,a.is_enabled AS feishu_app_enabled
                FROM ai.verification_relay_config r JOIN ai.feishu_app a ON a.feishu_app_id=r.feishu_app_id
                WHERE r.is_enabled AND a.is_enabled AND a.deleted_at IS NULL
                ORDER BY r.verification_relay_config_id""")
            rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            scopes = list(row.get("platform_scopes") or [])
            if not scopes or platform in scopes:
                return row
        return None

    def _verification_message(self, relay, *, platform="", company="", shop="", purpose="", page_url="", challenge_type="verification_code", test=False):
        if test:
            lines = ["自动化验证码转发机器人连接测试成功。", "收到实际任务后，负责人直接在本群回复验证码即可。"]
        elif challenge_type == "archive_password":
            # 归档密码挑战也覆盖平台下发的文件提取码/文档密码。
            # 通过 purpose 选择文案，保持历史 ZIP 解压挑战的兼容性，
            # 同时让快手 XLSX 提取码不会被误称为压缩包密码。
            password_label = "文件提取码" if ("提取码" in purpose or "文档" in purpose) else "压缩包解压密码"
            lines = [f"自动化任务需要{password_label}，请负责人回复平台发送的原始密码。", f"平台：{platform}", f"公司：{company}", f"店铺：{shop}", f"用途：{purpose}"]
            if page_url:
                lines.append(f"页面：{page_url[:300]}")
        else:
            lines = ["自动化任务需要验证码，请负责人回复验证码。", f"平台：{platform}", f"公司：{company}", f"店铺：{shop}", f"用途：{purpose}"]
            if page_url:
                lines.append(f"页面：{page_url[:300]}")
        # 重试挑战必须把上一次失败明确告诉负责人，避免看起来像机器人
        # 在无原因地重复发送同一条请求。
        if not test and ("验证码错误" in purpose or "解压密码错误" in purpose):
            if challenge_type == "verification_code":
                notice = "上一次验证码输入错误，请重新输入。"
            elif "提取码" in purpose or "文档" in purpose:
                notice = "上一次文件提取码输入错误，请重新输入。"
            else:
                notice = "上一次解压密码输入错误，请重新输入。"
            lines.insert(0, notice)
        content = [{"tag":"text","text":"\n".join(lines)}]
        for open_id in list(relay.get("mention_open_ids") or []):
            content.append({"tag":"at","user_id":str(open_id),"user_name":"负责人"})
        return {"zh_cn":{"title":"自动化验证码","content":[content]}}

    def create_verification_challenge(self, payload):
        challenge_type = str(payload.get("challenge_type") or "verification_code").strip()
        if challenge_type not in {"verification_code", "archive_password"}:
            raise ValueError("自动化 Challenge 类型无效")
        platform = text(payload.get("platform"), "平台", maximum=64)
        company = text(payload.get("company"), "公司", maximum=200)
        shop = text(payload.get("shop"), "店铺", maximum=200)
        default_purpose = "订单报表下载验证码" if challenge_type == "verification_code" else "订单报表 ZIP 解压密码"
        purpose = text(payload.get("purpose") or default_purpose, "自动化请求用途", maximum=120)
        page_url = str(payload.get("page_url") or "")[:1000]
        relay = self._select_verification_relay(platform)
        if not relay:
            raise ValueError(f"没有启用的{platform}验证码转发配置")
        return self.sms.create(payload, relay, challenge_type, platform, company, shop, purpose, page_url)

    @staticmethod
    def _automation_notice_message(relay, *, platform, company, shop, purpose):
        lines = [
            "自动化任务遇到抖店登录滑块，需要人工完成验证。",
            f"平台：{platform}",
            f"公司：{company}",
            f"店铺：{shop}",
            f"用途：{purpose}",
            "请打开对应 profile 手动完成滑块；程序会持续等待，完成后继续进入店铺选择或业务页面。",
        ]
        content = [{"tag": "text", "text": "\n".join(lines)}]
        for open_id in list(relay.get("mention_open_ids") or []):
            content.append({"tag": "at", "user_id": str(open_id), "user_name": "负责人"})
        return {"zh_cn": {"title": "自动化登录提醒", "content": [content]}}

    def send_automation_notice(self, payload):
        """Send a Feishu human-handoff notice without creating a reply challenge."""

        platform = text(payload.get("platform"), "平台", maximum=64)
        company = text(payload.get("company"), "公司", maximum=200)
        shop = text(payload.get("shop"), "店铺", maximum=200)
        purpose = text(payload.get("purpose"), "自动化提醒用途", maximum=120)
        relay = self._select_verification_relay(platform)
        if not relay:
            raise ValueError(f"没有启用的{platform}验证码转发配置")
        app = self._app(relay["feishu_app_id"])
        self._send_post_to_chat(
            app,
            relay["chat_id"],
            self._automation_notice_message(
                relay,
                platform=platform,
                company=company,
                shop=shop,
                purpose=purpose,
            ),
        )
        return {"sent": True}

    def get_verification_challenge(self, challenge_id):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT c.*,r.timeout_seconds FROM ai.verification_challenge c
                JOIN ai.verification_relay_config r ON r.verification_relay_config_id=c.verification_relay_config_id
                WHERE c.challenge_uuid=%s""", (challenge_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("验证码请求不存在")
            item = dict(row)
            if item["status"] == "pending" or item.get("auto_until"):
                cursor.execute("UPDATE ai.verification_challenge SET status='expired',answer_ciphertext=NULL,answer_nonce=NULL WHERE challenge_uuid=%s AND status IN ('pending','answered') AND expires_at<=NOW() RETURNING status", (challenge_id,))
                if cursor.fetchone():
                    item["status"] = "expired"
            answer = None
            if item["status"] == "answered" and item.get("answer_ciphertext"):
                answer = self.cipher.decrypt(self.cipher.decode(item["answer_ciphertext"]), self.cipher.decode(item["answer_nonce"]),
                                             context=f"verification:{item['challenge_uuid']}")
            return {"challenge_id": str(item["challenge_uuid"]), "challenge_type": item["challenge_type"], "status": item["status"],
                    "timeout_seconds": 300, "answer": answer, "answer_source": item.get("answer_source"),
                    "expires_at": item["expires_at"].isoformat(), "human_fallback": bool(item.get("human_fallback_at"))}

    @staticmethod
    def _challenge_candidates(challenge_type, content):
        """按 Challenge 类型解析消息；普通聊天文本不能误当作答案。"""

        normalized = html.unescape(str(content or ""))
        normalized = re.sub(r"<at\b[^>]*>.*?</at>", " ", normalized, flags=re.IGNORECASE | re.DOTALL)
        normalized = normalized.replace("\u200b", " ").replace("\ufeff", " ")
        normalized = re.sub(r"@[A-Za-z0-9_:\-]+", " ", normalized)
        if challenge_type == "archive_password":
            labeled = re.findall(r"(?:文件提取码|提取码|解压密码|压缩包密码|密码|password)\s*[:：=]?\s*([^\s，。,；;]{4,128})", normalized, flags=re.IGNORECASE)
            if labeled:
                return labeled
            stripped = normalized.strip()
            if stripped and len(stripped) <= 128 and len(stripped) >= 4 and not re.search(r"[\u4e00-\u9fff\s]", stripped):
                return [stripped]
            return []
        labeled = re.findall(r"(?:验证码|校验码|verification\s*code|code)\s*[:：=]?\s*([A-Za-z0-9]{4,12})(?![A-Za-z0-9_-])", normalized, flags=re.IGNORECASE)
        if labeled:
            return labeled
        standalone = re.sub(r"@[^\s]+", " ", normalized).strip()
        return [standalone] if re.fullmatch(r"[A-Za-z0-9]{4,12}", standalone) else []

    @staticmethod
    def _verification_candidates(content):
        """兼容旧调用方：默认按短信验证码解析。"""

        return FeishuService._challenge_candidates("verification_code", content)

    def _has_pending_challenge(self, config, chat_id):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT 1 FROM ai.verification_challenge c
                JOIN ai.verification_relay_config r ON r.verification_relay_config_id=c.verification_relay_config_id
                WHERE r.feishu_app_id=%s AND r.chat_id=%s AND c.status='pending' AND c.expires_at>NOW()
                LIMIT 1""", (config["feishu_app_id"], chat_id))
            return cursor.fetchone() is not None

    def _answer_pending_challenge(self, config, chat_id, actor_id, content):
        # Compatibility for old callers; real intake always supplies message identity/time.
        from .sms import SmsMessage
        message = SmsMessage("compat_" + str(time.time_ns()), chat_id, "user", (("open_id", actor_id),), int(time.time() * 1000), content)
        return self._answer_human_message(config, message)

    def _answer_human_message(self, config, message):
        if not message or message.sender_type != "user":
            return None
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT c.*,r.mention_open_ids,EXTRACT(EPOCH FROM (NOW()-c.created_at)) AS challenge_age_seconds FROM ai.verification_challenge c
                JOIN ai.verification_relay_config r ON r.verification_relay_config_id=c.verification_relay_config_id
                WHERE r.feishu_app_id=%s AND r.chat_id=%s AND r.is_enabled AND c.status='pending' AND c.expires_at>NOW()
                FOR UPDATE OF c""",
                (config["feishu_app_id"], message.chat_id))
            rows = [dict(row) for row in cursor.fetchall()]
            now_ms = self.sms.message_now_ms()
            rows = [row for row in rows if self.sms.message_cutoff_ms(row, now_ms) <= message.created_ms <= now_ms]
            if message.parent_id:
                rows = [row for row in rows if row["human_notice_message_id"] == message.parent_id]
            sender_ids = {v for k, v in message.sender_ids if k == "open_id"}
            rows = [row for row in rows if not row["mention_open_ids"] or sender_ids.intersection(row["mention_open_ids"])]
            if len(rows) != 1:
                return None
            row = rows[0]
            candidates = set(self._challenge_candidates(row["challenge_type"], message.text))
            if len(candidates) != 1:
                return None
            if not self.sms.store_answer(cursor, config["feishu_app_id"], row, message, next(iter(candidates)), "human"):
                return None
        self.sms.notify_answer(row["challenge_uuid"])
        return {"challenge_type": row["challenge_type"], "purpose": row.get("purpose") or ""}

    @staticmethod
    def _verification_answer_notice(challenge_type, purpose):
        if challenge_type == "verification_code":
            return "验证码已收到，自动化任务将继续。"
        if "提取码" in purpose or "文档" in purpose:
            return "文件提取码已收到，自动化任务将继续。"
        return "解压密码已收到，自动化任务将继续。"

    def receive(self, headers, raw_body, config_code):
        config = self._app_by_code(config_code)
        if not config or not config["is_enabled"] or config["connection_mode"] != "webhook":
            raise PermissionError("飞书Webhook未启用")
        payload = json.loads(raw_body.decode("utf-8"))
        verification = self._decrypt(config, "verification_token") if config.get("verification_token_ciphertext") else ""
        if payload.get("token") and payload.get("token") != verification:
            raise PermissionError("飞书Verification Token校验失败")
        if payload.get("encrypt"):
            encrypt_key = self._decrypt(config, "encrypt_key")
            signature = headers.get("X-Lark-Signature", "")
            timestamp = headers.get("X-Lark-Request-Timestamp", "")
            nonce = headers.get("X-Lark-Request-Nonce", "")
            expected = hashlib.sha256((timestamp + nonce + encrypt_key + raw_body.decode("utf-8")).encode()).hexdigest()
            if not signature or signature != expected:
                raise PermissionError("飞书事件签名校验失败")
            payload = self._decrypt_event(payload["encrypt"], encrypt_key)
        if payload.get("type") == "url_verification":
            return {"challenge":payload.get("challenge", "")}
        return self._enqueue(config, payload)

    def receive_sdk(self, config, payload):
        # 长连接客户端会长期持有启动时的配置快照。每条事件都重新读取数据库，
        # 让白名单、私聊和 @ 开关保存后立即生效，无需重启连接。
        current = self._app(config["feishu_app_id"])
        if not current["is_enabled"] or current["connection_mode"] != "long_connection":
            return
        self._enqueue(current, payload)

    def _enqueue(self, config, payload):
        header = payload.get("header") or {}
        event_id = str(header.get("event_id") or "")
        if not event_id:
            raise ValueError("飞书事件缺少event_id")
        with self.database.transaction() as cursor:
            event = payload.get("event") or {}; message = event.get("message") or {}
            sender = event.get("sender", {}).get("sender_id") or {}
            cursor.execute("""INSERT INTO ai.feishu_event_dedup(event_id,feishu_app_id,event_type,chat_id,message_id,open_id)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING RETURNING event_id""",
                (event_id, config["feishu_app_id"], header.get("event_type"),message.get("chat_id"),
                 message.get("message_id"),sender.get("open_id") or sender.get("union_id")))
            fresh = cursor.fetchone()
        if fresh:
            self.executor.submit(self._process_event, config, payload)
        return {"accepted":True, "duplicate":not bool(fresh)}

    def _process_event(self, config, payload):
        event_id = payload["header"]["event_id"]
        try:
            self._finish(event_id, "processing")
            if (payload.get("header") or {}).get("event_type") != "im.message.receive_v1":
                return self._finish(event_id, "ignored", "unsupported_event")
            event = payload.get("event") or {}
            message = event.get("message") or {}
            normalized = normalize_event(payload)
            if normalized:
                with self.database.transaction() as cursor:
                    cursor.execute("SELECT 1 FROM ai.verification_message_receipt WHERE feishu_app_id=%s AND message_id=%s", (config["feishu_app_id"], normalized.message_id))
                    if cursor.fetchone():
                        return self._finish(event_id, "ignored", "sms_message_already_consumed")
            sender_type = (event.get("sender") or {}).get("sender_type")
            if sender_type != "user":
                matched = self.sms.ingest_bot(config["feishu_app_id"], normalized)
                return self._finish(event_id, "success" if matched else "ignored", None if matched else "sms_bot_no_match")
            sender = event.get("sender", {}).get("sender_id") or {}
            actor_id = sender.get("open_id") or sender.get("union_id") or "unknown"
            chat_type, chat_id = message.get("chat_type"), message.get("chat_id")
            content = visible_text(message.get("message_type"), message.get("content") or "{}").strip()
            mentions = message.get("mentions") or []
            # 验证码回复不要求再次 @ 机器人；必须先于普通问答的群聊策略处理。
            answered = self._answer_human_message(config, normalized) if chat_id else None
            if answered:
                return self._finish(event_id, "success")
            if chat_id and self._has_pending_challenge(config, chat_id):
                return self._finish(event_id, "ignored", "automation_challenge_answer_not_found")
            if chat_type == "group" and config["group_require_mention"] and not mentions:
                return self._finish(event_id, "ignored", "mention_required")
            if chat_type == "p2p" and not config["allow_private_chat"]:
                return self._finish(event_id, "ignored", "private_chat_disabled")
            allowed = list(config["allowed_chat_ids"] or [])
            if chat_type == "group" and allowed and chat_id not in allowed:
                return self._finish(event_id, "ignored", "chat_not_allowed")
            for mention in mentions:
                content = content.replace(mention.get("key", "").strip(), "").strip()
            if not content:
                self._reply(config, message.get("message_id"), "请发送需要分析的问题。")
                return self._finish(event_id, "success")
            context = self._external_context(actor_id, "feishu")
            conversation = self.analysis.conversation_for_channel(context, channel="feishu", external_chat_id=chat_id)
            prompt_code = self._prompt_code(config.get("default_prompt_template_id"))
            answer, error = self._generate(context, conversation, content, prompt_code)
            self._reply(config, message.get("message_id"), error or answer or "未生成有效回答")
            self._finish(event_id, "success")
        except Exception as exc:
            error = self._safe_error(exc)
            self._finish(event_id, "failed", error)
            self._record_runtime_error(config["feishu_app_id"], error)

    def run_due_daily_reports(self, now=None):
        started = 0
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT * FROM ai.feishu_app WHERE is_enabled AND daily_report_enabled
                AND deleted_at IS NULL AND jsonb_array_length(daily_report_chat_ids)>0""")
            configs = [dict(row) for row in cursor.fetchall()]
        for config in configs:
            local_now = now.astimezone(ZoneInfo(config["daily_report_timezone"])) if now else datetime.now(ZoneInfo(config["daily_report_timezone"]))
            if local_now.time().replace(second=0, microsecond=0) < config["daily_report_time"].replace(second=0, microsecond=0):
                continue
            for chat_id in list(config["daily_report_chat_ids"] or []):
                with self.database.transaction() as cursor:
                    cursor.execute("""INSERT INTO ai.daily_report_run(feishu_app_id,report_date,chat_id,status,started_at)
                        VALUES (%s,%s,%s,'started',NOW()) ON CONFLICT(feishu_app_id,report_date,chat_id) DO NOTHING
                        RETURNING daily_report_run_id""", (config["feishu_app_id"], local_now.date(), chat_id))
                    row = cursor.fetchone()
                if row:
                    started += 1
                    self.executor.submit(self._run_daily_report, config, int(row["daily_report_run_id"]), chat_id, local_now.date())
        return started

    def _run_daily_report(self, config, run_id, chat_id, report_date):
        try:
            context = self._external_context(f"daily:{config['config_code']}:{chat_id}", "daily_report")
            conversation = self.analysis.conversation_for_channel(context, channel="feishu", external_chat_id=chat_id)
            prompt_code = self._prompt_code(config.get("daily_report_prompt_template_id") or config.get("default_prompt_template_id"))
            question = f"请生成 {report_date.isoformat()} 的每日经营分析报告。先从 ads、dim 实时元数据识别可用日期字段并确认最新完整数据日期，再分析核心指标、趋势、异常、口径、来源和数据限制。"
            answer, error = self._generate(context, conversation, question, prompt_code)
            if error:
                raise RuntimeError(error)
            self._send_to_chat(config, chat_id, answer or "未生成有效报告")
            status, category = "success", None
        except Exception as exc:
            status, category = "failed", self._safe_error(exc)
        with self.database.transaction() as cursor:
            cursor.execute("""UPDATE ai.daily_report_run SET status=%s,error_category=%s,completed_at=NOW()
                WHERE daily_report_run_id=%s""", (status, category, run_id))
            if status == "success":
                cursor.execute("UPDATE ai.feishu_app SET last_daily_report_date=%s,last_error_summary=NULL WHERE feishu_app_id=%s", (report_date, config["feishu_app_id"]))
            else:
                cursor.execute("UPDATE ai.feishu_app SET last_error_summary=%s WHERE feishu_app_id=%s", (category, config["feishu_app_id"]))

    def _generate(self, context, conversation, content, prompt_code=None):
        answer, error = "", None
        payload = {"conversation_uuid":str(conversation["conversation_uuid"]), "message":content}
        if prompt_code:
            payload["prompt_code"] = prompt_code
        for event_type, data in self.analysis.stream(context, payload, channel="feishu"):
            if event_type == "delta":
                answer += data["text"]
            elif event_type == "error":
                error = data["message"]
        return answer, error

    @staticmethod
    def _external_context(actor_id, channel):
        digest = int(hashlib.sha256(actor_id.encode()).hexdigest()[:12], 16)
        synthetic_id = -(digest or 1)
        return AuthContext(synthetic_id, f"{channel}:{actor_id}", actor_id, None, "飞书", False, channel, channel,
                           {"ai.analysis.view", "ai.analysis.query"}, {})

    def _prompt_code(self, prompt_id):
        if not prompt_id:
            return None
        with self.database.transaction() as cursor:
            cursor.execute("SELECT template_code FROM ai.prompt_template WHERE prompt_template_id=%s AND is_enabled AND deleted_at IS NULL", (prompt_id,))
            row = cursor.fetchone()
        return row["template_code"] if row else None

    def _tenant_token(self, config, force=False):
        with self._lock:
            cached = self._token_cache.get(config["config_code"])
            if cached and cached[1] > time.time() + 60 and not force:
                return cached[0]
        secret = self._decrypt(config, "app_secret")
        request = urllib.request.Request("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id":config["app_id"], "app_secret":secret}).encode(),
            headers={"Content-Type":"application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode())
        if data.get("code") != 0:
            raise RuntimeError("credential_error")
        token = data["tenant_access_token"]
        with self._lock:
            self._token_cache[config["config_code"]] = (token, time.time() + int(data.get("expire", 7200)))
        return token

    def _request_json(self, request, *, server_clock=None):
        request_started_ms = int(time.time() * 1000)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
                if server_clock:
                    server_clock(response.headers.get("Date"), request_started_ms)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
                api_code = detail.get("code")
                api_message = str(detail.get("msg") or "request_failed")[:80]
                raise RuntimeError(f"feishu_api_{api_code}:{api_message}") from exc
            except (ValueError, UnicodeDecodeError):
                raise RuntimeError(f"feishu_http_{exc.code}") from exc
        data = json.loads(body or "{}")
        if int(data.get("code", 0)) != 0:
            raise RuntimeError(f"feishu_api_{data.get('code')}:{str(data.get('msg') or 'unknown_error')[:120]}")
        return data

    def _reply(self, config, message_id, text_value):
        for part in self._message_chunks(text_value):
            request = urllib.request.Request(f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                data=json.dumps({"msg_type":"text", "content":json.dumps({"text":part}, ensure_ascii=False)}).encode(),
                headers={"Authorization":f"Bearer {self._tenant_token(config)}", "Content-Type":"application/json"}, method="POST")
            self._request_json(request)

    def _send_to_chat(self, config, chat_id, text_value):
        for part in self._message_chunks(text_value):
            request = urllib.request.Request(f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                data=json.dumps({"receive_id":str(chat_id), "msg_type":"text", "content":json.dumps({"text":part}, ensure_ascii=False)}).encode(),
                headers={"Authorization":f"Bearer {self._tenant_token(config)}", "Content-Type":"application/json"}, method="POST")
            self._request_json(request)

    def _send_post_to_chat(self, config, chat_id, content):
        """向验证码群发送带负责人 @ 的 post 消息。"""

        request = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=json.dumps({"receive_id":str(chat_id),"msg_type":"post","content":json.dumps(content, ensure_ascii=False)}).encode(),
            headers={"Authorization":f"Bearer {self._tenant_token(config)}","Content-Type":"application/json"},
            method="POST",
        )
        result = self._request_json(request)
        return (result.get("data") or {}).get("message_id")

    @staticmethod
    def _message_chunks(value):
        return [value[index:index+3500] for index in range(0, len(value), 3500)] or [value]

    @staticmethod
    def _normalize_chat_ids(values, label):
        if isinstance(values, str):
            values = values.split(",")
        normalized = []
        for value in values or []:
            chat_id = str(value).strip()
            if not chat_id:
                continue
            if not chat_id.startswith("oc_"):
                raise ValueError(f"{label}只能填写 oc_ 开头的飞书群聊 ID，不能填写群名称")
            if chat_id not in normalized:
                normalized.append(chat_id)
        return normalized

    def _app(self, app_id):
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.feishu_app WHERE feishu_app_id=%s AND deleted_at IS NULL", (app_id,))
            row = cursor.fetchone()
        if not row:
            raise ValueError("飞书配置不存在")
        return dict(row)

    def _app_by_code(self, config_code):
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.feishu_app WHERE config_code=%s AND deleted_at IS NULL", (config_code,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def _decrypt(self, config, label):
        return self.cipher.decrypt(self.cipher.decode(config[f"{label}_ciphertext"]), self.cipher.decode(config[f"{label}_nonce"]),
                                   context=f"feishu:{config['config_code']}:{label.replace('_','-')}")

    @staticmethod
    def _decrypt_event(encoded, key):
        data = base64.b64decode(encoded)
        cipher = Cipher(algorithms.AES(hashlib.sha256(key.encode()).digest()), modes.CBC(data[:16]))
        decryptor = cipher.decryptor()
        padded = decryptor.update(data[16:]) + decryptor.finalize()
        unpadder = PKCS7(128).unpadder()
        return json.loads((unpadder.update(padded) + unpadder.finalize()).decode())

    def _finish(self, event_id, status, error=None):
        with self.database.transaction() as cursor:
            cursor.execute("""UPDATE ai.feishu_event_dedup SET processing_status=%s,
                completed_at=CASE WHEN %s='processing' THEN NULL ELSE NOW() END,error_category=%s WHERE event_id=%s""",
                           (status, status, error, event_id))

    def _record_runtime_error(self, app_id, error):
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.feishu_app SET last_error_summary=%s WHERE feishu_app_id=%s", (error, app_id))

    @staticmethod
    def _safe_error(exc):
        value = str(exc).replace("\n", " ").replace("\r", " ")[:60]
        return value if value and not any(word in value.lower() for word in ("secret", "token", "cookie")) else type(exc).__name__

    @staticmethod
    def _mask_id(value):
        value = str(value or "")
        return value[:5] + "****" + value[-4:] if len(value) > 10 else "****"
