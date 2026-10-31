"""飞书异常提醒与共享人工处理配置。所有密钥仅在 DPAPI 密文中持久化。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .review_config import PROJECT
from .review_errors import ContractError, ReviewError
from .review_session_store import _dpapi


def config_path():
    return Path(os.environ.get("COLLECTION_ALERT_CONFIG_PATH") or PROJECT / "data" / "collection-alerts.enc")


def load_config():
    path = config_path()
    if not path.exists(): return {"enabled": False}
    try:
        value = json.loads(_dpapi(path.read_bytes(), decrypt=True))
        if not isinstance(value, dict): raise ValueError()
        return value
    except Exception:
        raise ContractError("飞书配置无法解密，请使用同一 Windows 用户重新保存") from None


def public_config():
    c = load_config()
    return {k: c.get(k, "") for k in ("app_id", "chat_id", "mention_open_id", "relay_url")} | {
        "enabled": bool(c.get("enabled")), "app_secret_configured": bool(c.get("app_secret")),
        "relay_token_configured": bool(c.get("relay_token"))}


def save_config(body):
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool): raise ContractError("飞书配置格式无效")
    previous = load_config()
    result = {"enabled": body["enabled"]}
    for key in ("app_id", "chat_id", "mention_open_id", "relay_url", "app_secret", "relay_token"):
        value = body.get(key, "")
        if not isinstance(value, str) or len(value) > 2000 or any(c in value for c in "\r\n\x00"):
            raise ContractError("飞书配置字段格式无效")
        result[key] = value.strip() if key not in ("app_secret", "relay_token") else value or previous.get(key, "")
    for key, prefix in (("chat_id", "oc_"), ("mention_open_id", "ou_")):
        if result[key] and not re.fullmatch(prefix + r"[A-Za-z0-9_-]+", result[key]): raise ContractError("飞书群或提醒人员标识格式无效")
    if result["relay_url"]:
        parsed = urlsplit(result["relay_url"])
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ContractError("人工处理服务地址应为不含令牌的 HTTP 服务地址")
    if result["enabled"] and not all(result[k] for k in ("app_id", "app_secret", "chat_id")):
        raise ContractError("启用飞书提醒前请填写 App ID、App Secret 和群 Chat ID")
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(_dpapi(json.dumps(result, ensure_ascii=False).encode()))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return public_config()


@contextlib.contextmanager
def shared_relay_environment():
    """仅当前显式登录进程使用，不修改 Windows 用户/系统环境。"""
    config = load_config()
    overrides = {}
    if config.get("relay_url") and config.get("relay_token"):
        overrides = {"AUTOMATION_RELAY_URL": config["relay_url"].rstrip("/"),
                     "AUTOMATION_RELAY_TOKEN_ENV": "KEFU_COLLECTION_RELAY_TOKEN", "KEFU_COLLECTION_RELAY_TOKEN": config["relay_token"]}
    old = {key: os.environ.get(key) for key in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for key, value in old.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def queue_alert(db, event_key, profile_id, category, message, event_id=None):
    try:
        status = "pending" if load_config().get("enabled") else "disabled"
    except ReviewError:
        status = "failed"
    with db:
        db.execute("INSERT OR IGNORE INTO collection_notifications(event_key,profile_id,category,message,status,created_at,event_id) VALUES(?,?,?,?,?,?,?)",
                   (event_key, profile_id, category, message, status, datetime.now(timezone.utc).isoformat(timespec="seconds"), event_id))


async def send_alert(config, message, *, transport=None):
    async with httpx.AsyncClient(trust_env=False, timeout=15, transport=transport, follow_redirects=False) as client:
        try:
            response = await client.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": config["app_id"], "app_secret": config["app_secret"]})
            token = response.json()
            if response.status_code != 200 or not isinstance(token, dict) or token.get("code") != 0 or not isinstance(token.get("tenant_access_token"), str) or not token["tenant_access_token"]:
                raise ReviewError("飞书鉴权失败，请检查应用配置")
            text = message
            if config.get("mention_open_id"):
                text = '<at user_id="' + config["mention_open_id"] + '">处理人员</at>\n' + text
            response = await client.post("https://open.feishu.cn/open-apis/im/v1/messages", params={"receive_id_type": "chat_id"},
                headers={"Authorization": "Bearer " + token["tenant_access_token"]},
                json={"receive_id": config["chat_id"], "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)})
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            identifier = data.get("message_id") if isinstance(data, dict) else None
            if response.status_code != 200 or not isinstance(body, dict) or body.get("code") != 0 or not isinstance(identifier, str) or not identifier:
                raise ReviewError("飞书发送失败，请检查应用权限、群配置和应用发布状态")
            return identifier
        except (httpx.RequestError, ValueError):
            raise ReviewError("飞书网络或响应异常，请检查配置后查看提醒记录") from None


async def flush_alerts(db):
    # 每轮最多一条，避免平台异常造成重复刷屏；未知发送结果不盲目重发。
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT * FROM collection_notifications WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row: db.execute("UPDATE collection_notifications SET status='sending' WHERE id=? AND status='pending'", (row["id"],))
        db.commit()
    except Exception:
        db.rollback(); raise
    if not row: return
    status, identifier, error = "sent", "", ""
    try:
        config = load_config()
        if config.get("enabled"):
            identifier = await send_alert(config, row["message"])
        else:
            status = "disabled"
    except ReviewError as exc:
        status, error = "failed", str(exc)
    with db:
        db.execute("UPDATE collection_notifications SET status=?,message_id=?,error_summary=?,finished_at=? WHERE id=?",
                   (status, identifier, error, datetime.now(timezone.utc).isoformat(timespec="seconds"), row["id"]))
