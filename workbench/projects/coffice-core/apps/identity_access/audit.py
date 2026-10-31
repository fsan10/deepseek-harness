from __future__ import annotations

import json
from typing import Any


SENSITIVE_KEYS = {
    "password", "password_hash", "new_password", "token", "csrf_token", "session_token",
    "api_key", "api_key_ciphertext", "api_key_nonce", "app_secret", "app_secret_ciphertext",
    "verification_token", "encrypt_key", "password_ciphertext", "password_nonce", "cookie",
}


def safe_snapshot(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {key: item for key, item in value.items() if key.lower() not in SENSITIVE_KEYS}


def write_audit(
    cursor,
    *,
    action: str,
    target_type: str,
    target_id: object | None,
    actor=None,
    before: dict | None = None,
    after: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    cursor.execute(
        """
        INSERT INTO iam.audit_log
            (user_id, username, action_code, target_type, target_id,
             change_before, change_after, ip_address, user_agent)
        VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
        """,
        (
            getattr(actor, "user_id", None), getattr(actor, "username", None), action,
            target_type, str(target_id)[:128] if target_id is not None else None,
            json.dumps(safe_snapshot(before), ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(safe_snapshot(after), ensure_ascii=False, default=str) if after is not None else None,
            ip_address, (user_agent or "")[:500] or None,
        ),
    )
