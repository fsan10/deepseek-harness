from __future__ import annotations

import hashlib
import os
import re
import secrets
import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parents[1] / "fund_split_adjust" / ".vendor"
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import bcrypt
except ImportError:  # pragma: no cover - 启动时由require_bcrypt给出明确错误
    bcrypt = None


USERNAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def require_bcrypt() -> None:
    if bcrypt is None:
        raise RuntimeError("缺少安全依赖bcrypt，请安装apps/fund_split_adjust/requirements.txt")


def normalize_username(value: object) -> str:
    username = str(value or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名须为3-64位小写字母、数字、点、横线或下划线，且以字母开头")
    return username


def validate_code(value: object, label: str = "编码") -> str:
    code = str(value or "").strip().lower()
    if not CODE_RE.fullmatch(code):
        raise ValueError(f"{label}须为2-64位小写字母、数字或下划线，且以字母开头")
    return code


def validate_password(value: object) -> str:
    password = str(value or "")
    if not 10 <= len(password) <= 128:
        raise ValueError("密码长度须为10-128位")
    if password.isspace() or password.strip() != password:
        raise ValueError("密码首尾不能包含空白字符")
    return password


def password_hash(password: object) -> str:
    require_bcrypt()
    rounds = min(15, max(10, int(os.getenv("AUTH_BCRYPT_ROUNDS", "12"))))
    return bcrypt.hashpw(validate_password(password).encode("utf-8"), bcrypt.gensalt(rounds)).decode("ascii")


def password_matches(password: object, encoded: str) -> bool:
    require_bcrypt()
    try:
        return bcrypt.checkpw(str(password or "").encode("utf-8"), encoded.encode("ascii"))
    except (ValueError, TypeError):
        return False


def random_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
