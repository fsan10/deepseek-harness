"""Deterministic SMS normalization and extraction; never sends SMS text to AI."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

CODE = r"(?P<code>[A-Za-z0-9]{4,8})(?![A-Za-z0-9_-])"
SEP = r"\s*(?:[（(]\s*区分大小写\s*[）)]\s*)?(?:(?:是|为)\s*)?[:：]?\s*"
RULES = {
    "jd_archive_password": (("【京东】", "以taskid-", "加密导出文件", "密码"), r"密码" + SEP + CODE),
    "kuaishou_export_otp": (("【快手小店】", "验证码", "正申请导出订单"), r"验证码" + SEP + CODE),
    "kuaishou_extract_code": (("【快手小店】", "提取码", "正申请文件提取码"), r"提取码" + SEP + CODE),
    "douyin_order_otp": (("【抖店】", "验证码"), r"验证码" + SEP + CODE),
    "douyin_archive_password": (("【抖音商城】", "订单导出文件已加密", "解压密码"), r"解压密码" + SEP + CODE),
}


@dataclass(frozen=True)
class SmsMessage:
    message_id: str
    chat_id: str
    sender_type: str
    sender_ids: tuple[tuple[str, str], ...]
    created_ms: int
    text: str = field(repr=False)
    parent_id: str = ""


def visible_text(message_type, content):
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (TypeError, ValueError):
            return ""
    if not isinstance(content, dict):
        return ""
    if message_type == "text":
        return content.get("text", "") if isinstance(content.get("text", ""), str) else ""
    if message_type not in {"post", "interactive", "card"}:
        return ""
    parts = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            tag = value.get("tag")
            if tag in {"at", "img", "image", "button", "select_static", "input"}:
                return
            for key, child in value.items():
                if key in {"text", "title"} and isinstance(child, str):
                    parts.append(child)
                elif key == "content" and isinstance(child, str) and tag in {"markdown", "lark_md", "plain_text", "text"}:
                    parts.append(child)
                elif isinstance(child, (dict, list)):
                    visit(child)
    visit(content)
    return "\n".join(parts)


def normalize(raw, sender_type, sender_ids):
    try:
        if raw.get("deleted") or raw.get("updated") or raw.get("chat_type", "group") != "group":
            return None
        if not raw["message_id"] or not raw["chat_id"] or int(raw["create_time"]) <= 0:
            return None
        return SmsMessage(str(raw["message_id"]), str(raw["chat_id"]), str(sender_type),
                          tuple(sender_ids), int(raw["create_time"]),
                          visible_text(raw.get("message_type", raw.get("msg_type")),
                                       raw.get("content", (raw.get("body") or {}).get("content"))),
                          str(raw.get("parent_id") or ""))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def normalize_history(item):
    if not isinstance(item, dict) or not isinstance(item.get("sender"), dict):
        return None
    sender = item["sender"]
    return normalize(item, sender.get("sender_type"), [(str(sender.get("id_type", "")), str(sender.get("id", "")))])


def normalize_event(payload):
    if (payload.get("header") or {}).get("event_type") != "im.message.receive_v1":
        return None
    event = payload.get("event") or {}
    sender = event.get("sender") or {}
    return normalize(event.get("message") or {}, sender.get("sender_type"),
                     [(str(k), str(v)) for k, v in (sender.get("sender_id") or {}).items() if v])


def route_key(platform, challenge_type, purpose):
    if platform == "京东" and challenge_type == "archive_password":
        return "jd_archive_password"
    if platform == "快手":
        return "kuaishou_extract_code" if challenge_type == "archive_password" else "kuaishou_export_otp"
    if platform == "抖音":
        return "douyin_archive_password" if challenge_type == "archive_password" else "douyin_order_otp"
    return None


def extract_code(text, key, business_reference=""):
    rule = RULES.get(key)
    if not rule or not all(keyword in text for keyword in rule[0]):
        return None
    if key == "jd_archive_password" and business_reference:
        if not re.fullmatch(r"taskid-[0-9]+", business_reference) or f"以{business_reference}-开头" not in text:
            return None
    codes = {m.group("code") for m in re.finditer(rule[1], text, re.IGNORECASE)}
    return next(iter(codes)) if len(codes) == 1 else None


def bot_matches(message, challenge, trusted_senders, now_ms):
    if not message or message.sender_type not in {"app", "bot"} or message.chat_id != challenge["chat_id"]:
        return None
    trusted = {(x.get("id_type"), x.get("id")) for x in trusted_senders}
    if not trusted.intersection(message.sender_ids):
        return None
    armed_ms = challenge.get("message_cutoff_ms", int(challenge["created_at"].timestamp() * 1000))
    if not armed_ms <= message.created_ms <= now_ms or now_ms - message.created_ms > 120_000:
        return None
    return extract_code(message.text, challenge["sms_route_key"], challenge.get("business_reference") or "")
