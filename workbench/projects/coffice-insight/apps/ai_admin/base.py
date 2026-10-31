from __future__ import annotations

import re

from apps.identity_access.audit import write_audit
from apps.identity_access.authorization import AuthorizationError


CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def require(context, permission: str) -> None:
    if context is None or not context.can(permission):
        raise AuthorizationError(f"缺少权限：{permission}")


def code(value, label: str = "编码") -> str:
    normalized = str(value or "").strip().lower()
    if not CODE_PATTERN.fullmatch(normalized):
        raise ValueError(f"{label}必须由小写字母开头，只能包含小写字母、数字和下划线")
    return normalized


def text(value, label: str, *, maximum: int, required: bool = True) -> str:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ValueError(f"{label}不能为空")
    if len(normalized) > maximum:
        raise ValueError(f"{label}不能超过{maximum}个字符")
    return normalized


def audit(cursor, *, context, action: str, target_type: str, target_id, before=None, after=None,
          ip_address="", user_agent=""):
    write_audit(cursor, action=action, target_type=target_type, target_id=target_id,
                actor=context, before=before, after=after, ip_address=ip_address,
                user_agent=user_agent)
