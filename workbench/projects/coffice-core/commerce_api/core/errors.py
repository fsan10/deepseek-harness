"""Stable public errors; raw platform responses and credentials never escape."""
from __future__ import annotations

import re
from typing import Any


def redact(value: Any) -> str:
    text = str(value)
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL]", text)
    text = re.sub(r"wss?://[^\s\"'<>]+", "[CDP]", text)
    text = re.sub(r"(?i)(cookie|authorization|password|passwd|token|secret|signature|ticket|验证码|提取码)(\s*[=:：]\s*)[^\s,;，；]+", r"\1\2[REDACTED]", text)
    return text[:800]


class CommerceError(Exception):
    code = "FAILED"
    exit_code = 1
    recoverable = False

    def __init__(self, message: str, *, stage: str = "", hint: str = "", details: dict | None = None):
        super().__init__(redact(message))
        self.stage = stage
        self.hint = hint
        self.details = details or {}

    def public(self) -> dict:
        return {"code": self.code, "message": str(self), "stage": self.stage,
                "recoverable": self.recoverable, "hint": self.hint, "details": self.details}


class UsageError(CommerceError):
    code = "USAGE"


class AuthRequired(CommerceError):
    code = "AUTH_REQUIRED"
    exit_code = 2
    recoverable = True


class NeedsHuman(CommerceError):
    code = "NEEDS_HUMAN"
    exit_code = 2
    recoverable = True


class ChallengeExpired(NeedsHuman):
    code = "CHALLENGE_EXPIRED"


class ContractError(CommerceError):
    code = "CONTRACT_ERROR"


class NetworkError(CommerceError):
    code = "NETWORK_ERROR"
    recoverable = True


class OutcomeUnknown(CommerceError):
    code = "OUTCOME_UNKNOWN"
    recoverable = True


class NotReady(CommerceError):
    code = "NOT_READY"
    recoverable = True


class ContextRequired(CommerceError):
    code = "CONTEXT_REQUIRED"
    recoverable = True


class IdentityMismatch(CommerceError):
    code = "IDENTITY_MISMATCH"


class LockBusy(CommerceError):
    code = "LOCK_BUSY"
    recoverable = True


class SessionStoreError(CommerceError):
    code = "SESSION_STORE_ERROR"


class IntegrationUnavailable(CommerceError):
    code = "INTEGRATION_UNAVAILABLE"
    recoverable = True
