"""Database-backed SMS intake and timed human fallback for existing Challenges."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from email.utils import parsedate_to_datetime

from apps.ai_admin.base import audit, code, require, text
from .sms import bot_matches, normalize_history, route_key


class SmsRelay:
    def __init__(self, service):
        self.service = service
        self.database, self.cipher = service.database, service.cipher
        self.stop_event = threading.Event()
        self.thread = None
        self.clock_upper_offset_ms = None

    def observe_clock(self, http_date, request_started_ms):
        if not http_date:
            return
        try:
            # HTTP Date has whole-second precision. Use its upper bound so
            # clock drift cannot make a message predating registration eligible.
            server_upper_ms = int(parsedate_to_datetime(http_date).timestamp() * 1000) + 1000
            self.clock_upper_offset_ms = server_upper_ms - request_started_ms
        except (TypeError, ValueError, OverflowError):
            pass

    def message_now_ms(self):
        return int(time.time() * 1000) + (self.clock_upper_offset_ms or 0)

    def message_cutoff_ms(self, row, now_ms):
        if self.clock_upper_offset_ms is None:
            return int(row["created_at"].timestamp() * 1000)
        return now_ms - int(float(row["challenge_age_seconds"]) * 1000)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="feishu-sms-poll", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _loop(self):
        while not self.stop_event.wait(3):
            try:
                self.tick()
            except Exception:
                # Polling failures are handled per group. Never log message bodies.
                pass

    def configs(self, context):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT s.sms_forwarder_config_id,s.config_code,s.config_name,s.verification_relay_config_id,
                r.config_name AS relay_name,a.config_name AS feishu_app_name,r.chat_id,s.is_enabled,s.last_test_status,
                s.last_tested_at,s.last_error_summary,jsonb_array_length(s.trusted_senders)>0 AS sender_verified,
                s.signing_secret_ciphertext IS NOT NULL AS has_signing_secret
                FROM ai.sms_forwarder_config s JOIN ai.verification_relay_config r USING(verification_relay_config_id)
                JOIN ai.feishu_app a USING(feishu_app_id) ORDER BY s.sms_forwarder_config_id""")
            rows = [dict(row) for row in cursor.fetchall()]
        for row in rows:
            row["webhook_masked"] = "已配置（只写不读）"
            row["signing_secret_masked"] = "已配置" if row.pop("has_signing_secret") else "未配置"
        return rows

    @staticmethod
    def validate_webhook(value):
        parsed = urllib.parse.urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "open.feishu.cn" or parsed.query or parsed.fragment
                or not re.fullmatch(r"/open-apis/bot/v2/hook/[A-Za-z0-9-]+", parsed.path)):
            raise ValueError("请填写飞书自定义机器人的 HTTPS Webhook 地址")

    def _seal(self, value, config_code, label):
        if not value:
            return None, None
        encrypted, nonce = self.cipher.encrypt(value, context=f"sms-forwarder:{config_code}:{label}")
        return self.cipher.encode(encrypted), self.cipher.encode(nonce)

    def _secret(self, row, label):
        return self.cipher.decrypt(self.cipher.decode(row[f"{label}_ciphertext"]),
                                   self.cipher.decode(row[f"{label}_nonce"]),
                                   context=f"sms-forwarder:{row['config_code']}:{label.replace('_', '-')}")

    def save(self, context, payload, config_id=None, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        config_code = code(payload.get("config_code"))
        relay_id = int(payload.get("verification_relay_config_id") or 0)
        webhook = str(payload.get("webhook_url") or "").strip()
        signing_secret = str(payload.get("signing_secret") or "").strip()
        if webhook:
            self.validate_webhook(webhook)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT 1 FROM ai.verification_relay_config WHERE verification_relay_config_id=%s", (relay_id,))
            if not cursor.fetchone():
                raise ValueError("请选择已有的验证码接收配置")
            old = None
            if config_id:
                cursor.execute("SELECT * FROM ai.sms_forwarder_config WHERE sms_forwarder_config_id=%s FOR UPDATE", (config_id,))
                old = cursor.fetchone()
                if not old:
                    raise ValueError("短信转发配置不存在")
                if old["config_code"] != config_code:
                    raise ValueError("已保存的配置编码不能变更")
            elif not webhook:
                raise ValueError("新配置必须填写 Webhook 地址")
            changed = bool(webhook) or bool(signing_secret) or bool(old and old["verification_relay_config_id"] != relay_id)
            enabled = bool(payload.get("is_enabled", False))
            if enabled and (not old or changed or not old["trusted_senders"]):
                raise ValueError("请先保存配置并完成接收测试，再启用自动接收")
            values = (text(payload.get("config_name"), "配置名称", maximum=120), relay_id,
                      *self._seal(webhook, config_code, "webhook"), *self._seal(signing_secret, config_code, "signing-secret"), enabled)
            if config_id:
                cursor.execute("""UPDATE ai.sms_forwarder_config SET config_name=%s,verification_relay_config_id=%s,
                    webhook_ciphertext=COALESCE(%s,webhook_ciphertext),webhook_nonce=COALESCE(%s,webhook_nonce),
                    signing_secret_ciphertext=COALESCE(%s,signing_secret_ciphertext),signing_secret_nonce=COALESCE(%s,signing_secret_nonce),
                    is_enabled=%s,trusted_senders=CASE WHEN %s THEN '[]'::jsonb ELSE trusted_senders END,
                    updated_by=%s,updated_at=NOW() WHERE sms_forwarder_config_id=%s""",
                    (*values, changed, context.user_id, config_id))
                saved = config_id
            else:
                cursor.execute("""INSERT INTO ai.sms_forwarder_config(config_name,verification_relay_config_id,webhook_ciphertext,
                    webhook_nonce,signing_secret_ciphertext,signing_secret_nonce,is_enabled,config_code,created_by,updated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING sms_forwarder_config_id""",
                    (*values, config_code, context.user_id, context.user_id))
                saved = int(cursor.fetchone()["sms_forwarder_config_id"])
            audit(cursor, context=context, action="ai.sms_forwarder.update" if config_id else "ai.sms_forwarder.create",
                  target_type="ai.sms_forwarder_config", target_id=saved,
                  after={"config_code": config_code, "webhook_changed": bool(webhook), "enabled": enabled},
                  ip_address=ip_address, user_agent=user_agent)
        return {"sms_forwarder_config_id": saved}

    def toggle(self, context, config_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.sms_forwarder_config WHERE sms_forwarder_config_id=%s FOR UPDATE", (config_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("短信转发配置不存在")
            if not row["is_enabled"] and not row["trusted_senders"]:
                raise ValueError("请先完成接收测试，确认短信机器人的真实身份")
            cursor.execute("UPDATE ai.sms_forwarder_config SET is_enabled=NOT is_enabled,updated_by=%s,updated_at=NOW() WHERE sms_forwarder_config_id=%s RETURNING is_enabled",
                           (context.user_id, config_id))
            enabled = cursor.fetchone()["is_enabled"]
            audit(cursor, context=context, action="ai.sms_forwarder.toggle", target_type="ai.sms_forwarder_config",
                  target_id=config_id, after={"enabled": enabled}, ip_address=ip_address, user_agent=user_agent)
        return {"is_enabled": enabled}

    def delete(self, context, config_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT 1 FROM ai.verification_challenge WHERE sms_forwarder_config_id=%s AND status='pending' AND expires_at>NOW()", (config_id,))
            if cursor.fetchone():
                raise ValueError("还有正在等待的验证码请求，请先等待完成或取消任务")
            cursor.execute("UPDATE ai.verification_challenge SET sms_forwarder_config_id=NULL WHERE sms_forwarder_config_id=%s", (config_id,))
            cursor.execute("DELETE FROM ai.sms_forwarder_config WHERE sms_forwarder_config_id=%s", (config_id,))
            audit(cursor, context=context, action="ai.sms_forwarder.delete", target_type="ai.sms_forwarder_config",
                  target_id=config_id, ip_address=ip_address, user_agent=user_agent)
        return {"deleted": True}

    def history(self, app, chat_id, start_ms, end_ms):
        params = {"container_id_type": "chat", "container_id": chat_id,
                  "start_time": str(max(0, start_ms // 1000 - 1)), "end_time": str(end_ms // 1000 + 1),
                  "sort_type": "ByCreateTimeAsc", "page_size": "50", "card_msg_content_type": "user_card_content"}
        result, seen = [], set()
        for _ in range(20):
            request = urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/messages?" + urllib.parse.urlencode(params),
                headers={"Authorization": "Bearer " + self.service._tenant_token(app)})
            try:
                payload = self.service._request_json(request, server_clock=self.observe_clock)
            except RuntimeError as exc:
                if any(str(n) in str(exc) for n in (99991661, 99991663, 99991664, 99991668)):
                    self.service._tenant_token(app, force=True)
                    request.headers["Authorization"] = "Bearer " + self.service._tenant_token(app)
                    payload = self.service._request_json(request, server_clock=self.observe_clock)
                else:
                    raise
            data = payload.get("data") or {}
            if not isinstance(data.get("items", []), list):
                raise RuntimeError("history_invalid_response")
            result.extend(data.get("items", []))
            if not data.get("has_more"):
                return result
            token = data.get("page_token")
            if not token or token in seen:
                raise RuntimeError("history_invalid_pagination")
            seen.add(token)
            params["page_token"] = token
        raise RuntimeError("history_pagination_limit")

    @staticmethod
    def _error(exc):
        matched = re.search(r"feishu_api_([0-9]+)", str(exc))
        if matched:
            return "feishu_api_" + matched.group(1)
        safe_categories = {"receiver_disabled", "receiver_group_or_sender_not_found", "history_invalid_response",
                           "history_invalid_pagination", "history_pagination_limit", "credential_error"}
        return str(exc) if str(exc) in safe_categories else type(exc).__name__

    def test(self, context, config_id, *, ip_address="", user_agent=""):
        require(context, "ai.feishu_app.manage")
        with self.database.transaction() as cursor:
            cursor.execute("SELECT * FROM ai.sms_forwarder_config WHERE sms_forwarder_config_id=%s", (config_id,))
            row = cursor.fetchone()
        if not row:
            raise ValueError("短信转发配置不存在")
        row = dict(row)
        relay = self.service._verification_relay(row["verification_relay_config_id"])
        app = self.service._app(relay["feishu_app_id"])
        marker = "SMS_RELAY_BIND_" + uuid.uuid4().hex
        error, identities = None, []
        try:
            if not app["is_enabled"] or not relay["is_enabled"]:
                raise RuntimeError("receiver_disabled")
            start_ms = int(time.time() * 1000)
            self.history(app, relay["chat_id"], start_ms - 1000, start_ms)  # preflight before sending
            body = {"msg_type": "text", "content": {"text": f"【京东】【快手小店】【抖店】【抖音商城】短信转发机器人验证码接收测试：{marker}（无真实验证码）"}}
            if row.get("signing_secret_ciphertext"):
                timestamp = str(int(time.time()))
                secret = self._secret(row, "signing_secret")
                body.update(timestamp=timestamp, sign=base64.b64encode(hmac.new((timestamp + "\n" + secret).encode(), b"", hashlib.sha256).digest()).decode())
            request = urllib.request.Request(self._secret(row, "webhook"), data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
            self.service._request_json(request)
            # Group history can lag behind successful Webhook delivery.
            for _ in range(15):
                for item in self.history(app, relay["chat_id"], start_ms - 30_000, int(time.time() * 1000)):
                    msg = normalize_history(item)
                    if msg and msg.sender_type == "app" and marker in msg.text:
                        identities = [{"id_type": k, "id": v} for k, v in msg.sender_ids if k and v]
                        break
                if identities:
                    break
                time.sleep(2)
            if not identities:
                raise RuntimeError("receiver_group_or_sender_not_found")
        except Exception as exc:
            error = self._error(exc)
        with self.database.transaction() as cursor:
            cursor.execute("UPDATE ai.sms_forwarder_config SET trusted_senders=%s::jsonb,last_test_status=%s,last_tested_at=NOW(),last_error_summary=%s,is_enabled=CASE WHEN %s THEN FALSE ELSE is_enabled END WHERE sms_forwarder_config_id=%s",
                           (json.dumps(identities), "failed" if error else "success", error, bool(error), config_id))
            audit(cursor, context=context, action="ai.sms_forwarder.test", target_type="ai.sms_forwarder_config",
                  target_id=config_id, after={"success": not bool(error)}, ip_address=ip_address, user_agent=user_agent)
        if error:
            raise ValueError("短信机器人接收测试失败（" + error + "）；请检查已有接收应用的群历史读取权限、Webhook 和签名配置")
        return {"ok": True, "message": "发送与接收测试成功，短信机器人身份已绑定；现在可以启用自动接收。"}

    def create(self, payload, relay, challenge_type, platform, company, shop, purpose, page_url):
        key = route_key(platform, challenge_type, purpose)
        business_ref = str(payload.get("business_reference") or "")[:180]
        if key == "jd_archive_password" and business_ref and not re.fullmatch(r"taskid-[0-9]+", business_ref):
            raise ValueError("京东业务关联编号必须为实际 taskid-数字")
        force_human = bool(payload.get("force_human")) or "错误" in purpose
        # Before a download click we cannot yet know whether OTP verification
        # will open instead. Delay a disabled channel's manual request until
        # the encrypted ZIP phase explicitly resumes it (or the normal timeout).
        defer_notice = bool(payload.get("defer_human_notice")) and challenge_type == "archive_password" and not force_human
        with self.database.transaction() as cursor:
            # Serialize registration for this relay before testing indistinguishable streams.
            cursor.execute("SELECT verification_relay_config_id FROM ai.verification_relay_config WHERE verification_relay_config_id=%s FOR UPDATE", (relay["verification_relay_config_id"],))
            cursor.execute("SELECT * FROM ai.sms_forwarder_config WHERE verification_relay_config_id=%s AND is_enabled AND jsonb_array_length(trusted_senders)>0", (relay["verification_relay_config_id"],))
            forwarder = cursor.fetchone() if key else None
            stream_key = f"{relay['verification_relay_config_id']}:{platform}" if forwarder else None
            if stream_key:
                cursor.execute("SELECT 1 FROM ai.verification_challenge WHERE sms_stream_key=%s AND status='pending' AND expires_at>NOW()", (stream_key,))
                if cursor.fetchone():
                    raise ValueError("同一平台短信来源已有等待任务，请串行执行以避免店铺错配")
            automatic = bool(forwarder) and not force_human
            cursor.execute("""INSERT INTO ai.verification_challenge(verification_relay_config_id,challenge_type,platform_name,company_name,
                shop_name,purpose,page_url,expires_at,sms_forwarder_config_id,sms_route_key,sms_stream_key,business_reference,
                auto_until,human_fallback_at) VALUES (%s,%s,%s,%s,%s,%s,%s,NOW()+INTERVAL '300 seconds',%s,%s,%s,%s,
                NOW()+INTERVAL '120 seconds',CASE WHEN %s THEN NULL ELSE NOW() END) RETURNING challenge_uuid""",
                (relay["verification_relay_config_id"], challenge_type, platform, company, shop, purpose, page_url,
                 forwarder["sms_forwarder_config_id"] if forwarder else None, key, stream_key, business_ref, automatic or defer_notice))
            challenge_id = str(cursor.fetchone()["challenge_uuid"])
        if not automatic and not defer_notice:
            try:
                self.notify_fallback(challenge_id, "自动接收未启用或本次验证需人工处理")
            except Exception:
                with self.database.transaction() as cursor:
                    cursor.execute("UPDATE ai.verification_challenge SET status='cancelled' WHERE challenge_uuid=%s", (challenge_id,))
                raise
        return {"challenge_id": challenge_id, "timeout_seconds": 300, "automatic_seconds": 120, "automatic_enabled": automatic}

    def notify_fallback(self, challenge_id, reason):
        with self.database.transaction() as cursor:
            cursor.execute("SELECT c.*,r.feishu_app_id,r.chat_id,r.mention_open_ids,EXTRACT(EPOCH FROM (c.expires_at-NOW())) AS remaining_seconds FROM ai.verification_challenge c JOIN ai.verification_relay_config r USING(verification_relay_config_id) WHERE challenge_uuid=%s FOR UPDATE OF c", (challenge_id,))
            row = cursor.fetchone()
            if not row or row["status"] != "pending" or row["remaining_seconds"] <= 0 or row["human_notice_sent_at"]:
                return
            remaining = max(1, int(row["remaining_seconds"]))
            content = self.service._verification_message(
                row, platform=row["platform_name"], company=row["company_name"], shop=row["shop_name"],
                purpose=row["purpose"], page_url=row["page_url"], challenge_type=row["challenge_type"],
            )
            text = content["zh_cn"]["content"][0][0]
            text["text"] = f"{reason}。\n{text['text']}\n本次总等待 5 分钟，剩余约 {remaining} 秒；请回复本消息或直接发送原始代码。"
            app = self.service._app(row["feishu_app_id"])
            message_id = self.service._send_post_to_chat(app, row["chat_id"], content)
            cursor.execute("UPDATE ai.verification_challenge SET human_fallback_at=COALESCE(human_fallback_at,NOW()),human_notice_sent_at=NOW(),human_notice_message_id=%s WHERE challenge_uuid=%s", (message_id, challenge_id))

    def reject(self, challenge_id):
        with self.database.transaction() as cursor:
            cursor.execute("SELECT *,EXTRACT(EPOCH FROM (expires_at-NOW())) AS remaining_seconds FROM ai.verification_challenge WHERE challenge_uuid=%s FOR UPDATE", (challenge_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("验证码请求不存在")
            if row["remaining_seconds"] <= 0:
                raise ValueError("自动化 Challenge 已过期")
            if row["status"] not in {"pending", "answered"}:
                raise ValueError("自动化 Challenge 已取消")
            cursor.execute("""UPDATE ai.verification_challenge SET status='pending',answer_ciphertext=NULL,answer_nonce=NULL,
                answered_by=NULL,answered_at=NULL,answer_source=NULL,source_message_id=NULL,human_fallback_at=NOW(),
                human_notice_sent_at=NULL,answer_notice_sent_at=NULL WHERE challenge_uuid=%s""", (challenge_id,))
        self.notify_fallback(challenge_id, "平台判定收到的验证码或密码错误，自动接收已停止")
        return {"challenge_id": challenge_id, "status": "pending", "timeout_seconds": max(1, int(row["remaining_seconds"]))}

    def cancel(self, challenge_id):
        """Revoke a password listener when verification failed before download."""
        with self.database.transaction() as cursor:
            cursor.execute("""UPDATE ai.verification_challenge SET status='cancelled',answer_ciphertext=NULL,
                answer_nonce=NULL WHERE challenge_uuid=%s AND status IN ('pending','answered')""", (challenge_id,))
        return {"challenge_id": challenge_id, "status": "cancelled"}

    def resume(self, challenge_id):
        """Resend a pending manual request; preserve accepted answers and deadlines."""
        with self.database.transaction() as cursor:
            cursor.execute("SELECT *,expires_at<=NOW() AS elapsed FROM ai.verification_challenge WHERE challenge_uuid=%s FOR UPDATE", (challenge_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("验证码请求不存在")
            status = "expired" if row["elapsed"] else row["status"]
            if status != "pending":
                return {"challenge_id": challenge_id, "status": status}
            cursor.execute("""UPDATE ai.verification_challenge SET human_fallback_at=COALESCE(human_fallback_at,NOW()),
                human_notice_sent_at=NULL WHERE challenge_uuid=%s""", (challenge_id,))
        self.notify_fallback(challenge_id, "自动化节点已恢复，接收已启动，请人工提供原始代码")
        return {"challenge_id": challenge_id, "status": "pending"}

    def notify_answer(self, challenge_id):
        """Send a code-free receipt after commit; retry failed sends from tick."""
        try:
            with self.database.transaction() as cursor:
                cursor.execute("""SELECT c.*,r.feishu_app_id,r.chat_id FROM ai.verification_challenge c
                    JOIN ai.verification_relay_config r USING(verification_relay_config_id)
                    WHERE challenge_uuid=%s AND status='answered' AND expires_at>NOW()
                    AND answer_notice_sent_at IS NULL FOR UPDATE OF c""", (challenge_id,))
                row = cursor.fetchone()
                if not row:
                    return False
                notice = self.service._verification_answer_notice(row["challenge_type"], row["purpose"])
                self.service._send_to_chat(self.service._app(row["feishu_app_id"]), row["chat_id"], notice)
                cursor.execute("UPDATE ai.verification_challenge SET answer_notice_sent_at=NOW() WHERE challenge_uuid=%s", (challenge_id,))
            return True
        except Exception:
            # The accepted answer remains committed and usable. No SMS text is logged.
            return False

    def ingest_bot(self, app_id, message):
        if not message or message.sender_type not in {"app", "bot"}:
            return False
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT c.*,r.chat_id,s.trusted_senders,EXTRACT(EPOCH FROM (NOW()-c.created_at)) AS challenge_age_seconds FROM ai.verification_challenge c
                JOIN ai.verification_relay_config r USING(verification_relay_config_id)
                JOIN ai.sms_forwarder_config s USING(sms_forwarder_config_id)
                WHERE r.feishu_app_id=%s AND r.chat_id=%s AND r.is_enabled AND s.is_enabled AND c.status='pending'
                AND c.expires_at>NOW() AND c.auto_until>NOW() AND c.human_fallback_at IS NULL FOR UPDATE OF c""", (app_id, message.chat_id))
            candidates = []
            now_ms = self.message_now_ms()
            for row in cursor.fetchall():
                row["message_cutoff_ms"] = self.message_cutoff_ms(row, now_ms)
                answer = bot_matches(message, row, row["trusted_senders"], now_ms)
                if answer is not None:
                    candidates.append((row, answer))
            if len(candidates) != 1:
                return False
            row, answer = candidates[0]
            stored = self.store_answer(cursor, app_id, row, message, answer, "auto")
        if stored:
            self.notify_answer(row["challenge_uuid"])
        return stored

    def store_answer(self, cursor, app_id, challenge, message, answer, source):
        cursor.execute("INSERT INTO ai.verification_message_receipt(feishu_app_id,message_id,challenge_uuid) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING message_id", (app_id, message.message_id, challenge["challenge_uuid"]))
        if not cursor.fetchone():
            return False
        encrypted, nonce = self.cipher.encrypt(answer, context=f"verification:{challenge['challenge_uuid']}")
        actor = next((v for k, v in message.sender_ids if k == "open_id"), "sms_bot")
        cursor.execute("""UPDATE ai.verification_challenge SET status='answered',answer_ciphertext=%s,answer_nonce=%s,
            answered_by=%s,answered_at=NOW(),answer_source=%s,source_message_id=%s WHERE challenge_uuid=%s AND status='pending'""",
            (self.cipher.encode(encrypted), self.cipher.encode(nonce), actor, source, message.message_id, challenge["challenge_uuid"]))
        return cursor.rowcount == 1

    def tick(self):
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT challenge_uuid FROM ai.verification_challenge
                WHERE status='answered' AND expires_at>NOW() AND answer_notice_sent_at IS NULL LIMIT 50""")
            unacknowledged = [row["challenge_uuid"] for row in cursor.fetchall()]
        for challenge_id in unacknowledged:
            self.notify_answer(challenge_id)
        with self.database.transaction() as cursor:
            cursor.execute("""SELECT c.challenge_uuid,c.created_at,c.auto_until,c.auto_until<=NOW() AS auto_elapsed,c.human_fallback_at,c.human_notice_sent_at,r.feishu_app_id,r.chat_id
                FROM ai.verification_challenge c JOIN ai.verification_relay_config r USING(verification_relay_config_id)
                WHERE c.status='pending' AND c.expires_at>NOW() AND r.is_enabled""")
            pending = [dict(row) for row in cursor.fetchall()]
        groups = {}
        for row in pending:
            if row["human_fallback_at"] and not row["human_notice_sent_at"]:
                self.notify_fallback(row["challenge_uuid"], "验证码需人工处理，自动接收已停止")
            if row["auto_elapsed"] and not row["human_fallback_at"]:
                self.notify_fallback(row["challenge_uuid"], "自动接收 2 分钟内未获得有效验证码")
            key = (row["feishu_app_id"], row["chat_id"])
            groups.setdefault(key, []).append(row)
        for (app_id, chat_id), rows in groups.items():
            try:
                app = self.service._app(app_id)
                if not app["is_enabled"]:
                    continue
                start_ms = min(int(row["created_at"].timestamp() * 1000) for row in rows)
                for item in self.history(app, chat_id, start_ms - 30_000, int(time.time() * 1000)):
                    msg = normalize_history(item)
                    if msg and msg.sender_type == "user":
                        self.service._answer_human_message(app, msg)
                    else:
                        self.ingest_bot(app_id, msg)
            except Exception as exc:
                # Transient failures retry inside the 2-minute window. Permission failure falls back now.
                reason = self._error(exc)
                if reason in {"feishu_api_230027", "feishu_api_99991672", "feishu_api_230002", "feishu_api_230006"}:
                    for row in rows:
                        self.notify_fallback(row["challenge_uuid"], "短信自动读取权限或群访问不可用")
